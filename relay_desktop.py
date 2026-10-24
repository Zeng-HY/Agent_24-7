"""Frozen Windows entry: user-session backend, outbound agent, WebView2 and tray."""
import argparse
from contextlib import closing
import asyncio
import ctypes
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import sqlite3
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, quote
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError
if __name__=='__main__' and 'AR_DATA_DIR' not in os.environ:
    os.environ['AR_DATA_DIR']=str(Path(os.environ['LOCALAPPDATA'])/'AgentRemote'/'Data')
from app_paths import ASSETS, DATA, command

ORIGIN='https://8.166.15.235'
stop=threading.Event()
connection_state='offline'
rebind_requested=False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


class ApiError(ValueError):
    def __init__(self, message, code='network_error', retry_after=2):
        super().__init__(message);self.code=code;self.retry_after=retry_after


def api(origin,path,data,key):
    request=Request(origin+path,data=json.dumps(data).encode(),headers={
        'Content-Type':'application/json','Origin':origin,'Authorization':'Bearer '+key})
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        status=exc.code
        try:result=json.loads(exc.read(8192))
        except (ValueError,OSError):result={}
        finally:exc.close()
        if not isinstance(result,dict):result={}
        retry=result.get('retry_after',30)
        retry=retry if isinstance(retry,int) and 1<=retry<=86400 else 30
        code=result.get('code')
        if status==429:raise ApiError(f'请求较多，请在 {retry} 秒后重试','rate_limited',retry) from None
        if status in (401,403):raise ApiError('设备授权已失效，请重新绑定','invalid_device_credential') from None
        if status==400 and code is None and '绑定请求' in result.get('error',''):code='binding_expired'
        raise ApiError(result.get('error','服务器暂时无法连接'),code or 'server_error') from None
    except (OSError,ValueError) as exc:
        if isinstance(exc,ApiError):raise
        raise ApiError('连不上服务器，正在重试','network_error') from None


def startup(enabled, *, shell=None):
    import win32com.client
    shell=shell or win32com.client.Dispatch('WScript.Shell')
    folder=Path(shell.SpecialFolders('Startup'))
    target=folder/'Agent Remote 027.lnk'
    if enabled:
        shortcut=shell.CreateShortcut(str(target))
        args=command('--tray')
        shortcut.TargetPath=args[0]
        shortcut.Arguments=subprocess.list2cmdline(args[1:])
        shortcut.WorkingDirectory=str(DATA)
        shortcut.WindowStyle=7
        shortcut.Save()
        # Only retire our known, same-user legacy launchers, never arbitrary links.
        for name in ('Agent Remote.lnk','Agent Remote Relay.lnk'):
            old=folder/name
            if old.exists():
                prior=shell.CreateShortcut(str(old))
                if any(x in prior.Arguments for x in ('autostart.py','relay_supervisor.py')):
                    backup=DATA/'migration-backup'/name;backup.parent.mkdir(parents=True,exist_ok=True)
                    if not backup.exists():shutil.copy2(old,backup)
                    old.unlink()
    elif target.exists(): target.unlink()


