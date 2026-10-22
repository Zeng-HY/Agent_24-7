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
        if status==429:
            wait=result.get('retry_after',30) if isinstance(result,dict) else 30
            wait=wait if isinstance(wait,int) and 1<=wait<=86400 else 30
            raise ValueError(f'请求较多，请在 {wait} 秒后重试') from None
        messages={404:'服务器尚未启用新版接入，请联系管理员',401:'设备授权已失效，请重新绑定',
                  403:'设备授权已失效，请重新绑定',400:'绑定请求无效或已过期，请重新打开客户端'}
        raise ValueError(messages.get(status,f'服务器暂时无法连接（HTTP {status}）')) from None


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
    port=int(cfg['port'])
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
    try:
        for name in ('attachments','voice_terms.txt'):
            source=legacy/name
            if source.is_file():copy_user_file(source,DATA/name)
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
                        copy_user_file(item,dest)
        staged=DATA/'remote_config.migrating'
        staged.write_text(json.dumps(fresh,ensure_ascii=False),encoding='utf-8')
        staged.replace(DATA/'remote_config.json')
        marker.unlink()
        return fresh
    except BaseException:
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


def backend(cfg):
    if healthy(cfg):return None
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',int(cfg['port'])))==0:
            raise ValueError('端口已被其他程序占用，未启动重复服务')
    env=os.environ.copy();env['AR_DATA_DIR']=str(DATA)
    process=subprocess.Popen(command('--serve'),cwd=DATA,env=env,stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(50):
        if healthy(cfg):return process
        if process.poll() is not None:break
        time.sleep(.2)
    raise ValueError('本机服务启动失败')


def bind_window(binding):
    import webview
    from relay_vault import save
    request=api(binding['origin'],'/device-auth/start',{'label':socket.gethostname()},binding['key'])
    if not re.fullmatch('[0-9a-f]{32}',str(request.get('id',''))):raise ValueError('服务器返回的绑定请求无效')
    binding['pending']=request['id'];save(binding)
    webview.settings['ALLOW_FILE_URLS']=False
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
    window=webview.create_window('Agent Remote',binding['origin']+'/account?authorize='+request['id'],width=500,height=700,min_size=(380,540),
        background_color='#f6f6f6',js_api=None)
    approved=threading.Event();closed=threading.Event()
    window.events.closed+=lambda:closed.set()
    window.events.before_show+=lambda:harden_window(window,binding['origin'])
    def poll():
        while not closed.wait(2):
            try:result=api(binding['origin'],'/device-auth/poll',{'id':binding['pending']},binding['key'])
            except Exception:continue
            if result.get('approved'):
                if not re.fullmatch('[0-9a-f]{32}',str(result.get('device',''))):continue
                binding['device']=result['device'];save(binding);approved.set();window.destroy();return
    threading.Thread(target=poll,daemon=True).start()
    webview.start(gui='edgechromium',private_mode=True,debug=False)
    return approved.is_set()


def harden_window(window,origin):
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
        if uri!='about:blank' and urlsplit(uri).scheme+'://'+urlsplit(uri).netloc!=origin:
            args.Cancel=True
    native.NavigationStarting+=navigating


def run_agent(binding,cfg):
    from relay_agent import Agent
    def state(value):
        global connection_state
        connection_state=value
    async def run():
        owned=None
        try:
            while not stop.is_set():
                try:
                    created=backend(cfg)
                    if created is not None:owned=created
                    agent=Agent(binding['origin'],binding['key'],cfg['port'],cfg['token'],state=state)
                    task=asyncio.create_task(agent.run())
                    while not stop.is_set() and not task.done():await asyncio.sleep(.5)
                    task.cancel();await asyncio.gather(task,return_exceptions=True)
                except Exception:state('offline');await asyncio.sleep(2)
        finally:
            if owned is not None and owned.poll() is None:
                owned.terminate();owned.wait(timeout=5)
    asyncio.run(run())


def tray(binding,cfg):
    import pystray
    from PIL import Image,ImageDraw
    import webbrowser
    image=Image.new('RGBA',(64,64),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((6,8,58,48),radius=8,fill='#171717');draw.line((23,56,41,56),fill='#171717',width=5)
    def quit_app(icon,item):stop.set();icon.stop()
    def rebind(icon,item):
        global rebind_requested
        rebind_requested=True;quit_app(icon,item)
    icon=pystray.Icon('AgentRemote',image,'Agent Remote',menu=pystray.Menu(
        pystray.MenuItem(lambda item:'状态：'+{'online':'已连接','offline':'未连接','reconnecting':'重连中'}.get(connection_state,'未连接'),None,enabled=False),
        pystray.MenuItem('账号与电脑',lambda:webbrowser.open(binding['origin']+'/account')),
        pystray.MenuItem('重新绑定',rebind),
        pystray.MenuItem('禁用登录自启',lambda:startup(False)),
        pystray.MenuItem('启用登录自启',lambda:startup(True)),
        pystray.MenuItem('退出',quit_app)))
    worker=threading.Thread(target=run_agent,args=(binding,cfg),daemon=True)
    worker.start()
    try:icon.run()
    finally:stop.set();worker.join(timeout=10)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--serve',action='store_true');parser.add_argument('--tray',action='store_true')
    parser.add_argument('--dismiss-worker',action='store_true');parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--webview-smoke',action='store_true')
    parser.add_argument('--rebind',action='store_true')
    args=parser.parse_args()
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
            assert remote.VERSION=='0.27.0-dev' and remote.chats is not None
            assert (ASSETS/'remote.html').is_file()
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
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateMutexW(None,True,'Local\\AgentRemote027-'+str(os.getlogin()))
    if not handle:return 1
    if ctypes.get_last_error()==183:kernel.CloseHandle(handle);return 0
    try:
        from relay_vault import load,save
        cfg=initialize()
        binding=load()
        if not binding or args.rebind:
            binding={'origin':ORIGIN,'key':secrets.token_urlsafe(32)};save(binding)
        if not binding.get('device') and not bind_window(binding):return 0
        cfg=complete_migration(cfg)
        startup(True)
        tray(binding,cfg)
    except Exception as exc:
        message=str(exc) if isinstance(exc,ValueError) else '连接或安装未完成，请检查服务和运行环境。'
        ctypes.windll.user32.MessageBoxW(None,message,'Agent Remote',0x10)
        return 1
    finally:
        kernel.CloseHandle(handle)
        if rebind_requested:
            subprocess.Popen(command('--rebind'),cwd=DATA,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    return 0


if __name__=='__main__':raise SystemExit(main())
