"""Windows login-session supervisor; no unattended system desktop control."""
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import time

from autostart import launch, log, occupied
from relay_device import DEFAULT_CONFIG

HERE = Path(__file__).resolve().parent


def supervise(config=DEFAULT_CONFIG):
    cfg = json.loads(config.read_text(encoding='utf-8'))
    frpc = Path(cfg['frpc_executable'])
    if not frpc.is_file() or not (config.parent/'frpc.toml').is_file():
        raise ValueError('frpc installation/configuration missing')
    processes = []
    backoff = 2
    try:
        while True:
            current = json.loads(config.read_text(encoding='utf-8'))
            if current.get('revoked'):
                return
            if launch() != 0:
                log('Relay waits for authenticated local service.')
                time.sleep(15)
                continue
            started = time.monotonic()
            if occupied(int(current['local_port'])):
                raise RuntimeError('Device gateway port occupied; refusing duplicate startup')
            commands = [
                [str(HERE/'.venv/Scripts/pythonw.exe'), str(HERE/'relay_device.py'), '--config',str(config),'serve'],
                [str(frpc), '-c', str(config.parent/'frpc.toml')],
            ]
            # Child output may include network/configuration details; do not retain it.
            for command in commands:
                processes.append(subprocess.Popen(command,cwd=HERE,stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW))
            log('Relay supervisor started device gateway and tunnel processes.')
            while all(p.poll() is None for p in processes):
                time.sleep(3)
                if json.loads(config.read_text(encoding='utf-8')).get('revoked'):
                    return
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
            processes.clear()
            if time.monotonic()-started > 120:
                backoff = 2
            log('Relay child exited; retry scheduled.')
            time.sleep(backoff)
            backoff = min(backoff*2,60)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def main():
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    name = 'Local\\AgentRemoteRelay-'+hashlib.sha256(str(HERE).casefold().encode()).hexdigest()[:16]
    mutex = kernel.CreateMutexW(None,True,name)
    if not mutex:
        return 1
    already = ctypes.get_last_error() == 183
    try:
        if already:
            return 0
        supervise()
    except Exception as exc:
        log('Relay supervisor stopped: '+type(exc).__name__+'.')
        return 1
    finally:
        kernel.CloseHandle(mutex)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
