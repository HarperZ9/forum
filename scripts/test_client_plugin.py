"""Package controls and real source MCP startup; no model or provider calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('client_builder', ROOT / 'scripts/build_client_plugin.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class ClientPackage(unittest.TestCase):
    def test_reproducible_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = builder.build(ROOT, Path(tmp) / 'a')[0]
            b = builder.build(ROOT, Path(tmp) / 'b')[0]
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with self.assertRaises(FileExistsError):
                builder.build(ROOT, Path(tmp) / 'a')
            with zipfile.ZipFile(a) as z:
                receipt = json.loads(z.read('SOURCE.json'))
                self.assertEqual(receipt['mode'], 'dev')
                for name, digest in receipt['payload_sha256'].items():
                    self.assertEqual(builder.hashlib.sha256(z.read(name)).hexdigest(), digest)
                self.assertIn('skills/', '\n'.join(z.namelist()))
                self.assertNotIn('C:/dev', z.read('mcp.json').decode())
                self.assertNotIn('.env', z.namelist())

    def test_refuses_unqualified_release(self):
        config = json.loads((ROOT / 'client-plugin/config.json').read_text())
        with self.assertRaises(ValueError):
            builder.qualify(ROOT, builder.version(ROOT, config), 'release', 'v0.0.0')
        with self.assertRaises(ValueError):
            builder.build(ROOT, ROOT / 'dist')

    def test_runtime_hash_and_source_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'node.exe').write_bytes(b'not a runtime')
            with self.assertRaises(ValueError):
                builder.add_node({}, root, {'runtime': 'node'}, '1.0.0')
            with self.assertRaises(ValueError):
                builder.read(root, '../outside')

    def test_release_rejects_dirty_source_and_wrong_tag_commit(self):
        def dirty(root, *args):
            return 'changed' if args[0]=='status' else 'head'
        with patch.object(builder, 'git', side_effect=dirty):
            with self.assertRaisesRegex(ValueError, 'clean source'):
                builder.qualify(ROOT, '2.1.0', 'release', 'v2.1.0')
        def wrong(root, *args):
            if args[0]=='status': return ''
            return 'head' if args[1]=='HEAD' else 'other'
        with patch.object(builder, 'git', side_effect=wrong):
            with self.assertRaisesRegex(ValueError, 'name HEAD'):
                builder.qualify(ROOT, '2.1.0', 'release', 'v2.1.0')

    def test_linked_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'real').mkdir()
            (root/'real/data').write_text('synthetic')
            try:
                (root/'linked').symlink_to(root/'real', target_is_directory=True)
            except OSError:
                self.skipTest('host does not permit symlinks')
            with self.assertRaisesRegex(ValueError, 'reparse'):
                builder.read(root, 'linked/data')

    def test_real_packaged_stdio(self):
        config = json.loads((ROOT / 'client-plugin/config.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = builder.build(ROOT, root / 'archives')[0]
            with zipfile.ZipFile(archive) as z:
                z.extractall(root / 'payload')
            exe = os.environ.get('CLIENT_TEST_PYTHON', os.sys.executable) if config['runtime']=='python3' else shutil.which('node')
            self.assertTrue(exe, 'installed runtime required for source qualification')
            command = [exe]
            if config['runtime']=='python3': command += ['-I', '-S', '-B']
            command += [str(root / 'payload' / config['entry'])]
            env = {k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','COMSPEC','PATHEXT'}}
            env.update(HOME=str(root/'home'),USERPROFILE=str(root/'home'),LEARN_HOME=str(root/'state'),FORUM_LEDGER=str(root/'ledger'))
            requests = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'package-test','version':'1'}}},
                        {'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}]
            safe = {'forum': {'name':'forum.route','arguments':{'text':'Review a Python module for correctness'}},
                    'telos': {'name':'telos.catalog','arguments':{}},
                    'learn': {'name':'learn_dry_run','arguments':{'workflow':{'steps':[{'kind':'assess'}]}}}}[config['tool']]
            requests.append({'jsonrpc':'2.0','id':3,'method':'tools/call','params':safe})
            requests += [{'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'forum.submit','arguments':{'request':'Do not execute'}}},
                         {'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'forum.gate.approve','arguments':{}}},
                         {'jsonrpc':'2.0','id':6,'method':'tools/call','params':{'name':'forum.runtime.inspect','arguments':{}}}]
            result = subprocess.run(command, input=''.join(json.dumps(x)+'\n' for x in requests), text=True,capture_output=True,env=env,cwd=root,timeout=25)
            self.assertEqual(result.returncode,0,result.stderr)
            messages = {r['id']:r for r in map(json.loads,result.stdout.splitlines()) if 'id' in r}
            self.assertEqual(messages[1]['result']['serverInfo']['version'], builder.version(ROOT,config))
            self.assertFalse(messages[3].get('error'), messages[3])
            self.assertFalse(messages[3]['result'].get('isError'), messages[3])
            if config['tool']=='learn':
                self.assertIn('halted', json.dumps(messages[3]).lower())
            self.assertTrue(messages[4]['result']['isError'])
            self.assertTrue(messages[5]['result']['isError'])
            self.assertFalse(messages[6]['result'].get('isError'))
            runtime = json.loads(messages[6]['result']['content'][0]['text'])
            self.assertIs(runtime['ready'], False)
            self.assertEqual(runtime['default']['kind'], 'missing')
            names={x['name'] for x in messages[2]['result']['tools']}
            self.assertEqual(len(names), 6)
            self.assertNotIn('forum.submit', names)
            self.assertNotIn('forum.gate.approve', names)
            self.assertIn({'forum':'forum.route','learn':'learn_status','telos':'telos.status'}[config['tool']], names)

if __name__=='__main__': unittest.main()
