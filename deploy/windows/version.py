"""Generate build identity and the exact Release asset manifest, never credentials."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
version=json.loads((root/'windows-version.json').read_text(encoding='utf-8'))
notes=json.loads((root/'windows-release-notes.json').read_text(encoding='utf-8')).get(version['version'],{})
summary=notes.get('summary')
assert isinstance(summary,list) and 1<=len(summary)<=3 and all(isinstance(s,str) and 0<len(s)<=160 for s in summary),'Write 1-3 plain-language release highlights before building.'
assert isinstance(notes.get('details'),str) and notes['details'].strip(),'Full release notes are required.'
assert re.fullmatch(r'\d+\.\d+\.\d+(?:-dev\.\d+)?',version['version'])
assert type(version['build']) is int and 0<version['build']<65536
if '--manifest' in sys.argv:
    info=json.loads((root/'build/windows-build.json').read_text(encoding='utf-8'))
    file=root/'dist'/('AgentRemote-'+info['version']+'-Setup.exe')
    info.update(schema=1,name=file.name,size=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest(),summary=summary,notes=notes['details'])
    (root/'dist/windows-update.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
else:
    version['commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    build=root/'build';build.mkdir(exist_ok=True)
    (build/'windows-build.json').write_text(json.dumps(version),encoding='utf-8')
    numeric=version['version'].split('-')[0]+'.'+str(version['build'])
    (build/'windows-version.iss').write_text('#define AppVersion "'+version['version']+'"\n#define AppNumericVersion "'+numeric+'"\n',encoding='utf-8')
    (build/'windows-release-notes.md').write_text('## 本版重点\n\n'+'\n'.join('- '+s for s in summary)+'\n\n<details>\n<summary>更新详情</summary>\n\n'+notes['details']+'\n\n</details>\n',encoding='utf-8')

if '--manifest' not in sys.argv:
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/target:library','/optimize+','/reference:System.Drawing.dll','/reference:System.Windows.Forms.dll',
        '/out:'+str(root/'build/AgentRemote.Chrome.dll'),str(root/'deploy/windows/ChromeRenderer.cs')],check=True)
