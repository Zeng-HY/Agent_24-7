from pathlib import Path
from contextlib import closing
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import relay_desktop


class DesktopTests(unittest.TestCase):
    def test_unknown_listener_is_never_stopped(self):
        with patch('autostart.occupied',return_value=True),patch.object(relay_desktop,'healthy',return_value=False),patch('subprocess.run') as run:
            with self.assertRaises(ValueError):relay_desktop.stop_legacy_backend(Path('C:/test'),{'port':8765,'token':'test'})
            run.assert_not_called()

    def test_only_authenticated_matching_backend_pid_is_stopped(self):
        legacy=Path('C:/test').resolve()
        wmi=Mock();wmi.ExecQuery.return_value=[SimpleNamespace(CommandLine='python "'+str(legacy/'remote.py')+'"')]
        with patch('autostart.occupied',side_effect=[True,False]),patch.object(relay_desktop,'healthy',return_value=True),patch('setup_machine.listener',return_value=42),patch('win32com.client.GetObject',return_value=wmi),patch('subprocess.run') as run:
            self.assertTrue(relay_desktop.stop_legacy_backend(legacy,{'port':8765,'token':'test'}))
            self.assertEqual(run.call_args.args[0],['taskkill','/F','/PID','42'])

    def test_startup_shortcut_roundtrip_is_idempotent_in_disposable_folder(self):
        import win32com.client
        real=win32com.client.Dispatch('WScript.Shell')
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);data=folder/'data';data.mkdir()
            startup=folder/'startup';startup.mkdir()
            legacy=real.CreateShortcut(str(startup/'Agent Remote.lnk'))
            legacy.TargetPath=sys.executable;legacy.Arguments='"C:\\test\\autostart.py"';legacy.Save()
            facade=SimpleNamespace(SpecialFolders=lambda name:str(startup),CreateShortcut=real.CreateShortcut)
            with patch.object(relay_desktop,'DATA',data),patch.object(relay_desktop,'command',return_value=[sys.executable,'--tray']):
                relay_desktop.startup(True,shell=facade);relay_desktop.startup(True,shell=facade)
                self.assertEqual(len(list(startup.glob('*.lnk'))),1)
                shortcut=real.CreateShortcut(str(startup/'Agent Remote 027.lnk'))
                self.assertEqual(shortcut.Arguments,'--tray')
                self.assertTrue((data/'migration-backup/Agent Remote.lnk').exists())
                relay_desktop.startup(False,shell=facade)
                self.assertFalse((startup/'Agent Remote 027.lnk').exists())

    def test_legacy_data_migration_preserves_original_and_copies_consistent_database(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);old=base/'old';old.mkdir();new=base/'new'
            cfg={'port':8765,'token':'disposable-token'}
            (old/'remote_config.json').write_text(json.dumps(cfg),encoding='utf-8-sig')
            (old/'attachments').mkdir()
            db=sqlite3.connect(old/'attachments/ledger.sqlite')
            db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE sample(value TEXT)')
            db.execute('INSERT INTO sample VALUES (?)',('kept',));db.commit()
            try:
                with patch.object(relay_desktop,'DATA',new),patch.object(relay_desktop,'detect_legacy',return_value=old),patch.object(relay_desktop,'stop_legacy_backend',return_value=False):
                    self.assertEqual(relay_desktop.initialize(),cfg)
                    self.assertFalse((new/'attachments/ledger.sqlite').exists())
                    self.assertEqual(relay_desktop.complete_migration(cfg),cfg)
                with closing(sqlite3.connect(new/'attachments/ledger.sqlite')) as copied:
                    self.assertEqual(copied.execute('SELECT value FROM sample').fetchone()[0],'kept')
                self.assertTrue((old/'remote_config.json').exists())
                self.assertTrue((new/'migration-backup/remote_config.json').exists())
                self.assertFalse((new/'attachments/ledger.sqlite-wal').exists())
            finally:db.close()


if __name__=='__main__':unittest.main()
