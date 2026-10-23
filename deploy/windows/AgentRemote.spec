# PyInstaller directory build; never include configuration, logs or attachments.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
root=Path(SPECPATH).parents[1]
datas=[(str(root/'remote.html'),'.'),(str(root/'voice_tidy_prompt.txt'),'.'),
       (str(root/'static'),'static'),(str(root/'desktop_status.html'),'.'),
       (str(root/'windows-version.json'),'.'),(str(root/'windows-release-notes.json'),'.'),(str(root/'build/windows-build.json'),'.'),(str(root/'build/AgentRemote.Chrome.dll'),'.')]
datas+=collect_data_files('webview')
hidden=collect_submodules('comtypes',filter=lambda name:'.test' not in name)+collect_submodules('win32com',filter=lambda name:'.test' not in name)
a=Analysis([str(root/'relay_desktop.py')],pathex=[str(root)],binaries=collect_dynamic_libs('uiautomation'),datas=datas,
    hiddenimports=hidden,excludes=['pytest','playwright','IPython','matplotlib','numpy','pandas'],
    noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='AgentRemote',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'static/app.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='AgentRemote')
