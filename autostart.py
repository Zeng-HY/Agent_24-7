"""Current-user login launcher. Reuse an existing service; never kill or duplicate it."""
from __future__ import annotations
import ctypes,hashlib,json,os,socket,subprocess,time
from datetime import datetime
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler

HERE=Path(__file__).resolve().parent
def log(message):
    folder=HERE/'logs';folder.mkdir(exist_ok=True)
    path=folder/'startup.log'
    # This log contains state and errors only, never configuration values or access URLs.
    if path.exists() and path.stat().st_size>1<<20:path.write_text('',encoding='utf-8')
    with path.open('a',encoding='utf-8') as f:f.write(datetime.now().isoformat(timespec='seconds')+' '+message+'\n')

def healthy(port,token):
    try:
        request=Request(f'http://127.0.0.1:{port}/api/status',headers={'Cookie':'lbr='+token})
        with build_opener(ProxyHandler({})).open(request,timeout=3) as response:
            data=json.load(response)
            return response.headers.get('Server','').startswith('AgentRemote/') and isinstance(data,dict) and 'chat' in data
    except Exception:return False

def occupied(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):return True
    except OSError:return False

def launch():
    config=json.loads((HERE/'remote_config.json').read_text(encoding='utf-8-sig'))
    port=int(config.get('port',8765));token=config.get('token','')
    if not token:raise RuntimeError('remote_config.json has no access token; use the console launcher for first setup')
    if healthy(port,token):log('Existing authenticated service reused.');return 0
    if occupied(port):log('Port occupied but service health not confirmed; no duplicate started.');return 2
    python=HERE/'.venv/Scripts/pythonw.exe'  # this folder's own environment (requirements.txt), since 10-12
    if not python.is_file():raise RuntimeError('Python environment .venv not found; set it up from requirements.txt')
    environment=os.environ.copy();environment['PYTHONUTF8']='1'
    with (HERE/'logs/startup-errors.log').open('ab') as errors:
        process=subprocess.Popen([str(python),str(HERE/'remote.py')],cwd=str(HERE),env=environment,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
    for _ in range(40):
        if healthy(port,token):log('Background service started and authenticated health check passed.');return 0
        if process.poll() is not None:log('Service launcher exited before readiness; see startup-errors.log.');return 3
        time.sleep(.5)
    log('Readiness not confirmed; no second process started. See startup-errors.log.');return 4

def main():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.ReleaseMutex.argtypes=[ctypes.c_void_p]
    name='Local\\AgentRemoteLauncher-'+hashlib.sha256(str(HERE).casefold().encode()).hexdigest()[:16]
    mutex=kernel.CreateMutexW(None,True,name)
    if not mutex:return 5
    already=ctypes.get_last_error()==183
    try:
        if already:return 0
        try:
            (HERE/'logs').mkdir(exist_ok=True)
            return launch()
        except Exception as exc:
            log('Startup failed: '+type(exc).__name__+'. Check configuration, paths and permissions.');return 1
    finally:
        if not already:kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)

if __name__=='__main__':raise SystemExit(main())
