"""Build local client archives from allowlisted source; never configures clients."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NODE_HASHES = {'node.exe': 'ba4e6d110e8c1592a1ecd390f6b05f3da124b13871a5be62b341a07a853c6c32',
               'LICENSE': 'ed34dd8e3f0a78dbaf00d0444ce8e285b015b765379c2e17880455f70370f8e9'}

def js(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def read(root, path):
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("source escapes package root")
    for parent in [target, *target.parents]:
        if parent == root.parent:
            break
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('links and reparse points are not package inputs')
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('source escapes package root')
    return target.read_bytes()


def version(root, config):
    data = read(root, config['version_file'])
    if config['version_file'].endswith('.toml'):
        return tomllib.loads(data.decode())['project']['version']
    return json.loads(data)['version']


def qualify(root, value, mode, tag):
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('source version must be MAJOR.MINOR.PATCH')
    head = git(root, 'rev-parse', 'HEAD')
    if mode == 'release':
        if not value.endswith('.0') or tag != 'v' + value:
            raise ValueError('mature release requires exact vMAJOR.MINOR.0 tag')
        if git(root, 'status', '--porcelain', '--untracked-files=all'):
            raise ValueError('release requires clean source')
        if git(root, 'rev-parse', tag + '^{commit}') != head:
            raise ValueError('release tag must name HEAD')
    return {'mode': mode, 'source_head': head, 'version': value,
            'published': False, 'tag': tag}


def payload(root, config, value):
    data = {}
    for name in git(root, 'ls-files', '-z').split('\0'):
        if not name:
            continue
        selected = name in config['files'] or any(name.startswith(r + '/') for r in config['roots'])
        excluded = (name.endswith(('.test.mjs', '.pyc')) or
                    any(part in {'__pycache__', 'scankii-synthetic-corpus', 'smallharness-dogfood-pack'}
                        for part in Path(name).parts) or name == 'demo/README.md')
        if selected and not excluded:
            data['server/' + name] = read(root, name)
    source = root / config.get('skill_source', 'client-plugin/skills/' + config['skill'])
    for path in sorted(source.rglob('*')):
        if path.is_dir():
            read_directory(path)
        elif path.is_file():
            data['skills/' + config['skill'] + '/' + path.relative_to(source).as_posix()] = read(root, path.relative_to(root))
    if config['tool'] == 'forum':
        data['server/serve.py'] = read(root, 'client-plugin/serve.py')
        data['skills/forum-route-preflight/SKILL.md'] = read(root, 'client-plugin/SKILL.md')
    manifest = {'name': config['name'], 'version': value, 'description': config['description'],
                'author': {'name': 'Zain Dana Harper'},
                'repository': 'https://github.com/HarperZ9/' + config['tool']}
    args = ['${PLUGIN_ROOT}/' + config['entry']]
    if config['runtime'] == 'python3':
        args = ['-I', '-S', '-B', *args]
    mcp = {'mcpServers': {config['tool']: {'type': 'stdio', 'command': config['runtime'], 'args': args}}}
    data['plugin.json'] = js(manifest)
    data['.claude-plugin/plugin.json'] = js(manifest)
    data['mcp.json'] = js(mcp)
    data['.mcp.json'] = js(json.loads(js(mcp).decode().replace('${PLUGIN_ROOT}', '${CLAUDE_PLUGIN_ROOT}')))
    data['README.md'] = read(root, 'client-plugin/README.md')
    data['PRIVACY.md'] = read(root, 'client-plugin/PRIVACY.md')
    return data


def read_directory(path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('linked directories are not package inputs')


def add_node(data, runtime, config, value):
    if config['runtime'] != 'node':
        raise ValueError('bundled Node only supports the Node tools')
    for name, expected in NODE_HASHES.items():
        content = read(runtime, name)
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('Node v24.21.0 Windows x64 runtime/license hash mismatch')
        data['runtime/' + name] = content
    cfg = {'type': 'stdio', 'command': '${PLUGIN_ROOT}/runtime/node.exe',
           'args': ['${PLUGIN_ROOT}/' + config['entry']]}
    data['mcp.json'] = js({'mcpServers': {config['tool']: cfg}})
    data['.mcp.json'] = data['mcp.json'].replace(b'${PLUGIN_ROOT}', b'${CLAUDE_PLUGIN_ROOT}')
    data['manifest.json'] = js({'manifest_version': '0.3', 'name': config['name'],
        'version': value, 'description': config['description'],
        'author': {'name': 'Zain Dana Harper'}, 'compatibility': {'platforms': ['win32']},
        'server': {'type': 'binary', 'entry_point': 'runtime/node.exe',
                   'mcp_config': {'command': '${__dirname}/runtime/node.exe',
                                  'args': ['${__dirname}/' + config['entry']]}}})
    data['RUNTIME.json'] = js({'node_version': 'v24.21.0', 'platform': 'win-x64',
        'archive_sha256': '158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541',
        'source': 'https://nodejs.org/dist/v24.21.0/node-v24.21.0-win-x64.zip',
        'members': NODE_HASHES})


def write_sums(target, paths):
    """Write sha256sum lines for paths to target with LF endings on every OS.

    Path.write_text turns each newline into CRLF on Windows. GNU sha256sum 8.32
    and Perl shasum then read the file name with a trailing carriage return and
    fail to open it, so the bytes are written directly.
    """
    lines = ''.join(f'{hashlib.sha256(Path(p).read_bytes()).hexdigest()}  {Path(p).name}\n' for p in paths)
    Path(target).write_bytes(lines.encode('utf-8'))


def build(root, out, *, mode='dev', tag=None, runtime=None):
    root, out = Path(root).resolve(), Path(out).resolve()
    if out == root or out.is_relative_to(root):
        raise ValueError('output must be outside source checkout')
    config = json.loads(read(root, 'client-plugin/config.json'))
    value = version(root, config)
    source = qualify(root, value, mode, tag)
    data = payload(root, config, value)
    if runtime:
        add_node(data, Path(runtime).absolute(), config, value)
    source['payload_sha256'] = {n: hashlib.sha256(v).hexdigest() for n, v in sorted(data.items())}
    data['SOURCE.json'] = js(source)
    label = '-dev' if mode == 'dev' else ''
    platform = '-win-x64' if runtime else '-source'
    name = f'{config["name"]}-{value}{label}{platform}'
    targets = [out / (name + ext) for ext in (('.zip', '.mcpb') if runtime else ('.zip',))]
    sums = out / (name + '.sha256')
    if any(p.exists() for p in [*targets, sums]):
        raise FileExistsError('refusing to overwrite client package')
    out.mkdir(parents=True, exist_ok=True)
    for target in targets:
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_STORED) as archive:
            for path, content in sorted(data.items()):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
    write_sums(sums, targets)
    return targets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=('dev', 'release'), default='release')
    parser.add_argument('--tag')
    parser.add_argument('--node-runtime', type=Path)
    args = parser.parse_args()
    for target in build(ROOT, args.out, mode=args.mode, tag=args.tag, runtime=args.node_runtime):
        print(target)
