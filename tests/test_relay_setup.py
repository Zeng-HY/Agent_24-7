import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import relay_setup


class SetupTests(unittest.TestCase):
    def test_verified_archive_only_installs_client_license_and_public_certificate(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'frp';folder.mkdir()
            cert=Path(tmp)/'public.crt';cert.write_text('-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----')
            archive=folder/relay_setup.ARCHIVE_NAME
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr(relay_setup.DIRECTORY+'/frpc.exe',b'dummy test binary')
                z.writestr(relay_setup.DIRECTORY+'/LICENSE',b'test license')
                z.writestr('../unwanted',b'not extracted')
            digest=hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.object(relay_setup,'FRP_SHA256',digest):
                installed=relay_setup.install_frpc(folder,cert)
                self.assertEqual(installed.read_bytes(),b'dummy test binary')
                self.assertEqual((folder/'config/server.crt').read_bytes(),cert.read_bytes())
                self.assertFalse((Path(tmp)/'unwanted').exists())
                installed.write_bytes(b'changed executable')
                with self.assertRaises(ValueError):relay_setup.install_frpc(folder,cert)

    def test_invalid_archive_fails_before_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/relay_setup.ARCHIVE_NAME).write_bytes(b'wrong download')
            with self.assertRaises(ValueError):relay_setup.install_frpc(folder,folder/'unused-cert')
            self.assertFalse((folder/relay_setup.DIRECTORY).exists())


if __name__=='__main__':unittest.main()
