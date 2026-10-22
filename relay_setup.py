"""Prepare a verified per-user frpc installation, then show local account binding."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen
import zipfile

HERE = Path(__file__).resolve().parent
FRP_SHA256 = 'b90074b2b6a1d792a7a40f085ac6d276bcab2d1bc60201f8a86ca53ce65ce821'
ARCHIVE_NAME = 'frp_0.71.1_windows_amd64.zip'
DIRECTORY = 'frp_0.71.1_windows_amd64'
URL = 'https://github.com/fatedier/frp/releases/download/v0.71.1/'+ARCHIVE_NAME


def install_frpc(folder, certificate):
    folder = Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    archive = folder/ARCHIVE_NAME
    if not archive.exists():
        partial = folder/(ARCHIVE_NAME+'.part')
        print('正在下载 frp 官方发行包……',flush=True)
        try:
            with urlopen(URL,timeout=60) as source, partial.open('wb') as output:
                shutil.copyfileobj(source,output)
            if hashlib.sha256(partial.read_bytes()).hexdigest() != FRP_SHA256:
                raise ValueError('下载文件校验失败，未安装。')
            partial.replace(archive)
        finally:
            if partial.exists(): partial.unlink()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != FRP_SHA256:
        raise ValueError('本机 frp 压缩包校验失败，未执行。')
    cert = certificate.read_bytes()
    if b'BEGIN CERTIFICATE' not in cert or b'PRIVATE KEY' in cert:
        raise ValueError('仓库中的公开证书格式不正确。')
    target_cert = folder/'config'/'server.crt'
    if target_cert.exists() and target_cert.read_bytes() != cert:
        raise ValueError('本机已有其他服务器证书，未覆盖。请联系管理员。')
    with zipfile.ZipFile(archive) as zipped:
        for name in ('frpc.exe','LICENSE'):
            dest = folder/DIRECTORY/name
            data = zipped.read(DIRECTORY+'/'+name)
            if dest.exists() and dest.read_bytes() != data:
                raise ValueError('已安装文件与核对过的发行包不一致，未覆盖。')
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists(): dest.write_bytes(data)
    target_cert.parent.mkdir(parents=True,exist_ok=True)
    if not target_cert.exists(): target_cert.write_bytes(cert)
    return folder/DIRECTORY/'frpc.exe'


def main():
    if os.name != 'nt':
        raise SystemExit('绑定窗口目前支持 Windows。')
    try:
        executable = install_frpc(Path(os.environ['LOCALAPPDATA'])/'AgentRemote'/'frp',
                                  HERE/'deploy'/'relay'/'server-public.crt')
        subprocess.run([str(executable),'--version'],check=True,stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as exc:
        print(str(exc) if isinstance(exc,ValueError) else '隧道程序准备失败，请检查网络或安全软件的具体提示。')
        print('若安全软件拦截 frpc，请保留提示交给管理员；不要关闭防护。')
        return 1
    from relay_bind_gui import build_window
    build_window().mainloop()
    return 0


if __name__=='__main__': raise SystemExit(main())
