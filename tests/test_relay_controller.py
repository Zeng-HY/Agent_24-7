import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_identity import Identity,BindingError
from relay_controller import local_action
import relay_desktop as d


class Controller(unittest.TestCase):
    def test_failed_startup_change_keeps_previous_value(self):
        from relay_controller import DesktopController
        c=DesktopController.__new__(DesktopController)
        c.stop=threading.Event();c.action_lock=threading.Lock();c.startup=True;c.shell=Mock()
        with patch.object(d,'set_startup',side_effect=OSError('fixture')):
            c.dispatch('startup')
        self.assertTrue(c.startup)
        c.shell.sync.assert_called()

    def test_a_binding_made_on_the_ip_moves_to_the_domain_and_keeps_its_key(self):
        self.assertEqual(d.current_binding({'origin':'https://8.166.15.235','key':'k','device':'x'}),
                         {'origin':'https://app.pocketagentdesk.com','key':'k','device':'x'})
        self.assertEqual(d.current_binding({'origin':'http://127.0.0.1:9','key':'k'})['origin'],'http://127.0.0.1:9')
        self.assertIsNone(d.current_binding(None))

    def test_local_commands_accept_no_payload_or_remote_navigation(self):
        self.assertEqual(local_action('agentremote-action://check-update'),'check-update')
        for uri in ['https://example.test','agentremote-action://install?url=https://evil.test','agentremote-action://bind/extra','agentremote-action://exit','javascript:alert(1)']:
            self.assertIsNone(local_action(uri))

    def test_expiration_refresh_and_approved_result_survive_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Identity(Path(temp)/'state.db');key=secrets.token_urlsafe(32)
            request=store.start_authorization(key,'test')
            with store.connect() as db:db.execute('UPDATE device_authorizations SET expires=? WHERE id=?',(time.time()-1,request))
            with self.assertRaises(BindingError) as error:store.authorization(request,key)
            self.assertEqual(error.exception.code,'binding_expired')
            fresh=store.start_authorization(key,'test');self.assertNotEqual(fresh,request)
            store.register('test','test-password-long',store.grant('invite'))
            session=store.login('test','test-password-long');device=store.approve(session,fresh)
            with store.connect() as db:db.execute('UPDATE device_authorizations SET expires=? WHERE id=?',(time.time()-1,fresh))
            self.assertEqual(store.start_authorization(key,'test'),fresh)
            self.assertEqual(store.authorization(fresh,key)['device'],device)
            self.assertEqual(store.approve(session,fresh),device)
            with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM devices').fetchone()[0],1)
            with self.assertRaises(BindingError) as error:store.authorization('missing',key)
            self.assertEqual(error.exception.code,'binding_not_found')

    def test_current_user_instance_signals_existing_process(self):
        from relay_instance import Instance
        suffix='-test-'+secrets.token_hex(8);first=Instance(suffix)
        try:
            self.assertTrue(first.primary)
            second=Instance(suffix)
            try:
                self.assertFalse(second.primary);self.assertFalse(second.legacy)
                self.assertEqual(first.event_api.WaitForSingleObject(first.show,1000),0)
            finally:second.close()
        finally:first.close()

    def test_disabled_startup_preference_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(d,'DATA',Path(temp)),patch.object(d,'startup') as startup:
            d.set_startup(False)
            self.assertIs(d.preferences()['startup'],False)
            startup.assert_called_once_with(False)

    def test_manual_selection_requires_real_legacy_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';old.mkdir();data=root/'data';data.mkdir()
            with patch.object(d,'DATA',data):
                with self.assertRaises(ValueError):d.select_legacy(old)
                (old/'remote.py').write_text('# placeholder');(old/'remote_config.json').write_text(json.dumps({'token':'test','port':8765}))
                self.assertEqual(d.select_legacy(old)['port'],8765)
                self.assertTrue((data/'pending-migration.json').exists())
                self.assertFalse((data/'remote_config.json').exists())

    def test_tray_status_dot_is_green_only_while_connected(self):
        from relay_controller import DesktopController
        seen=[];views=[(False,'连接中'),(True,'已连接'),(True,'已连接'),(False,'断线重连')]
        dot=lambda image:image.getpixel((42,214))[:3]  # centre of the lower-left status dot
        class Hook(list):
            def __iadd__(self,handler):self.append(handler);return self
        class Icon:
            def __init__(self,name,image,title,menu=None):seen.append(('start',dot(image),title))
            icon=property(None,lambda self,image:seen.append(('dot',dot(image))))
            title=property(None,lambda self,text:seen.append(('title',text)))
            def run(self):pass
            def stop(self):pass
        def start(loop,**options):
            worker=threading.Thread(target=loop,daemon=True);worker.start();worker.join(30)
        window=types.SimpleNamespace(events=types.SimpleNamespace(before_show=Hook(),loaded=Hook(),closing=Hook()),evaluate_js=lambda script:None)
        webview=types.SimpleNamespace(settings={},create_window=lambda *args,**kw:window,start=start)
        pystray=types.SimpleNamespace(Icon=Icon,Menu=lambda *items:items,MenuItem=lambda *args,**kw:args)
        c=DesktopController.__new__(DesktopController)
        for name in ('stop','ui_ready','ui_actions','agent_stop','auth_stop','cancel_download'):setattr(c,name,threading.Event())
        c.ui_ready.set();c.hidden=False;c.binding={};c.instance=types.SimpleNamespace(listen=lambda stop,show:None)
        c.harden_local=c.close_window=c.begin_auth=c.start_agent=lambda *args:None;c.shell=None
        def view():
            online,state=views.pop(0)
            if not views:c.stop.set()
            return {'online':online,'state':state}
        c.view=view
        with patch.dict(sys.modules,{'webview':webview,'pystray':pystray}):c.run()
        lit,dim=(22,136,75),(196,131,0)
        self.assertEqual(seen,[('start',dim,'Agent Remote'),('dot',dim),('title','Agent Remote · 连接中'),('dot',lit),
            ('title','Agent Remote · 已连接'),('dot',dim),('title','Agent Remote · 断线重连')])
