import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import relay_updates as u


class Updates(unittest.TestCase):
    def fixture(self,build=2):
        data=b'installer-test'
        info=dict(schema=1,version='0.27.0-dev.2',build=build,commit='a'*40,name='AgentRemote-0.27.0-dev.2-Setup.exe',size=len(data),sha256=hashlib.sha256(data).hexdigest())
        asset=dict(name=info['name'],size=len(data),digest='sha256:'+info['sha256'],browser_download_url=u.REPO+'windows-v0.27.0-dev.2/'+info['name'])
        release=dict(tag_name='windows-v0.27.0-dev.2',assets=[asset],body='Update',prerelease=True)
        return data,info,release

    def test_release_manifest_and_asset_must_agree_and_be_newer(self):
        data,info,r=self.fixture();current={'build':1}
        self.assertEqual(u.validate_manifest(info,r,current)['build'],2)
        self.assertIsNone(u.validate_manifest(info,r,{'build':2}))
        for key,value in [('digest','sha256:'+'b'*64),('size',1),('browser_download_url','https://evil.test/a.exe')]:
            _,_,bad=self.fixture();bad['assets'][0][key]=value
            with self.assertRaises(ValueError):u.validate_manifest(info,bad,current)

    def test_download_rejects_truncation_corruption_overflow_and_cancellation(self):
        data,info,_=self.fixture()
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'test.part';progress=[];cancel=threading.Event()
            u.transfer(io.BytesIO(data),p,info,cancel,progress.append)
            self.assertEqual(p.read_bytes(),data);self.assertEqual(progress[-1],100)
            for bad in (data[:-1],data+b'x',b'x'*len(data)):
                with self.assertRaises(ValueError):u.transfer(io.BytesIO(bad),p,info,cancel)
            cancel.set()
            with self.assertRaises(u.Cancelled):u.transfer(io.BytesIO(data),p,info,cancel)

    def test_cancel_removes_partial_and_keeps_previous_download(self):
        data,info,r=self.fixture();info['url']=r['assets'][0]['browser_download_url'];cancel=threading.Event();cancel.set()
        with tempfile.TemporaryDirectory() as temp,patch.object(u,'open_url',return_value=io.BytesIO(data)):
            target=Path(temp)/info['name'];target.write_bytes(b'old')
            with self.assertRaises(u.Cancelled):u.download(info,temp,cancel)
            self.assertEqual(target.read_bytes(),b'old');self.assertFalse(list(Path(temp).glob('*.part')))

    def test_no_update_and_prerelease_channel(self):
        with patch.object(u,'read_json',return_value=[]):self.assertIsNone(u.check({'version':'0.27.0','build':1}))
        _,info,r=self.fixture();r['assets'].append(dict(name='windows-update.json',browser_download_url=u.REPO+r['tag_name']+'/windows-update.json'))
        with patch.object(u,'read_json',side_effect=[[r],info]):self.assertEqual(u.check({'version':'0.27.0-dev.1','build':1})['build'],2)
        with patch.object(u,'read_json',return_value=[r]):self.assertIsNone(u.check({'version':'0.27.0','build':1}))

    def test_only_https_repository_and_official_download_hosts(self):
        self.assertTrue(u.allowed_url(u.API))
        for value in ['http://github.com/a','https://github.com/another/repo/releases/download/a','https://user:pass@release-assets.githubusercontent.com/a','https://release-assets.githubusercontent.com.evil.test/a','https://release-assets.githubusercontent.com:8000/a']:
            self.assertFalse(u.allowed_url(value))
