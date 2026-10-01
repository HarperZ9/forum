"""Bounded Windows Job process tree with file-backed stdio for native checks."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import tempfile
import time


class Startup(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR),
                ('title', w.LPWSTR), ('x', w.DWORD), ('y', w.DWORD), ('xs', w.DWORD),
                ('ys', w.DWORD), ('xc', w.DWORD), ('yc', w.DWORD), ('fill', w.DWORD),
                ('flags', w.DWORD), ('show', w.WORD), ('reserved2', w.WORD),
                ('reserved_ptr', c.c_void_p), ('stdin', w.HANDLE), ('stdout', w.HANDLE),
                ('stderr', w.HANDLE)]


class Process(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class Limits(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                ('min_working_set', c.c_size_t), ('max_working_set', c.c_size_t),
                ('active_limit', w.DWORD), ('affinity', c.c_size_t), ('priority', w.DWORD),
                ('scheduling', w.DWORD)]


class ExtendedLimits(c.Structure):
    _fields_ = [('basic', Limits), ('io', c.c_uint64 * 6), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process_memory', c.c_size_t),
                ('peak_job_memory', c.c_size_t)]


class Accounting(c.Structure):
    _fields_ = [('user', c.c_int64), ('kernel', c.c_int64), ('period_user', c.c_int64),
                ('period_kernel', c.c_int64), ('faults', w.DWORD), ('total', w.DWORD),
                ('active', w.DWORD), ('terminated', w.DWORD)]


def api():
    kernel = c.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        'SetInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        'QueryInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
        'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL,
                            w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(Startup), c.POINTER(Process)], w.BOOL),
        'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
        'ResumeThread': ([w.HANDLE], w.DWORD),
        'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
        'GetExitCodeProcess': ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
        'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
        'CloseHandle': ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(kernel, name).argtypes = args
        getattr(kernel, name).restype = result
    return kernel


def checked(success):
    if not success:
        raise c.WinError(c.get_last_error())


def active(kernel, job):
    state = Accounting()
    checked(kernel.QueryInformationJobObject(job, 1, c.byref(state), c.sizeof(state), None))
    return state.active


def execute(executable, args, env, cwd, streams, timeout, limit):
    import msvcrt
    kernel = api()
    job = kernel.CreateJobObjectW(None, None)
    checked(job)
    process = Process()
    assigned = False
    try:
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        checked(kernel.SetInformationJobObject(job, 9, c.byref(limits), c.sizeof(limits)))
        startup = Startup()
        startup.cb, startup.flags = c.sizeof(startup), 0x100  # STARTF_USESTDHANDLES
        handles = [msvcrt.get_osfhandle(f.fileno()) for f in streams]
        for handle in handles:
            os.set_handle_inheritable(handle, True)
        startup.stdin, startup.stdout, startup.stderr = handles
        command = c.create_unicode_buffer(subprocess.list2cmdline([str(executable), *map(str, args)]))
        environment = c.create_unicode_buffer('\0'.join(f'{k}={v}' for k, v in sorted(env.items())) + '\0\0')
        checked(kernel.CreateProcessW(str(executable), command, None, None, True,
                0x4 | 0x400 | 0x08000000, environment, str(cwd), c.byref(startup), c.byref(process)))
        checked(kernel.AssignProcessToJobObject(job, process.process))
        assigned = True
        if kernel.ResumeThread(process.thread) == 0xffffffff:
            checked(False)
        deadline = time.monotonic() + timeout
        while True:
            status = kernel.WaitForSingleObject(process.process, 50)
            if any(os.fstat(f.fileno()).st_size > limit for f in streams[1:]):
                raise ValueError('native process output limit exceeded')
            if status == 0:
                break
            if status != 258:
                raise OSError('native process wait failed')
            if time.monotonic() >= deadline:
                raise TimeoutError('native process deadline exceeded')
        code = w.DWORD()
        checked(kernel.GetExitCodeProcess(process.process, c.byref(code)))
        drain = time.monotonic() + 1
        while active(kernel, job):
            if time.monotonic() >= drain:
                raise RuntimeError('native process left an active descendant')
            time.sleep(0.01)
        return code.value
    finally:
        # No subprocess/pipe wait here. Terminate the owned job and close its
        # kill-on-close handle even when any earlier API or check raised.
        if process.process:
            if assigned:
                kernel.TerminateJobObject(job, 1)
            else:
                kernel.TerminateProcess(process.process, 1)
        kernel.CloseHandle(job)
        if process.process:
            kernel.WaitForSingleObject(process.process, 3000)
            kernel.CloseHandle(process.process)
        if process.thread:
            kernel.CloseHandle(process.thread)


def run_process(executable, args, env, cwd, wire, timeout=30, max_bytes=2_000_000):
    if os.name != 'nt':
        raise ValueError('native qualification requires Windows')
    if timeout <= 0 or max_bytes <= 0 or len(wire.encode('utf-8')) > max_bytes:
        raise ValueError('invalid process limits or oversized input')
    with tempfile.TemporaryDirectory(prefix='native-process-', dir=cwd) as temporary:
        paths = [Path(temporary) / name for name in ('stdin', 'stdout', 'stderr')]
        paths[0].write_text(wire, encoding='utf-8')
        with paths[0].open('rb') as stdin, paths[1].open('w+b') as stdout, paths[2].open('w+b') as stderr:
            code = execute(executable, args, env, cwd, [stdin, stdout, stderr], timeout, max_bytes)
            stdout.seek(0)
            stderr.seek(0)
            out, err = stdout.read(max_bytes + 1), stderr.read(max_bytes + 1)
            if len(out) > max_bytes or len(err) > max_bytes:
                raise ValueError('native process output limit exceeded')
            return code, out.decode('utf-8').replace('\r\n', '\n'), err.decode('utf-8').replace('\r\n', '\n')
