"""Verify native Forum preflight and deny execution under a bounded Windows Job."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from native_windows_process import run_process

ALLOWED = {'forum.route','forum.context.preflight','forum.runtime.inspect',
           'forum.prose.contract','forum.status','forum.doctor'}


def check(exe, version):
    calls = [('forum.route', {'text':'Review a Python module for correctness'}),
             ('forum.context.preflight', {'request':'Review a Python module'}),
             ('forum.runtime.inspect', {}), ('forum.prose.contract', {'text':'Review a Python module'})]
    denied = ['submit','forum.submit','gate_approve','forum.gate.approve','forum.gate.edit','forum.gate.reject']
    requests = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
                {'jsonrpc':'2.0','id':2,'method':'tools/list'}]
    for i, (name, args) in enumerate(calls + [(name,{}) for name in denied], 3):
        requests.append({'jsonrpc':'2.0','id':i,'method':'tools/call',
                         'params':{'name':name,'arguments':args}})
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        env = {k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT'}}
        env.update(PATH=os.path.join(os.environ.get('SYSTEMROOT','C:/Windows'),'System32'),
                   HOME=str(root),USERPROFILE=str(root),TEMP=str(root),TMP=str(root))
        code, out, err = run_process(str(exe), [], env, str(root), ''.join(json.dumps(x)+'\n' for x in requests))
        if code or err:
            raise ValueError('native Forum failed or wrote unexpected diagnostics')
        messages = {m['id']:m for m in map(json.loads,out.splitlines())}
        if messages[1]['result']['serverInfo']['version'] != version:
            raise ValueError('native version mismatch')
        if {t['name'] for t in messages[2]['result']['tools']} != ALLOWED:
            raise ValueError('native capability set differs from preflight allowlist')
        for mid in range(3,7):
            if messages[mid].get('error') or messages[mid]['result'].get('isError'):
                raise ValueError('native preflight failed')
        runtime = json.loads(messages[5]['result']['content'][0]['text'])
        if runtime['ready'] is not False or runtime['default']['kind'] != 'missing':
            raise ValueError('preflight falsely reports an executor')
        for mid in range(7,13):
            if messages[mid]['result'].get('isError') is not True:
                raise ValueError('native execution or grant boundary accepted a forbidden tool')
        code, _, _ = run_process(str(exe), ['--allow-gate-decisions'], env, str(root), '')
        if code == 0:
            raise ValueError('unexpected launch argument accepted')
    return {'status':'PASS','version':version,'executable_sha256':hashlib.sha256(Path(exe).read_bytes()).hexdigest(),
            'tools':sorted(ALLOWED),'checks':['native preflight','execution and gate tools refused','unexpected argv refused'],
            'does_not_prove':['installed client compatibility','marketplace approval','semantic routing quality']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable',type=Path)
    parser.add_argument('--version',required=True)
    args=parser.parse_args()
    print(json.dumps(check(args.executable,args.version),indent=2))
