"""User-session UI/controller. Only the bundled local page can request fixed actions."""
import asyncio
import base64
import json
import os
from pathlib import Path
import random
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import urlsplit

import relay_desktop as desktop
import relay_updates as updates
from relay_vault import load,save
from app_paths import DATA,ASSETS

ACTIONS={'bind','retry','account','check-update','startup','download','install','cancel-download','back','rebind','quit'}


def local_action(uri):
    p=urlsplit(uri)
    if p.scheme=='agentremote-action' and p.netloc in ACTIONS and not p.path and not p.query and not p.fragment:return p.netloc
    return None


class DesktopController:
    def __init__(self,instance,start_hidden=False,rebind=False):
        self.instance=instance;self.hidden=start_hidden;self.stop=threading.Event();self.auth_stop=threading.Event()
        self.agent_stop=threading.Event();self.cancel_download=threading.Event();self.action_lock=threading.Lock()
        self.cfg=desktop.initialize();self.binding=desktop.current_binding(load()) or {'origin':desktop.ORIGIN,'key':secrets.token_urlsafe(32)}
        save(self.binding)
        if rebind:self.binding={'origin':desktop.ORIGIN,'key':secrets.token_urlsafe(32)};save(self.binding)
        prefs=desktop.preferences()
        shortcut=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup/Agent Remote 027.lnk'
        self.startup=prefs.get('startup',shortcut.exists() if self.binding.get('device') else True)
        self.startup_busy=False
        self.auth_active=False
        self.state='未绑定';self.detail='';self.online=False;self.worker=None;self.icon=None;self.window=None
        self.update=None;self.update_title='';self.update_notes='';self.downloading=False;self.checking=False;self.percent=0;self.installer=None
        self.version=updates.metadata()['version'];self.shell=None;self.settings_open=False;self.nav_history=[]
        self.migration='';self.migration_flash_until=0;self.ui_ready=threading.Event();self.ui_actions=threading.Event();self.exiting=False
        if (DATA/'migration-result.json').exists():self.migration='配置和附件已迁移；旧目录仍保留。实机验证后再处理旧版。'

    def view(self):
        bound=bool(self.binding.get('device'))
        return dict(name=self.cfg.get('name') or socket.gethostname(),state=self.state,detail=self.detail or ('迁移完成，旧目录已保留。' if time.monotonic()<self.migration_flash_until else ''),online=self.online,
            migration='',version='版本 '+self.version,startup=self.startup,settingsVisible=self.settings_open,
            bindVisible=(not bound and not self.auth_active) or self.state=='需要重新绑定',rebind=self.state=='需要重新绑定',retryVisible=bound and not self.online and self.state!='需要重新绑定',
            accountVisible=True,legacyVisible=not bound and not self.auth_active,updateVisible=bool(self.update_title),
            updateTitle=self.update_title,updateNotes=self.update_notes,
            updateSummary='\n'.join(self.update.get('summary',[])) if self.update and self.update_notes==self.update.get('notes') else self.update_notes,
            updateDetails=self.update_notes if self.update and self.update_notes==self.update.get('notes') else '',
            downloadVisible=bool(self.update) and not self.downloading and not self.installer,
            installVisible=bool(self.installer) and not self.downloading,cancelDownloadVisible=self.downloading,
            downloading=self.downloading,percent=self.percent)

    def show(self):
        if self.window:
            self.window.show();self.window.restore()

    def close_window(self):
        if self.exiting:return True
        self.window.hide()
        prefs=desktop.preferences()
        if not prefs.get('close_hint'):
            if self.icon:self.icon.notify('程序仍在后台运行。右键托盘图标可打开窗口或退出。','Agent Remote')
            prefs['close_hint']=True;desktop.save_preferences(prefs)
        return False

    def dispatch(self,action):
        if self.stop.is_set():return
        if action=='cancel-download':self.cancel_download.set();return
        if not self.action_lock.acquire(blocking=False):return
        import pythoncom
        pythoncom.CoInitialize()
        try:
            if action in ('account','check-update'):
                if not hasattr(self,'nav_history'):self.nav_history=[]
                self.nav_history.append((bool(self.shell.remote_showing),self.settings_open,self.update_title,self.update_notes))
            if action=='bind':
                if self.state=='需要重新绑定':self.rebind()
                else:self.begin_auth()
            elif action=='account':
                self.settings_open=False
                if not self.binding.get('device'):self.begin_auth()
                else:self.shell.load_account(self.binding['origin']+'/account?choose=1')
            elif action=='startup':
                desired=not self.startup
                self.startup_busy=True
                try:desktop.set_startup(desired);self.startup=desired
                finally:self.startup_busy=False
            elif action=='rebind':self.rebind()
            elif action=='quit':self.quit()
            elif action=='back':
                if getattr(self,'nav_history',None):
                    remote,self.settings_open,self.update_title,self.update_notes=self.nav_history.pop()
                    if remote:self.shell.show_account()
                    else:self.shell.local_view()
                else:
                    if self.settings_open:self.shell.back()
                    elif self.binding.get('device'):self.shell.local_view()
                    self.settings_open=False
                if not self.binding.get('device') and not self.auth_active:self.begin_auth()
            elif action=='retry':self.start_agent()
            elif action=='check-update':self.check_update()
            elif action=='download':self.download_update()
            elif action=='install':self.install_update()
        except Exception as exc:
            self.detail=str(exc) if isinstance(exc,ValueError) else '操作未完成，请重试。'
            if self.shell:
                self.shell.sync();self.settings_open=True;self.update_title='操作未完成';self.update_notes=self.detail;self.shell.local_view(returnable=True)
        finally:
            if self.shell:self.shell.sync()
            pythoncom.CoUninitialize();self.action_lock.release()

    def harden_local(self):
        self.local_uri='data:text/html;charset=utf-8;base64,'+base64.b64encode((ASSETS/'desktop_status.html').read_text(encoding='utf-8').encode('utf-8')).decode()
        self.local_trusted=False
        desktop.harden_window(self.window,None,self.local_uri)
        native=self.window.native.webview
        def navigation(sender,args):
            uri=str(args.Uri);action=local_action(uri)
            if action:
                args.Cancel=True
                if self.ui_actions.is_set() and self.local_trusted and str(native.CoreWebView2.Source) in ('about:blank',self.local_uri):
                    threading.Thread(target=self.dispatch,args=(action,),daemon=True).start()
            elif uri==self.local_uri:self.local_trusted=True
            elif uri!='about:blank' or self.local_trusted:args.Cancel=True
        native.NavigationStarting+=navigation

    def begin_auth(self):
        if self.auth_active:
            self.shell.show_account();return
        self.auth_active=True
        self.auth_stop=threading.Event();cancel=self.auth_stop
        self.state='等待确认';self.detail='正在申请绑定请求…';self.online=False
        def flow():
            delay=2
            while not self.stop.is_set() and not cancel.is_set():
                try:
                    request=desktop.api(self.binding['origin'],'/device-auth/start',{'label':socket.gethostname()},self.binding['key'])
                    ident=request.get('id','')
                    if not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('服务器返回的请求无效')
                    if cancel.is_set() or self.stop.is_set():return
                    self.binding['pending']=ident;save(self.binding)
                    url=self.binding['origin']+'/account?authorize='+ident
                    self.shell.load_account(url)
                    self.detail='请在登录窗口确认绑定这台电脑。';delay=2
                    while not cancel.wait(delay) and not self.stop.is_set():
                        try:
                            result=desktop.api(self.binding['origin'],'/device-auth/poll',{'id':ident},self.binding['key'])
                            delay=2
                            if result.get('approved'):
                                device=result.get('device','')
                                if not re.fullmatch('[0-9a-f]{32}',device):raise ValueError('服务器返回的电脑信息无效')
                                if cancel.is_set() or self.stop.is_set():return
                                self.binding['device']=device;save(self.binding)
                                self.auth_active=False;self.settings_open=False;self.detail='';self.shell.clear_account();self.shell.local_view();self.start_agent();self.show();return
                        except desktop.ApiError as exc:
                            if exc.code in ('binding_expired','binding_not_found'):
                                self.detail='请求已更新，请在登录窗口重新确认。';break
                            if exc.code in ('invalid_device_credential','binding_unavailable'):raise
                            self.detail=str(exc)
                            delay=exc.retry_after if exc.code=='rate_limited' else min(delay*2,30)+random.random()
                except desktop.ApiError as exc:
                    if exc.code in ('invalid_device_credential','binding_unavailable'):
                        self.auth_active=False;self.state='需要重新绑定';self.detail=str(exc);return
                    self.detail=str(exc)
                    if cancel.wait(exc.retry_after if exc.code=='rate_limited' else min(delay,30)):return
                    delay=min(delay*2,30)
                except Exception:
                    self.auth_active=False;self.state='未绑定';self.detail='申请绑定未完成，请重新尝试登录。';return
        threading.Thread(target=flow,daemon=True).start()

    def rebind(self):
        self.show()
        if not self.window.create_confirmation_dialog('重新绑定','停止当前电脑连接并重新选择账号？'):return
        if self.shell:self.shell.clear_account()
        self.auth_stop.set();self.auth_active=False;self.agent_stop.set()
        if self.worker:self.worker.join(timeout=25)
        if self.worker and self.worker.is_alive():self.detail='正在停止连接，请稍后重试。';return
        self.binding={'origin':self.binding['origin'],'key':secrets.token_urlsafe(32)};save(self.binding)
        self.begin_auth()

    def choose_legacy(self):
        import webview
        if self.binding.get('device'):raise ValueError('请在绑定前选择旧版文件夹')
        result=self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if result:
            if self.binding.get('device'):raise ValueError('绑定已完成，请勿再次迁移')
            self.auth_stop.set();self.auth_active=False
            desktop.select_legacy(result[0]);self.migration='已选择旧版。绑定后迁移配置和附件，原目录保留。'
            self.begin_auth()

    def start_agent(self):
        if not self.binding.get('device'):return
        if self.worker and self.worker.is_alive():return
        self.agent_stop=threading.Event();cancel=self.agent_stop
        self.state='连接中';self.detail='';self.online=False
        def worker():
            import pythoncom
            pythoncom.CoInitialize()
            try:
                migrating=(DATA/'pending-migration.json').exists()
                self.cfg=desktop.complete_migration(self.cfg)
                if migrating:self.migration_flash_until=time.monotonic()+6
                self.cfg.setdefault('port',8765);self.cfg['bind']='127.0.0.1'
                (DATA/'remote_config.json').write_text(json.dumps(self.cfg,ensure_ascii=False),encoding='utf-8')
                if (DATA/'migration-result.json').exists():self.migration='配置和附件已迁移；旧目录仍保留。实机验证后再处理旧版。'
                desktop.set_startup(self.startup)
                asyncio.run(self.connect_agent(cancel))
            except Exception as exc:
                self.online=False;self.state='连接失败';self.detail=str(exc) if isinstance(exc,ValueError) else '本机服务未启动，请重试。'
            finally:pythoncom.CoUninitialize()
        self.worker=threading.Thread(target=worker,daemon=True);self.worker.start()

    async def connect_agent(self,cancel):
        from aiohttp import ClientResponseError
        from relay_agent import Agent
        owned=None
        try:
            owned=await asyncio.to_thread(desktop.backend,self.cfg,cancel)
            def state(value):
                self.online=value=='online'
                if self.state!='连接失败':self.state='需要重新绑定' if value=='unauthorized' else '已连接' if self.online else '断线重连'
                if value=='unauthorized':self.detail='设备凭据已失效，请从托盘选择重新绑定。'
            agent=Agent(self.binding['origin'],self.binding['key'],self.cfg['port'],self.cfg['token'],state=state)
            task=asyncio.create_task(agent.run())
            while not self.stop.is_set() and not cancel.is_set() and not task.done():
                await asyncio.sleep(1)
                if self.online and not await asyncio.to_thread(desktop.healthy,self.cfg):
                    self.online=False;self.state='连接失败';self.detail='本机服务不可用，请重新连接。';break
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        finally:
            if owned is not None and owned.poll() is None:
                owned.terminate()
                try:owned.wait(timeout=5)
                except subprocess.TimeoutExpired:owned.kill();owned.wait(timeout=3)
            self.online=False

    def check_update(self):
        self.show();self.settings_open=True;self.shell.local_view(returnable=True)
        if self.checking or self.downloading:return
        self.checking=True;self.update_title='正在检查更新…';self.update_notes=''
        def work():
            try:
                self.update=updates.check();self.installer=None
                self.update_title='发现新版本 '+self.update['version'] if self.update else '当前已是最新可用版本'
                self.update_notes=self.update['notes'] if self.update else ''
            except Exception:self.update_title='检查更新失败';self.update_notes='请检查网络，稍后重新检查。'
            finally:self.checking=False
        threading.Thread(target=work,daemon=True).start()

    def download_update(self):
        if not self.update or self.downloading:return
        if not getattr(sys,'frozen',False):raise ValueError('当前为源码运行，请使用安装版进行覆盖更新')
        self.downloading=True;self.cancel_download.clear();self.percent=0;self.update_title='正在下载更新…'
        def work():
            try:
                self.installer=updates.download(self.update,DATA/'updates',self.cancel_download,lambda p:setattr(self,'percent',p))
                self.update_title='更新已下载';self.update_notes='安装将暂时断开连接，保留账号、数据和自启设置。'
            except updates.Cancelled:self.update_title='下载已取消'
            except Exception as exc:self.update_title='下载未完成';self.update_notes=str(exc) if isinstance(exc,ValueError) else '请检查网络后重试。'
            finally:self.downloading=False
        threading.Thread(target=work,daemon=True).start()

    def install_update(self):
        if not self.installer or not self.update:return
        updates.verify_file(self.installer,self.update)
        subprocess.Popen([str(self.installer),'/DIR='+str(Path(sys.executable).parent)],cwd=self.installer.parent)
        self.quit()

    def quit(self):
        if self.exiting:return
        self.exiting=True;self.stop.set();self.auth_stop.set();self.agent_stop.set();self.cancel_download.set()
        if self.shell:self.shell.clear_account()
        if self.worker:self.worker.join(timeout=25)
        if self.icon:self.icon.stop()
        if self.shell:self.shell.close()
        if self.window:self.window.destroy()

    def run(self):
        import webview,pystray
        if os.name=='nt':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('AgentRemote.Desktop')
        from PIL import Image
        webview.settings['ALLOW_FILE_URLS']=False;webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
        self.window=webview.create_window('Agent Remote',html=(ASSETS/'desktop_status.html').read_text(encoding='utf-8'),width=440,height=640,min_size=(380,520),hidden=self.hidden,js_api=None,background_color='#ffffff')
        def configure():
            self.harden_local()
            from relay_shell import Shell
            self.shell=Shell(self)
        self.window.events.before_show+=configure
        self.window.events.loaded+=lambda:(self.ui_ready.set(),self.ui_actions.set())
        self.window.events.closing+=self.close_window
        def picture(name):
            with Image.open(ASSETS/'static'/name) as image:return image.convert('RGBA')
        # The tray shows the mark; its dot is the connection light, dimmed while this computer is not connected
        lit,dim=picture('tray-online.png'),picture('tray-offline.png')
        def action(name):return lambda icon,item:threading.Thread(target=self.dispatch,args=(name,),daemon=True).start()
        self.icon=pystray.Icon('AgentRemote',dim,'Agent Remote',menu=pystray.Menu(
            pystray.MenuItem('打开主窗口',lambda icon,item:self.show(),default=True),
            pystray.MenuItem('账号与电脑',action('account')),
            pystray.MenuItem('检查更新',action('check-update')),
            pystray.MenuItem('登录时启动',action('startup'),checked=lambda item:self.startup),
            pystray.MenuItem('重新绑定',lambda icon,item:threading.Thread(target=self.rebind,daemon=True).start()),
            pystray.MenuItem('退出',lambda icon,item:threading.Thread(target=self.quit,daemon=True).start())))
        threading.Thread(target=self.icon.run,daemon=True).start()
        def loop():
            self.ui_ready.wait(20)
            if self.binding.get('device'):self.start_agent()
            else:self.begin_auth()
            threading.Thread(target=self.instance.listen,args=(self.stop,self.show),daemon=True).start()
            previous=None;tray=None
            while not self.stop.wait(.4):
                if self.shell:self.shell.sync()
                view=self.view()
                if view!=previous:
                    try:self.window.evaluate_js('window.render('+json.dumps(view,ensure_ascii=True)+')');previous=view
                    except Exception:pass
                if (view['online'],view['state'])!=tray:
                    tray=(view['online'],view['state'])
                    try:self.icon.icon=lit if view['online'] else dim;self.icon.title='Agent Remote · '+view['state']
                    except Exception:pass
        try:webview.start(loop,gui='edgechromium',private_mode=True,debug=False,icon=str(ASSETS/'static/app.ico'))
        finally:self.stop.set();self.agent_stop.set();self.auth_stop.set();self.cancel_download.set();self.icon.stop()


