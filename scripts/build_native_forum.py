"""Freeze and qualify the preflight-only Windows client using the current Python."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from build_client_plugin import ROOT, git, js, payload, qualify, read, version, write_sums
from check_native_forum import check


def build(out, mode, tag):
    out=Path(out).absolute()
    if os.name!='nt' or out.exists() or out.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('requires Windows and a new output directory outside source')
    config=json.loads(read(ROOT,'client-plugin/config.json'))
    value=version(ROOT,config)
    source=qualify(ROOT,value,mode,tag)
    inputs=payload(ROOT,config,value)
    out.mkdir(parents=True)
    env=dict(os.environ, PYTHONPATH=str(ROOT/'src'), PYTHONHASHSEED='0',
             SOURCE_DATE_EPOCH=git(ROOT,'show','-s','--format=%ct','HEAD'))
    command=[sys.executable,'-m','PyInstaller','--onefile','--noconfirm','--name','forum-preflight',
             '--paths',str(ROOT/'src'),
             '--add-data',str(ROOT/'src/forum/manifests')+';forum/manifests',
             '--add-data',str(ROOT/'src/forum/skills')+';forum/skills',
             '--distpath',str(out/'dist'),'--workpath',str(out/'work'),
             '--specpath',str(out/'spec'),str(ROOT/'client-plugin/serve.py')]
    with (out/'freeze.log').open('w',encoding='utf8') as log:
        subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
    if inputs != payload(ROOT,config,value):
        raise ValueError('source changed during freeze')
    exe=out/'dist/forum-preflight.exe'
    native=check(exe,value)
    data=inputs.copy()
    data['server/forum-preflight.exe']=exe.read_bytes()
    data['PYTHON-LICENSE.txt']=(Path(sys.base_prefix)/'LICENSE.txt').read_bytes()
    dist=importlib.metadata.distribution('pyinstaller')
    license_file=next(f for f in dist.files if str(f).endswith('/licenses/COPYING.txt'))
    data['PYINSTALLER-LICENSE.txt']=Path(dist.locate_file(license_file)).read_bytes()
    data['mcp.json']=js({'mcpServers':{'forum':{'type':'stdio','command':'${PLUGIN_ROOT}/server/forum-preflight.exe','args':[]}}})
    data['.mcp.json']=data['mcp.json'].replace(b'${PLUGIN_ROOT}',b'${CLAUDE_PLUGIN_ROOT}')
    data['manifest.json']=js({'manifest_version':'0.3','name':config['name'],'version':value,
        'description':config['description'],'author':{'name':'Zain Dana Harper'},
        'compatibility':{'platforms':['win32']},'server':{'type':'binary','entry_point':'server/forum-preflight.exe',
        'mcp_config':{'command':'${__dirname}/server/forum-preflight.exe','args':[]}}})
    data['NATIVE-QUALIFICATION.json']=js(native)
    source.update(python=sys.version.split()[0],pyinstaller=dist.version,
                  payload_sha256={k:hashlib.sha256(v).hexdigest() for k,v in sorted(data.items())})
    data['SOURCE.json']=js(source)
    label='-dev' if mode=='dev' else ''
    prefix=f'forum-routing-{value}{label}-win-x64'
    targets=[out/(prefix+suffix) for suffix in ['.zip','.mcpb']]
    for target in targets:
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_STORED) as archive:
            for name,content in sorted(data.items()):
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o100644<<16
                archive.writestr(info,content)
    write_sums(out/(prefix+'.sha256'),targets)
    return targets


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mode',choices=['dev','release'],default='release')
    parser.add_argument('--tag')
    args=parser.parse_args()
    for file in build(args.out,args.mode,args.tag): print(file)
