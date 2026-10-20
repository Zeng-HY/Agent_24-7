import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chats


class NewEnvironmentTests(unittest.TestCase):
    def desktop(self, names, selected_path=''):
        d=object.__new__(chats.Desktop)
        d.input_lock=threading.RLock()
        d._claude_root=Mock(return_value=(1,'root'))
        d._claude_show=Mock()
        button=lambda name:SimpleNamespace(Name=name,IsOffscreen=False,IsEnabled=True)
        d._claude_new_buttons=Mock(return_value=('doc',[button(n) for n in names]))
        d._claude_verified_prompt=Mock(return_value=('doc','edit'))
        d._fill_claude_prompt=Mock(return_value=('doc','edit'))
        d._claude_image_count=Mock(return_value=0)
        d._value=lambda edit:'hello'
        invoke=Mock(return_value=True)
        send=button('Send');send.GetInvokePattern=lambda:SimpleNamespace(Invoke=invoke)
        d._find=lambda scope,kind,name=None: [button(selected_path)] if kind=='ListItemControl' else [send] if name=='Send' else []
        return d,invoke

    def test_named_environment_checks_full_selected_path_before_submit(self):
        folder=str(Path('project').resolve())
        d,invoke=self.desktop(['Environment: project'],'project'+folder)
        dispatched=Mock()
        with patch('chats.require_send_desktop'):
            d._new_claude_now(folder,'hello',[],dispatched,True)
        dispatched.assert_called_once();invoke.assert_called_once()

    def test_same_name_wrong_path_never_fills_or_sends(self):
        d,invoke=self.desktop(['Environment: project'],'project'+str(Path('other/project').resolve()))
        with patch('chats.require_send_desktop'):
            with self.assertRaises(chats.InputNotSubmitted):
                d._new_claude_now(str(Path('project').resolve()),'hello',[],Mock(),True)
        d._fill_claude_prompt.assert_not_called();invoke.assert_not_called()

    def test_default_environment_without_folder(self):
        d,invoke=self.desktop(['Environment: This computer','Folder: Choose folder…'])
        with patch('chats.require_send_desktop'):
            d._new_claude_now('','hello',[],Mock())
        invoke.assert_called_once()


if __name__=='__main__':unittest.main()
