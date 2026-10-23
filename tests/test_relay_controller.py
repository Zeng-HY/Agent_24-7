import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_identity import Identity,BindingError
from relay_controller import local_action
import relay_desktop as d


class Controller(unittest.TestCase):
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