def preferences():
    try:return json.loads((DATA/'desktop-preferences.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def save_preferences(value):
    DATA.mkdir(parents=True,exist_ok=True)
    temp=DATA/'desktop-preferences.json.tmp';temp.write_text(json.dumps(value),encoding='utf-8');temp.replace(DATA/'desktop-preferences.json')


def set_startup(enabled):
    startup(enabled)
    value=preferences();value['startup']=enabled;save_preferences(value)


def select_legacy(path):
    source=Path(path).resolve()
    if source==DATA.resolve() or source.is_relative_to(DATA.resolve()) or DATA.resolve().is_relative_to(source) or not (source/'remote.py').is_file():raise ValueError('请选择旧版 agent_remote 文件夹')
    cfg=json.loads((source/'remote_config.json').read_text(encoding='utf-8-sig'))
    if not isinstance(cfg,dict) or not isinstance(cfg.get('token'),str) or not cfg['token']:raise ValueError('旧配置无效')
    port=cfg.get('port',8765)
    if type(port) is not int or not 1<=port<=65535:raise ValueError('旧配置端口无效')
    backup=DATA/'migration-backup';backup.mkdir(parents=True,exist_ok=True)
    for name in ('remote_config.json','voice_terms.txt'):
        if (DATA/name).is_file():shutil.copy2(DATA/name,backup/('before-manual-'+name))
    (DATA/'pending-migration.json').write_text(json.dumps({'source':str(source)}),encoding='utf-8')
    return cfg


def detect_legacy():
    import win32com.client
    shell=win32com.client.Dispatch('WScript.Shell')
    folder=Path(shell.SpecialFolders('Startup'))
    for name in ('Agent Remote.lnk','Agent Remote Relay.lnk'):
        link=folder/name
        if link.exists():
            shortcut=shell.CreateShortcut(str(link))
            value=shortcut.Arguments.strip().strip('"')
            candidate=Path(value).parent
            if (candidate/'remote_config.json').is_file():return candidate
    return None


def initialize():
    from relay_device import private_directory
    private_directory(DATA)
    config=DATA/'remote_config.json'
    if not config.exists():
        legacy=detect_legacy()
        if legacy and legacy.resolve()!=DATA.resolve():
            staged_config=DATA/'remote_config.migrating'
            shutil.copy2(legacy/'remote_config.json',staged_config)
            json.loads(staged_config.read_text(encoding='utf-8-sig'))
            (DATA/'pending-migration.json').write_text(json.dumps({'source':str(legacy.resolve())}),encoding='utf-8')
            (DATA/'migration-backup').mkdir(exist_ok=True)
            shutil.copy2(staged_config,DATA/'migration-backup'/'remote_config.json')
            staged_config.replace(config)
        else:
            cfg={'bind':'127.0.0.1','port':8765,'token':secrets.token_urlsafe(32),
                 'name':socket.gethostname(),'voice':False,'roots':[str(Path.home()/'Downloads')]}
            config.write_text(json.dumps(cfg),encoding='utf-8')
    return json.loads(config.read_text(encoding='utf-8-sig'))


def copy_user_file(source,destination):
    staged=destination.with_name(destination.name+'.migrating')
    with source.open('rb') as input_file:sqlite_header=input_file.read(16)==b'SQLite format 3\x00'
    if sqlite_header:
        uri='file:'+quote(source.resolve().as_posix(),safe='/:')+'?mode=ro'
        with closing(sqlite3.connect(uri,uri=True)) as original,closing(sqlite3.connect(staged)) as copy:
            original.backup(copy)
    else:shutil.copy2(source,staged)
    staged.replace(destination)


def stop_legacy_backend(legacy,cfg):
    import autostart
    import setup_machine
    import win32com.client
    port=int(cfg.get('port',8765))
    if not autostart.occupied(port):return False
    if not healthy(cfg):raise ValueError('旧服务身份未确认，未停止或覆盖现有安装')
    pid=setup_machine.listener(port)
    records=list(win32com.client.GetObject('winmgmts:').ExecQuery(f'SELECT CommandLine FROM Win32_Process WHERE ProcessId={pid}'))
    expected=str((legacy/'remote.py').resolve()).replace('/','\\').lower()
    if not records or expected not in str(records[0].CommandLine).replace('/','\\').lower():
        raise ValueError('监听进程不属于选定的旧安装，未停止')
    subprocess.run(['taskkill','/F','/PID',str(pid)],check=True,stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(25):
        if not autostart.occupied(port):return True
        time.sleep(.2)
    raise ValueError('旧服务尚未退出，未开始迁移')


def complete_migration(cfg):
    marker=DATA/'pending-migration.json'
    if not marker.exists():return cfg
    legacy=Path(json.loads(marker.read_text(encoding='utf-8'))['source']).resolve()
    if legacy==DATA.resolve():raise ValueError('迁移路径无效')
    fresh=json.loads((legacy/'remote_config.json').read_text(encoding='utf-8-sig'))
    stopped=stop_legacy_backend(legacy,fresh)
    rollback=DATA/'migration-backup'/('files-'+secrets.token_hex(6))
    touched=[]
    def preserve(dest):
        relative=dest.resolve().relative_to(DATA.resolve())
        backup=rollback/relative
        existed=dest.exists()
        if existed:
            backup.parent.mkdir(parents=True,exist_ok=True)
            copy_user_file(dest,backup)
        touched.append((dest,backup,existed))
    try:
        for name in ('attachments','voice_terms.txt'):
            source=legacy/name
            if source.is_file():
                preserve(DATA/name);copy_user_file(source,DATA/name)
            elif source.is_dir():
                for parent,dirs,files in os.walk(source,followlinks=False):
                    dirs[:]=[d for d in dirs if not (Path(parent)/d).is_symlink() and not (os.stat(Path(parent)/d,follow_symlinks=False).st_file_attributes & 0x400)]
                    for filename in files:
                        item=Path(parent)/filename
                        if item.is_symlink():continue
                        if filename.endswith(('-wal','-shm','-journal')):
                            main=item.with_name(filename.rsplit('-',1)[0])
                            if main.is_file():
                                with main.open('rb') as f:
                                    if f.read(16)==b'SQLite format 3\x00':continue
                        dest=DATA/name/item.relative_to(source)
                        dest.parent.mkdir(parents=True,exist_ok=True)
                        preserve(dest);copy_user_file(item,dest)
        preserve(DATA/'remote_config.json')
        staged=DATA/'remote_config.migrating'
        staged.write_text(json.dumps(fresh,ensure_ascii=False),encoding='utf-8')
        staged.replace(DATA/'remote_config.json')
        (DATA/'migration-result.json').write_text(json.dumps({'source':str(legacy),'completed':True}),encoding='utf-8')
        marker.unlink()
        return fresh
    except BaseException:
        for dest,backup,existed in reversed(touched):
            if existed:shutil.copy2(backup,dest)
            else:dest.unlink(missing_ok=True)
        if stopped:
            subprocess.Popen([str(legacy/'.venv/Scripts/pythonw.exe'),str(legacy/'autostart.py')],cwd=legacy,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        raise


def healthy(cfg):
    try:
        request=Request('http://127.0.0.1:'+str(cfg['port'])+'/api/status',headers={'Cookie':'lbr='+cfg['token']})
        with build_opener(ProxyHandler({})).open(request,timeout=3) as response:
            return json.load(response).get('ok') is True and response.headers.get('Server','').startswith('AgentRemote/')
    except Exception:return False


def backend(cfg,cancel=None):
    if healthy(cfg):return None
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',int(cfg['port'])))==0:
            raise ValueError('端口已被其他程序占用，未启动重复服务')
    env=os.environ.copy();env['AR_DATA_DIR']=str(DATA)
    process=subprocess.Popen(command('--serve'),cwd=DATA,env=env,stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(50):
        if cancel is not None and cancel.is_set():break
        if healthy(cfg):return process
        if process.poll() is not None:break
        time.sleep(.2)
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
    raise ValueError('本机服务启动失败')


def harden_window(window,origin,local_uri=None):
    native=window.native.webview
    def configure(sender=None,args=None):
        if native.CoreWebView2 is not None:
            native.CoreWebView2.Settings.IsWebMessageEnabled=False
            native.CoreWebView2.Settings.AreHostObjectsAllowed=False
            native.CoreWebView2.Settings.AreDevToolsEnabled=False
            native.CoreWebView2.Settings.IsPasswordAutosaveEnabled=False
    native.CoreWebView2InitializationCompleted+=configure
    configure()
    def navigating(sender,args):
        uri=str(args.Uri)
        if uri not in ('about:blank',local_uri) and urlsplit(uri).scheme+'://'+urlsplit(uri).netloc!=origin:
            args.Cancel=True
    native.NavigationStarting+=navigating


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--serve',action='store_true');parser.add_argument('--tray',action='store_true')
    parser.add_argument('--dismiss-worker',action='store_true');parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--webview-smoke',action='store_true')
    parser.add_argument('--rebind',action='store_true')
    parser.add_argument('--status-smoke',action='store_true')
    args=parser.parse_args()
    if args.status_smoke:
        from relay_controller import smoke
        return smoke()
    if args.webview_smoke:
        import webview
        window=webview.create_window('Agent Remote smoke',html='<html><body>test</body></html>',hidden=True,js_api=None)
        result=[]
        def configure():
            harden_window(window,'https://example.test')
            def check(sender,args):
                settings=window.native.webview.CoreWebView2.Settings
                result.append(not settings.IsWebMessageEnabled and not settings.AreHostObjectsAllowed)
                threading.Timer(.5,window.destroy).start()
            window.native.webview.CoreWebView2InitializationCompleted+=check
        window.events.before_show+=configure
        threading.Timer(15,window.destroy).start()
        webview.start(gui='edgechromium',private_mode=True,debug=False)
        return 0 if result==[True] else 1
    if args.self_test:
        try:
            import aiohttp,webview,win32crypt,win32security,comtypes,remote
            assert remote.chats is not None
            assert (ASSETS/'remote.html').is_file()
            from message_files import references
            assert references('[file](<D:/candidate/file (1).md>)')==['D:/candidate/file (1).md']
            for asset in ('markdown-it.min.js','purify.min.js','markdown-ui.js','message-projection.js','scroll-anchor.js'):
                assert (ASSETS/'static'/asset).is_file()
            import relay_controller,relay_updates,relay_instance
            assert (ASSETS/'desktop_status.html').is_file()
            assert relay_updates.metadata()['build']>=1
            return 0
        except Exception:return 1
    if args.serve:
        import remote
        return remote.main([])
    if args.dismiss_worker:
        import codex_question_dismiss
        sys.argv=[sys.argv[0],'--worker']
        codex_question_dismiss.worker()
        return 0
    from relay_instance import Instance
    instance=Instance()
    if not instance.primary:
        if instance.legacy:ctypes.windll.user32.MessageBoxW(None,'旧版 Agent Remote 仍在运行。请从旧版托盘退出后再打开新版。','Agent Remote',0x40)
        instance.close();return 0
    try:
        from relay_controller import DesktopController
        DesktopController(instance,start_hidden=args.tray,rebind=args.rebind).run()
    except Exception as exc:
        message=str(exc) if isinstance(exc,ValueError) else '启动未完成，请检查运行环境。'
        ctypes.windll.user32.MessageBoxW(None,message,'Agent Remote',0x10)
        return 1
    finally:instance.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