def smoke():
    """Exercise both isolated controls in one real native window without user state."""
    import webview
    def trace(message):
        path=os.environ.get('AR_SMOKE_LOG')
        if path:
            with open(path,'a',encoding='utf-8') as f:f.write(message+'\n')
    trace('start')
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'");self.end_headers()
            self.wfile.write(b'<html><input id="email"><input id="password" type="password"></html>')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    c=DesktopController.__new__(DesktopController)
    c.ui_actions=threading.Event();c.startup=True;c.version='test';c.migration=''
    c.binding={'origin':'http://127.0.0.1:'+str(server.server_address[1])}
    actions=[];acted=threading.Event();errors=[]
    def dispatch(action):actions.append(action);acted.set()
    c.dispatch=dispatch
    c.window=webview.create_window('Single-window smoke',html=(ASSETS/'desktop_status.html').read_text(encoding='utf-8'),width=440,height=640,hidden=True,js_api=None)
    def configure():
        trace('configure');c.harden_local()
        from relay_shell import Shell
        c.shell=Shell(c);trace('configured')
    c.window.events.before_show+=configure
    c.window.events.loaded+=lambda:c.ui_actions.set()
    def test():
        try:
            from System import Func,Boolean,Object
            from System.Windows.Forms import Application
            assert c.ui_actions.wait(15);trace('local loaded')
            for _ in range(100):
                if c.window.evaluate_js('typeof window.render')=='function':break
                time.sleep(.1)
            else:raise AssertionError('Local view did not load')
            c.window.evaluate_js('window.render('+json.dumps({'name':'Test PC','state':'已连接'})+')')
            assert c.window.evaluate_js('document.getElementById("name").textContent')=='Test PC'
            notes={'settingsVisible':True,'updateTitle':'发现新版本 test','updateSummary':'修复菜单关闭。','updateDetails':'完整说明\n'+('内容'*400)+'<img src=x>'}
            c.window.evaluate_js('window.render('+json.dumps(notes)+')')
            assert c.window.evaluate_js('document.getElementById("updateDetails").open') is False
            assert c.window.evaluate_js('document.getElementById("highlightList").textContent')=='修复菜单关闭。'
            c.window.evaluate_js('document.getElementById("updateDetails").open=true')
            c.window.evaluate_js('window.render('+json.dumps(notes)+')')
            assert c.window.evaluate_js('document.getElementById("updateDetails").open') is True
            full=c.window.evaluate_js('document.getElementById("updateFullNotes").innerText')
            assert full.startswith('完整说明') and ('内容'*400)+'<img src=x>' in full
            assert c.window.evaluate_js('document.querySelector("#updateFullNotes img")===null') is True
            notes['updateTitle']='另一个版本';c.window.evaluate_js('window.render('+json.dumps(notes)+')')
            assert c.window.evaluate_js('document.getElementById("updateDetails").open') is False
            trace('release notes summary and full details')
            c.window.evaluate_js('location.href="agentremote-action://check-update"')
            assert acted.wait(5) and actions==['check-update'];trace('local action')
            assert c.shell.remote_ready.wait(15);trace('remote ready')
            assert c.window.native.Invoke(Func[Boolean](lambda:Application.OpenForms.Count==1))
            assert c.window.native.Invoke(Func[Boolean](lambda:abs((c.shell.gear.Top+c.shell.gear.Height/2)-(c.shell.title.Top+c.shell.title.Height/2))<=1))
            assert c.window.native.Invoke(Func[Boolean](lambda:c.shell.back_button.Left<c.shell.title.Left<c.shell.gear.Left))
            assert c.window.native.Invoke(Func[Boolean](lambda:not c.shell.remote.CreationProperties.IsInPrivateModeEnabled))
            def menu_check():
                from System.Drawing import Point
                assert 'legacy' not in c.shell.items and 'migration-info' not in c.shell.items
                c.shell.open_menu();menu=c.shell.menu;guard=c.shell.menu_dismissal
                inside=Point(menu.Left+20,menu.Top+20);outside=Point(menu.Right+20,menu.Bottom+20)
                guard.ObservePointer(False,inside);guard.ObservePointer(True,inside)
                assert menu.Visible,'Inside click dismissed the menu'
                guard.ObservePointer(False,outside);guard.ObservePointer(True,outside)
                assert not menu.Visible,'Outside click did not dismiss the menu'
                assert c.shell.form.Icon is c.shell.app_icon or c.shell.form.Icon.Equals(c.shell.app_icon)
                assert c.shell.form.ShowIcon
            c.shell.invoke(menu_check);trace('native outside dismissal and window icon')
            render_dir=os.environ.get('AR_SMOKE_RENDER_DIR')
            if render_dir:
                def capture():
                    from System.Drawing import Bitmap,Rectangle
                    from System.Drawing.Imaging import ImageFormat
                    folder=Path(render_dir);folder.mkdir(parents=True,exist_ok=True)
                    top=c.shell.root.GetControlFromPosition(0,0)
                    c.shell.back_button.Visible=True
                    graphics=top.CreateGraphics();print('Chrome render:',c.shell.title.Font.Name,c.shell.menu.Font.Name,graphics.DpiX,top.DeviceDpi);graphics.Dispose()
                    bitmap=Bitmap(top.Width,top.Height);top.DrawToBitmap(bitmap,Rectangle(0,0,top.Width,top.Height));bitmap.Save(str(folder/'header.png'),ImageFormat.Png);bitmap.Dispose()
                    menu=c.shell.menu;menu.CreateControl();menu.PerformLayout();menu.Size=menu.PreferredSize
                    bitmap=Bitmap(menu.Width,menu.Height);menu.DrawToBitmap(bitmap,Rectangle(0,0,menu.Width,menu.Height));bitmap.Save(str(folder/'menu.png'),ImageFormat.Png);bitmap.Dispose()
                c.shell.invoke(capture)
            assert c.window.native.Invoke(Func[Boolean](lambda:not c.shell.remote.CoreWebView2.Settings.IsWebMessageEnabled and not c.shell.remote.CoreWebView2.Settings.AreHostObjectsAllowed))
            loaded=threading.Event()
            def watch_navigation():
                def completed(sender,args):
                    if args.IsSuccess and str(c.shell.remote.CoreWebView2.Source).startswith(c.binding['origin']+'/'):loaded.set()
                c.shell.remote.CoreWebView2.NavigationCompleted+=completed
            c.shell.invoke(watch_navigation)
            c.shell.load_account(c.binding['origin']+'/account');assert loaded.wait(10);trace('remote loaded')
            def remote_js(script):
                task=c.window.native.Invoke(Func[Object](lambda:c.shell.remote.CoreWebView2.ExecuteScriptAsync(script)))
                # Reading Task.Result before completion can hold Python's GIL while
                # the UI callback needs it. Yield with a bound, then read the result.
                deadline=time.monotonic()+15
                while not task.IsCompleted:
                    if time.monotonic()>deadline:raise TimeoutError('WebView script did not complete')
                    time.sleep(.02)
                return json.loads(str(task.Result))
            assert remote_js('getComputedStyle(document.body).paddingTop')=='24px'
            if os.environ.get('AR_SMOKE_COOKIE')=='read':
                assert remote_js('document.cookie.includes("ar_fixture=persisted")'), 'Account profile did not survive restart'
            remote_js('document.cookie="ar_fixture=persisted; Max-Age=3600; SameSite=Strict; Path=/"')
            remote_js('document.getElementById("email").value="fixture@example.test"')
            trace('form filled');c.shell.local_view(returnable=True);c.shell.back()
            assert remote_js('document.getElementById("email").value')=='fixture@example.test'
            remote_js('location.href="agentremote-action://install"');time.sleep(.2)
            assert actions==['check-update'];trace('remote blocked')
            c.shell.invoke(lambda:setattr(c.shell.startup,'Checked',False))
            for _ in range(50):
                if actions[-1]=='startup':break
                time.sleep(.02)
            assert actions[-1]=='startup'
            c.shell.sync()
            assert c.window.native.Invoke(Func[Boolean](lambda:c.shell.startup.Checked))
            assert c.window.native.Invoke(Func[Boolean](lambda:Application.OpenForms.Count==1))
        except Exception as exc:errors.append(repr(exc));trace('error '+repr(exc))
        finally:
            trace('closing')
            if getattr(c,'shell',None):c.shell.close()
            c.window.destroy();trace('closed')
    timer=threading.Timer(45,c.window.destroy);timer.daemon=True;timer.start()
    try:webview.start(test,gui='edgechromium',private_mode=True,debug=False)
    finally:
        trace('webview returned');timer.cancel();server.shutdown();server.server_close()
    if errors:print('Native smoke:',errors)
    return 1 if errors else 0
