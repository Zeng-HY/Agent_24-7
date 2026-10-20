import json,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats,winctl
from codex_control import Bridge,ControlError

class LockedSendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.bridge=Bridge();self.bridge.data_root=Path(self.temp.name)
        self.body={'id':'session','request_id':'lock-test-request-001','text':'只发送一次','attachments':[],
                   'settings':{'model':'model','effort':'low','mode':'default'}}
        state={'latestCollaborationMode':{'mode':'default','settings':{'model':'model','reasoning_effort':'low'}},'threadRuntimeStatus':{'type':'idle'}}
        self.bridge.snapshot=Mock(return_value=({'id':'session'},'owner',state))
        self.bridge.validate_settings=Mock(return_value=self.body['settings'])
        self.pipe=SimpleNamespace(call=Mock(return_value={'result':{'accepted':True}}));self.bridge._pipe=lambda:self.pipe
    def tearDown(self):self.temp.cleanup()
    def test_locked_before_dispatch_then_user_retries_after_unlock(self):
        with patch('chats.winctl.input_desktop_ready',return_value=False):
            with self.assertRaises(chats.SendNotSubmitted):self.bridge.send(self.body)
        self.bridge.snapshot.assert_not_called();self.pipe.call.assert_not_called()
        self.assertEqual(self.bridge.receipt('session',self.body['request_id'])['state'],'unknown')
        with patch('chats.winctl.input_desktop_ready',return_value=True):self.assertTrue(self.bridge.send(self.body)['accepted'])
        with patch('chats.winctl.input_desktop_ready',return_value=False):self.assertTrue(self.bridge.send(self.body)['accepted'])
        self.assertEqual(self.pipe.call.call_count,1)
    def test_lock_during_preparation_still_does_not_dispatch(self):
        with patch('chats.winctl.input_desktop_ready',side_effect=[True,False]):
            with self.assertRaises(chats.SendNotSubmitted):self.bridge.send(self.body)
        self.pipe.call.assert_not_called();self.assertFalse((self.bridge.data_root/'delivery.sqlite').exists())
    def test_uncertain_old_request_never_replayed_after_unlock(self):
        self.bridge._begin(self.body['request_id'],'session',self.body)
        with patch('chats.winctl.input_desktop_ready',return_value=True),patch.object(self.bridge,'delivery_evidence',return_value={}):
            with self.assertRaises(ControlError):self.bridge.send(self.body)
        self.pipe.call.assert_not_called()
    def test_legacy_locked_guard_runs_before_window_work(self):
        desktop=object.__new__(chats.Desktop);desktop._send_claude=Mock();desktop._send_codex=Mock()
        with patch('chats.winctl.input_desktop_ready',return_value=False):
            for app in ('codex','claude'):
                with self.assertRaises(chats.SendNotSubmitted):desktop.send(app,'session','text')
        desktop._send_claude.assert_not_called();desktop._send_codex.assert_not_called()
    def test_desktop_handle_closed_even_when_name_read_fails(self):
        handle=SimpleNamespace(CloseDesktop=Mock())
        with patch('winctl.win32service.OpenInputDesktop',return_value=handle),patch('winctl.win32service.GetUserObjectInformation',side_effect=OSError('locked')):
            self.assertFalse(winctl.input_desktop_ready())
        handle.CloseDesktop.assert_called_once()
    def test_http_preserves_not_submitted_marker(self):
        import remote
        handler=object.__new__(remote.Handler);responses=[]
        handler.server=SimpleNamespace(codex=SimpleNamespace(send=Mock(side_effect=chats.SendNotSubmitted('locked'))))
        handler._json=lambda body,status=200:responses.append((body,status))
        handler._codex_post('/api/codex/send',self.body)
        self.assertTrue(responses[0][0]['not_submitted']);self.assertEqual(responses[0][0]['code'],'desktop_unavailable')
        self.assertEqual(responses[0][1],400)

if __name__=='__main__':unittest.main()
