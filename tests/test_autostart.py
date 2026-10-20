import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import autostart

class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'remote';self.root.mkdir();(self.root/'logs').mkdir()
        (self.root/'remote_config.json').write_text(json.dumps({'port':8765,'token':'test-secret'}))
        self.location=patch.object(autostart,'HERE',self.root);self.location.start()
    def tearDown(self):self.location.stop();self.temp.cleanup()
    def test_existing_service_never_launches_duplicate(self):
        with patch.object(autostart,'healthy',return_value=True),patch.object(autostart.subprocess,'Popen') as spawn:
            self.assertEqual(autostart.launch(),0);spawn.assert_not_called()
    def test_unknown_listener_never_killed_or_duplicated(self):
        with patch.object(autostart,'healthy',return_value=False),patch.object(autostart,'occupied',return_value=True),patch.object(autostart.subprocess,'Popen') as spawn:
            self.assertEqual(autostart.launch(),2);spawn.assert_not_called()
    def test_start_uses_project_python_hidden_and_redacts_output(self):
        python=self.root/'.venv/Scripts/pythonw.exe';python.parent.mkdir(parents=True);python.touch()  # its own environment since 10-12
        with patch.object(autostart,'healthy',side_effect=[False,True]),patch.object(autostart,'occupied',return_value=False),patch.object(autostart.subprocess,'Popen') as spawn:
            self.assertEqual(autostart.launch(),0)
            self.assertEqual(spawn.call_args.args[0],[str(python),str(self.root/'remote.py')])
            self.assertEqual(spawn.call_args.kwargs['stdout'],autostart.subprocess.DEVNULL)
        self.assertNotIn('test-secret',(self.root/'logs/startup.log').read_text())

if __name__=='__main__':unittest.main()
