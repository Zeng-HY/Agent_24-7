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

ACTIONS={'bind','retry','account','legacy','check-update','startup','download','install','cancel-download'}


def local_action(uri):
    p=urlsplit(uri)
    if p.scheme=='agentremote-action' and p.netloc in ACTIONS and not p.path and not p.query and not p.fragment:return p.netloc
    return None


class DesktopController:
    def __init__(self,instance,start_hidden=False,rebind=False):
        self.instance=instance;self.hidden=start_hidden;self.stop=threading.Event();self.auth_stop=threading.Event()
        self.agent_stop=threading.Event();self.cancel_download=threading.Event();self.action_lock=threading.Lock()
        self.cfg=desktop.initialize();self.binding=load() or {'origin':desktop.ORIGIN,'key':secrets.token_urlsafe(32)}
        save(self.binding)
        if rebind:self.binding={'origin':desktop.ORIGIN,'key':secrets.token_urlsafe(32)};save(self.binding)
        prefs=desktop.preferences()
        shortcut=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup/Agent Remote 027.lnk'
        self.startup=prefs.get('startup',shortcut.exists() if self.binding.get('device') else True)
        self.auth_active=False
        self.state='未绑定';self.detail='';self.online=False;self.auth=None;self.worker=None;self.icon=None;self.window=None
        self.update=None;self.update_title='';self.update_notes='';self.downloading=False;self.checking=False;self.percent=0;self.installer=None
        self.migration='';self.ui_ready=threading.Event();self.ui_actions=threading.Event();self.exiting=False
        if (DATA/'migration-result.json').exists():self.migration='配置和附件已迁移；旧目录仍保留。实机验证后再处理旧版。'

    def view(self):
        bound=bool(self.binding.get('device'))
        return dict(name=self.cfg.get('name') or socket.gethostname(),state=self.state,detail=self.detail,online=self.online,
            migration=self.migration,version='版本 '+updates.metadata()['version'],startup=self.startup,
            bindVisible=(not bound and not self.auth_active) or self.state=='需要重新绑定',rebind=self.state=='需要重新绑定',retryVisible=bound and not self.online and self.state!='需要重新绑定',
            accountVisible=True,legacyVisible=not bound and not self.auth_active,updateVisible=bool(self.update_title),
            updateTitle=self.update_title,updateNotes=self.update_notes,downloadVisible=bool(self.update) and not self.downloading and not self.installer,
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
            if action=='bind':
                if self.state=='需要重新绑定':self.rebind()
                else:self.begin_auth()
            elif action=='account':webbrowser.open(self.binding['origin']+'/account')
            elif action=='startup':self.startup=not self.startup;desktop.set_startup(self.startup)
            elif action=='legacy':self.choose_legacy()
            elif action=='retry':self.start_agent()
            elif action=='check-update':self.check_update()
            elif action=='download':self.download_update()
            elif action=='install':self.install_update()
        except Exception as exc:self.detail=str(exc) if isinstance(exc,ValueError) else '操作未完成，请重试。'
        finally:pythoncom.CoUninitialize();self.action_lock.release()

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
        import webview
        if self.auth_active:
            if self.auth is not None:self.auth.show()
            return
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
                    if self.auth is None:
                        # Dynamic windows may already have fired before_show when create_window returns.
                        # Create blank, harden on the UI thread, and only then load the remote login page.
                        self.auth=webview.create_window('登录并绑定',html='<html></html>',hidden=True,width=500,height=700,min_size=(380,540),js_api=None,background_color='#ffffff')
                        auth=self.auth
                        from System import Action
                        auth.native.Invoke(Action(lambda:desktop.harden_window(auth,self.binding['origin'])))
                        def closed():
                            cancel.set()
                            if self.auth is auth:
                                self.auth=None;self.auth_active=False
                                if not self.binding.get('device'):self.state='未绑定';self.detail='';self.show()
                        auth.events.closed+=closed
                        auth.load_url(url);auth.show()
                    else:self.auth.load_url(url)
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
                                if self.auth:self.auth.destroy()
                                self.auth=None;self.auth_active=False;self.detail='';self.start_agent();self.show();return
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
                    self.auth_active=False;self.state='未绑定';self.detail='申请绑定未完成，请关闭登录窗口后重试。';return
        threading.Thread(target=flow,daemon=True).start()

    def rebind(self):
        self.show()
        if not self.window.create_confirmation_dialog('重新绑定','停止当前电脑连接并重新选择账号？'):return
        if self.auth:self.auth.destroy()
        self.auth_stop.set();self.auth_active=False;self.agent_stop.set()
        if self.worker:self.worker.join(timeout=25)
        if self.worker and self.worker.is_alive():self.detail='正在停止连接，请稍后重试。';return
        self.binding={'origin':self.binding['origin'],'key':secrets.token_urlsafe(32)};save(self.binding)
        self.begin_auth()

    def choose_legacy(self):
        import webview
        if self.binding.get('device') or self.auth is not None:raise ValueError('请在绑定前选择旧版文件夹')
        result=self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if result:
            desktop.select_legacy(result[0]);self.migration='已选择旧版。绑定后迁移配置和附件，原目录保留。'

    def start_agent(self):
        if not self.binding.get('device'):return
        if self.worker and self.worker.is_alive():return
        self.agent_stop=threading.Event();cancel=self.agent_stop
        self.state='连接中';self.detail='';self.online=False
        def worker():
            import pythoncom
            pythoncom.CoInitialize()
            try:
                self.cfg=desktop.complete_migration(self.cfg)
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
            owned=await asyncio.to_thread(desktop.backend,self.cfg)
            def state(value):
                self.online=value=='online'
                self.state='需要重新绑定' if value=='unauthorized' else '已连接' if self.online else '断线重连'
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
        self.show()
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
        if not self.window.create_confirmation_dialog('安装更新','现在安装更新并暂时断开这台电脑的连接？'):return
        updates.verify_file(self.installer,self.update)
        subprocess.Popen([str(self.installer),'/DIR='+str(Path(sys.executable).parent)],cwd=self.installer.parent)
        self.quit()

    def quit(self):
        if self.exiting:return
        self.exiting=True;self.stop.set();self.auth_stop.set();self.agent_stop.set();self.cancel_download.set()
        if self.auth:self.auth.destroy()
        if self.worker:self.worker.join(timeout=25)
        if self.icon:self.icon.stop()
        if self.window:self.window.destroy()

    def run(self):
        import webview,pystray
        from PIL import Image,ImageDraw
        webview.settings['ALLOW_FILE_URLS']=False;webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
        self.window=webview.create_window('Agent Remote',html=(ASSETS/'desktop_status.html').read_text(encoding='utf-8'),width=440,height=700,min_size=(380,540),hidden=self.hidden,js_api=None,background_color='#ffffff')
        self.window.events.before_show+=self.harden_local
        self.window.events.loaded+=lambda:(self.ui_ready.set(),self.ui_actions.set())
        self.window.events.closing+=self.close_window
        image=Image.new('RGBA',(64,64),(0,0,0,0));draw=ImageDraw.Draw(image);draw.rounded_rectangle((6,8,58,48),radius=8,fill='#171717');draw.line((23,56,41,56),fill='#171717',width=5)
        def action(name):return lambda icon,item:threading.Thread(target=self.dispatch,args=(name,),daemon=True).start()
        self.icon=pystray.Icon('AgentRemote',image,'Agent Remote',menu=pystray.Menu(
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
            threading.Thread(target=self.instance.listen,args=(self.stop,self.show),daemon=True).start()
            previous=None
            while not self.stop.wait(.4):
                view=self.view()
                if view!=previous:
                    try:self.window.evaluate_js('window.render('+json.dumps(view,ensure_ascii=True)+')');previous=view
                    except Exception:pass
        try:webview.start(loop,gui='edgechromium',private_mode=True,debug=False)
        finally:self.stop.set();self.agent_stop.set();self.auth_stop.set();self.cancel_download.set();self.icon.stop()


def smoke():
    import webview
    c=DesktopController.__new__(DesktopController)
    c.ui_actions=threading.Event();actions=[];acted=threading.Event()
    def dispatch(a):actions.append(a);acted.set()
    c.dispatch=dispatch
    c.window=webview.create_window('Status smoke',html=(ASSETS/'desktop_status.html').read_text(encoding='utf-8'),width=440,height=700,hidden=True,js_api=None)
    def harden():
     c.harden_local()
    c.window.events.before_show+=harden
    c.window.events.loaded+=lambda:c.ui_actions.set()
    errors=[]
    def test():
     try:
      assert c.ui_actions.wait(15)
      for _ in range(100):
       if c.window.evaluate_js('typeof window.render')=='function':break
       time.sleep(.1)
      else:raise AssertionError('Status HTML did not load')
      c.window.evaluate_js('window.render('+json.dumps({'name':'Test PC','state':'未绑定','bindVisible':True,'version':'0.27.0-dev.1'})+')')
      assert c.window.evaluate_js('document.getElementById("name").textContent')=='Test PC'
      c.window.evaluate_js('location.href="agentremote-action://check-update"')
      assert acted.wait(5), 'Native action not received'
      assert actions==['check-update']
      c.window.evaluate_js('location.href="https://example.invalid"')
      assert c.window.evaluate_js('location.href') in ('about:blank',c.local_uri)
      from System import Func, Boolean
      assert c.window.native.webview.Invoke(Func[Boolean](lambda:not c.window.native.webview.CoreWebView2.Settings.IsWebMessageEnabled and not c.window.native.webview.CoreWebView2.Settings.AreHostObjectsAllowed))
      child=webview.create_window('Auth smoke',html='<html></html>',hidden=True,js_api=None)
      from System import Action
      child.native.Invoke(Action(lambda:desktop.harden_window(child,'https://example.test')))
      child.events.loaded.wait(5)
      assert child.native.webview.Invoke(Func[Boolean](lambda:not child.native.webview.CoreWebView2.Settings.IsWebMessageEnabled and not child.native.webview.CoreWebView2.Settings.AreHostObjectsAllowed))
      child.destroy()
     except Exception as e:errors.append(repr(e))
     finally:c.window.destroy()
    timeout=threading.Timer(30,c.window.destroy);timeout.daemon=True;timeout.start()
    webview.start(test,gui='edgechromium',private_mode=True,debug=False)
    timeout.cancel()
    return 1 if errors else 0
