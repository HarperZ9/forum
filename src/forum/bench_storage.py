"""Storage-backend scaling benchmark: append throughput, verify latency, and
resident memory for InMemoryStorage, FileStorage, and SqliteStorage at scale.

The receipt it emits is the evidence that SqliteStorage removes the RAM ceiling
the other two backends share: InMemory and File both hold the whole ledger in
process memory, so their resident set grows ~linearly with entry count, while
SqliteStorage keeps it flat. Each (backend, count) cell is built in a FRESH
subprocess, because CPython does not reliably return freed memory to the OS, so
measuring several backends in one process would let an earlier peak mask a later
one.

Run the driver:  python -m forum.bench_storage
One cell (worker): python -m forum.bench_storage --worker sqlite 50000
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from statistics import median
from typing import Any

from forum.ledger import InMemoryStorage, Ledger
from forum.storage import FileStorage
from forum.sqlite_storage import SqliteStorage

SCHEMA = "forum.storage-scaling-benchmark/v1"


def _rss_bytes() -> int | None:
    """Current resident set size in bytes, stdlib-only and cross-platform.

    Windows via ctypes/psapi; POSIX via resource.getrusage (ru_maxrss is KiB on
    Linux, bytes on macOS). Returns None (an honest null) where neither works.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            # K32GetProcessMemoryInfo lives in kernel32 (no psapi.dll needed) and
            # is the reliable call once the HANDLE restype/argtypes are declared —
            # without them ctypes truncates the 64-bit pseudo-handle and it fails.
            get_mem = k32.K32GetProcessMemoryInfo
            get_mem.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
            get_mem.restype = wintypes.BOOL
            counters = _PMC()
            counters.cb = ctypes.sizeof(_PMC)
            if get_mem(k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return int(counters.WorkingSetSize)
        except Exception:
            return None
        return None
    try:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(maxrss) if sys.platform == "darwin" else int(maxrss) * 1024
    except Exception:
        return None


def _build_backend(name: str, tmp: str):
    if name == "memory":
        return InMemoryStorage(), None
    if name == "file":
        return FileStorage(tmp, fsync_each=False), None
    if name == "sqlite":
        return SqliteStorage(os.path.join(tmp, "ledger.db"), fsync_each=False), "sqlite"
    raise SystemExit(f"unknown backend: {name}")


def run_cell(backend: str, n: int) -> dict[str, Any]:
    """Build one backend with n entries; measure throughput, verify, and RSS."""
    seq = iter(float(t) for t in range(1, n + 2))
    with tempfile.TemporaryDirectory() as tmp:
        store, _ = _build_backend(backend, tmp)
        led = Ledger(store, clock=lambda: next(seq))
        rss_before = _rss_bytes()
        t0 = time.perf_counter()
        for i in range(n):
            led.append(actor="worker", kind="result", payload={"i": i})
        if hasattr(store, "sync"):
            store.sync()
        append_s = time.perf_counter() - t0
        rss_after = _rss_bytes()
        t1 = time.perf_counter()
        ok = led.verify()
        verify_s = time.perf_counter() - t1
        if hasattr(store, "close"):
            store.close()
    return {
        "backend": backend,
        "n": n,
        "append_per_sec": round(n / append_s) if append_s > 0 else None,
        "verify_ms": round(verify_s * 1000, 3),
        "rss_after_mb": round(rss_after / 1e6, 1) if rss_after else None,
        "rss_delta_mb": round((rss_after - rss_before) / 1e6, 1)
        if (rss_after and rss_before)
        else None,
        "verify_ok": ok,
    }


def benchmark_matrix(
    *, counts: list[int], backends: list[str], repeats: int = 3
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for backend in backends:
        for n in counts:
            reps = [_run_cell_subprocess(backend, n) for _ in range(repeats)]
            reps = [r for r in reps if r]
            if not reps:
                cases.append({"backend": backend, "n": n, "error": "no successful reps"})
                continue

            def _agg(key: str):
                vals = [r[key] for r in reps if r.get(key) is not None]
                if not vals:
                    return None
                return {"median": median(vals), "min": min(vals), "max": max(vals)}

            cases.append({
                "backend": backend, "n": n, "repeats": len(reps),
                "append_per_sec": _agg("append_per_sec"),
                "verify_ms": _agg("verify_ms"),
                "rss_after_mb": _agg("rss_after_mb"),
                "rss_delta_mb": _agg("rss_delta_mb"),
                "verify_ok": all(r.get("verify_ok") for r in reps),
            })
    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "rss_supported": _rss_bytes() is not None,
        "parameters": {"counts": counts, "backends": backends, "repeats": repeats,
                       "durability": "fsync_each=False (batched append; sync at end)"},
        "cases": cases,
    }


def _run_cell_subprocess(backend: str, n: int) -> dict[str, Any] | None:
    env = dict(os.environ)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = os.path.join(root, "src") + os.pathsep + env.get("PYTHONPATH", "")
    try:
        out = subprocess.run(
            [sys.executable, "-m", "forum.bench_storage", "--worker", backend, str(n)],
            capture_output=True, text=True, timeout=600, env=env,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def report_text(payload: dict[str, Any]) -> str:
    lines = [
        "Forum storage-scaling benchmark",
        f"schema: {payload['schema']}",
        f"python: {payload['python']} | platform: {payload['platform']} | rss_supported: {payload['rss_supported']}",
        "",
        f"{'backend':<8} {'n':>9} {'append/s (med)':>16} {'verify_ms':>10} {'rss_after_mb':>13}",
    ]
    for c in payload["cases"]:
        if "error" in c:
            lines.append(f"{c['backend']:<8} {c['n']:>9}  ERROR: {c['error']}")
            continue
        aps = c["append_per_sec"]["median"] if c.get("append_per_sec") else "-"
        vms = c["verify_ms"]["median"] if c.get("verify_ms") else "-"
        rss = c["rss_after_mb"]["median"] if c.get("rss_after_mb") else "null"
        lines.append(f"{c['backend']:<8} {c['n']:>9} {aps:>16} {vms:>10} {rss:>13}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--worker":
        backend, n = argv[1], int(argv[2])
        print(json.dumps(run_cell(backend, n)))
        return 0
    counts = [10_000, 50_000, 200_000]
    if "--quick" in argv:
        counts = [5_000, 20_000]
    payload = benchmark_matrix(
        counts=counts, backends=["memory", "file", "sqlite"], repeats=3
    )
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outdir = os.path.join(root, "benchmarks")
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, "storage_scaling.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(report_text(payload))
    print(f"\nreceipt: {outpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
