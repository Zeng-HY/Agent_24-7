from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from relay_vault import load,save


class Vault(unittest.TestCase):
    def test_dpapi_roundtrip_no_plaintext_and_atomic_update(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'private/device.bin'
            first={'key':'private-device-key','origin':'https://relay.example'}
            save(first,path)
            self.assertNotIn(b'private-device-key',path.read_bytes())
            self.assertEqual(load(path),first)
            save({**first,'device':'known-id'},path)
            self.assertEqual(load(path)['device'],'known-id')
            self.assertEqual(len(list(path.parent.iterdir())),1)


if __name__=='__main__':unittest.main()
