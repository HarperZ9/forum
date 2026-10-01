"""Release checksum files pass sha256sum -c on Linux, whichever OS wrote them.

The Windows release job wrote SHA256SUMS with Path.write_text, which emits CRLF
there. GNU sha256sum 8.32 and Perl shasum then fail to open the listed files.
The checksums workflow checks the same property across runners.
"""
import hashlib
import importlib
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
BUILDER = 'build_client_plugin'

pytestmark = pytest.mark.skipif(
    not (SCRIPTS / f'{BUILDER}.py').is_file(),
    reason='an extracted sdist carries no scripts directory',
)

LINE = re.compile(rb'[0-9a-f]{64}  [^\r\n/]+\n')


@pytest.fixture
def write_sums(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return importlib.import_module(BUILDER).write_sums


def test_checksum_file_is_lf_only_and_names_each_file(tmp_path, write_sums):
    alpha, beta = tmp_path / 'alpha.zip', tmp_path / 'beta.mcpb'
    alpha.write_bytes(b'alpha\n')
    beta.write_bytes(b'beta\r\n')
    target = tmp_path / 'SHA256SUMS'
    write_sums(target, [alpha, beta])
    data = target.read_bytes()
    assert b'\r' not in data
    lines = data.splitlines(keepends=True)
    assert all(LINE.fullmatch(line) for line in lines), data
    assert lines == [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'.encode()
                     for p in (alpha, beta)]


def test_no_script_writes_a_checksum_file_as_text():
    offenders = [f'{path.name}:{number}'
                 for path in sorted(SCRIPTS.glob('*.py'))
                 for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
                 if 'write_text(' in line and ('SUMS' in line or '.sha256' in line)]
    assert offenders == []
