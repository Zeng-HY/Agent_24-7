import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import relay_bind_gui as gui


class BindWindowTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(config=Mock(exists=Mock(return_value=False)),
            certificate=Mock(is_file=Mock(return_value=True)),frpc=Mock(is_file=Mock(return_value=True)),
            origin='https://relay.example',account='alice')

    def test_login_binding_and_logout_without_manual_code(self):
        with patch.object(gui,'account_request',side_effect=[{'ok':True},{'code':'test-grant'},{'ok':True}]) as api, \
             patch.object(gui,'enroll',return_value={'id':'device-id'}) as enroll:
            args = self.args()
            self.assertEqual(gui.login_and_bind(args,'password'),{'id':'device-id'})
            self.assertEqual([c.args[2] for c in api.call_args_list],['login','bind','logout'])
            enroll.assert_called_once_with(args,code='test-grant',confirmed=True)

    def test_binding_failure_still_logs_out_temporary_session(self):
        with patch.object(gui,'account_request',side_effect=[{'ok':True},{'code':'test-grant'},{'ok':True}]) as api, \
             patch.object(gui,'enroll',side_effect=ValueError('failed')):
            with self.assertRaises(ValueError): gui.login_and_bind(self.args(),'password')
            self.assertEqual(api.call_args_list[-1].args[2],'logout')

    def test_unknown_error_body_never_echoed(self):
        opener = Mock()
        opener.open.side_effect = HTTPError('https://relay.example/account/login',400,'Bad Request',{},
            io.BytesIO(b'{"error":"password echoed by upstream"}'))
        with self.assertRaises(ValueError) as error:
            gui.account_request(opener,'https://relay.example','login',{})
        self.assertNotIn('password',str(error.exception))


if __name__=='__main__': unittest.main()
