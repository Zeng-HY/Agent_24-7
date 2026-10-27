import base64
import hashlib
from http.client import IncompleteRead
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import relay_updates as u

ROOT=Path(__file__).resolve().parents[1]
# Made by Python's cryptography with a throwaway key, as deploy/updates/publish.py signs; the Android test checks the same.
TEST_KEY='MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEDkPNGGjzdLIPjYcTneoLrTl/YNy/J1OZq6DwHVlVEzB2Mv5avsQp1nJpAKbvwxLnMLZP6582cQg0yaq8K+4/qA=='
MESSAGE='{"schema": 1, "product": "test", "notes": "测试 vector"}'.encode('utf-8')
SIGNATURES=['MEUCIBVNtELOXily0NHImShXkJ2NNM6ruLSdnldAVpIUUg/GAiEAuPstKCioXosZhoO6TjndERhVntPPst9S/ybnZL2q4S8=',  # s padded with a zero byte
            'MEMCH1jg7fCGg0URdJj5GO1Sq3IYNE4W3oy5nlVouYNZpEUCIAJEt6I/UtDMaRSSlDc6YUMbXThF5iHam26jHiQBp0wT']  # r one byte short


def good_only(data,signature,key=u.KEY):
    """Stands in for the real check in the flow tests: the signature "good" signs anything."""
    if signature.strip()!='good':raise ValueError('更新签名不正确')


class Updates(unittest.TestCase):
    def fixture(self,build=2,version='0.27.0-dev.2'):
        data=b'installer-test';name='AgentRemote-'+version+'-Setup.exe';tag='windows-v'+version
        info=dict(schema=1,product='windows',channel=u.channel({'version':version}),version=version,build=build,commit='a'*40,name=name,
                  size=len(data),sha256=hashlib.sha256(data).hexdigest(),urls=[u.ALIYUN+name,u.REPO+tag+'/'+name])
        asset=dict(name=name,size=len(data),digest='sha256:'+info['sha256'],browser_download_url=u.REPO+tag+'/'+name)
        release=dict(tag_name=tag,assets=[asset],body='Update',prerelease='-dev.' in version)
        return data,info,release

    def test_authored_summary_and_full_notes_are_not_truncated(self):
        _,info,r=self.fixture()
        info['summary']=['设置菜单点击外部即可关闭。']
        r['body']='完整说明\n'+('详细内容'*400)
        parsed=u.validate_manifest(info,r,{'version':'0.27.0-dev.1','build':1})
        self.assertEqual(parsed['summary'],info['summary'])
        self.assertEqual(parsed['notes'],r['body'])
        info['notes']='构建时附带的完整说明'
        self.assertEqual(u.release_notes(info,r)[1],info['notes'])
        self.assertEqual(u.release_notes(info,None)[1],info['notes'])

    def test_legacy_published_version_has_an_authored_summary(self):
        summary,notes=u.release_notes({'version':'0.27.0-dev.5'},{'body':'旧版完整说明'})
        self.assertIn('首次打开',summary[0]);self.assertEqual(notes,'旧版完整说明')
        summary,_=u.release_notes({'version':'unknown','summary':'not a list'},{'body':'full'})
        self.assertEqual(len(summary),1);self.assertIn('未提供',summary[0])

    def test_release_manifest_and_asset_must_agree_and_be_newer(self):
        data,info,r=self.fixture();current={'version':'0.27.0-dev.1','build':1}
        self.assertEqual(u.validate_manifest(info,r,current)['build'],2)
        self.assertIsNone(u.validate_manifest(info,r,{'version':'0.27.0-dev.2','build':2}))
        for key,value in [('digest','sha256:'+'b'*64),('size',1),('browser_download_url','https://evil.test/a.exe')]:
            _,_,bad=self.fixture();bad['assets'][0][key]=value
            with self.assertRaises(ValueError):u.validate_manifest(info,bad,current)

    def test_manifest_must_be_for_windows_and_the_installs_channel(self):
        current={'version':'0.27.0-dev.1','build':1}
        for key,value in [('product','android'),('product',None),('channel','stable'),('schema',2)]:
            _,info,_=self.fixture();info[key]=value
            with self.assertRaises(ValueError):u.validate_manifest(info,None,current)
        _,dev,_=self.fixture(5);_,stable,_=self.fixture(6,'0.27.0')
        self.assertIsNone(u.validate_manifest(dev,None,{'version':'0.26.0','build':1}))
        self.assertEqual(u.validate_manifest(stable,None,{'version':'0.26.0','build':1})['build'],6)
        self.assertEqual(u.validate_manifest(stable,None,current)['build'],6)

    def test_download_addresses_come_from_the_signed_manifest(self):
        _,info,r=self.fixture();current={'version':'0.27.0-dev.1','build':1};name=info['name']
        self.assertEqual(u.validate_manifest(info,None,current)['urls'],info['urls'])
        self.assertEqual(u.validate_manifest(dict(info,urls=list(reversed(info['urls']))),r,current)['urls'],[u.REPO+r['tag_name']+'/'+name,u.ALIYUN+name])
        # A later mirror this build does not know is skipped, not refused; nothing usable is refused.
        kept=u.validate_manifest(dict(info,urls=['https://cdn.example/windows/'+name,u.ALIYUN+'other.exe',u.MIRROR+name]),None,current)['urls']
        self.assertEqual(kept,[u.MIRROR+name])
        for urls in (['https://cdn.example/windows/'+name],[],'not a list'):
            with self.assertRaises(ValueError):u.validate_manifest(dict(info,urls=urls),None,current)

    @unittest.skipUnless(os.name=='nt','Windows checks the signature itself (CNG)')
    def test_signatures_made_by_the_release_tool(self):
        for signature in SIGNATURES:u.verify_signature(MESSAGE,signature+'\n',TEST_KEY)
        for data,signature,key in [(MESSAGE+b' ',SIGNATURES[0],TEST_KEY),(MESSAGE,SIGNATURES[0],u.KEY),(MESSAGE,'AAAA',TEST_KEY),(MESSAGE,'not base64!',TEST_KEY),(MESSAGE,'',TEST_KEY),(MESSAGE,SIGNATURES[0],'AAAA')]:
            with self.assertRaises(ValueError):u.verify_signature(data,signature,key)
        der=base64.b64decode(SIGNATURES[0])
        self.assertEqual(len(u.raw_signature(der)),64)
        for bad in (der[:-1],der+b'\0',b'\x31'+der[1:],der[:2]+b'\x03'+der[3:]):
            with self.assertRaises(ValueError):u.raw_signature(bad)

    def test_the_apps_carry_one_p256_key_and_their_folders_on_alibaba_cloud(self):
        spki=base64.b64decode(u.KEY);self.assertEqual(len(spki),91);self.assertEqual(spki[:27],u.P256)
        kotlin=(ROOT/'apps/android/app/src/main/java/com/pocketagentdesk/teleply/Updates.kt').read_text(encoding='utf-8')
        constant=lambda name:re.search(r'const val '+name+r' = "([^"]*)"',kotlin).group(1)
        self.assertEqual(constant('Key'),u.KEY)
        self.assertEqual(constant('Aliyun'),u.ALIYUN.replace('/windows/','/android/'))
        self.assertEqual(constant('Mirror'),u.MIRROR.replace('/windows/','/android/'))
        try:from cryptography.hazmat.primitives import serialization
        except ImportError:return
        self.assertEqual(serialization.load_der_public_key(spki).curve.name,'secp256r1')

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
        data,info,r=self.fixture();cancel=threading.Event();cancel.set()
        with tempfile.TemporaryDirectory() as temp,patch.object(u,'open_url',return_value=io.BytesIO(data)):
            target=Path(temp)/info['name'];target.write_bytes(b'old')
            with self.assertRaises(u.Cancelled):u.download(info,temp,cancel)
            self.assertEqual(target.read_bytes(),b'old');self.assertFalse(list(Path(temp).glob('*.part')))

    def test_download_moves_on_when_an_address_fails_or_delivers_another_file(self):
        data,info,_=self.fixture();cancel=threading.Event()
        class Dropped(io.BytesIO):
            def read(self,size=-1):raise IncompleteRead(b'')
        def opener(*answers):
            answers=list(answers)
            def open_url(url):
                answer=answers.pop(0)
                if isinstance(answer,Exception):raise answer
                return answer if isinstance(answer,io.IOBase) else io.BytesIO(answer)
            return open_url
        with tempfile.TemporaryDirectory() as temp:
            for first in (OSError('unreachable'),b'x'*len(data),Dropped()):
                with patch.object(u,'open_url',opener(first,data)):self.assertEqual(u.download(info,temp,cancel).read_bytes(),data)
            with patch.object(u,'open_url',opener(OSError('unreachable'),data[:-1])),self.assertRaises(ValueError):u.download(info,temp,cancel)
            self.assertFalse(list(Path(temp).glob('*.part')))

    def serve(self,files):
        """read_bytes over a dict of addresses; anything else is unreachable, an exception there is raised."""
        asked=[]
        def read_bytes(url,limit):
            asked.append(url)
            if url not in files:raise OSError('unreachable '+url)
            if isinstance(files[url],Exception):raise files[url]
            return files[url]
        return read_bytes,asked

    def test_alibaba_cloud_first_and_github_only_when_it_cannot_answer(self):
        _,info,r=self.fixture(5);dev=u.ALIYUN+'dev/windows-update.json';current={'version':'0.27.0-dev.4','build':4}
        raw=json.dumps(info).encode()
        github=dict(r,assets=r['assets']+[dict(name=n,browser_download_url=u.REPO+r['tag_name']+'/'+n) for n in ('windows-update.json','windows-update.json.sig')])
        on_github={u.REPO+r['tag_name']+'/windows-update.json':raw,u.REPO+r['tag_name']+'/windows-update.json.sig':b'good\n'}
        with patch.object(u,'verify_signature',good_only):
            read,asked=self.serve({dev:raw,dev+'.sig':b'good\n'})
            with patch.object(u,'read_bytes',read),patch.object(u,'read_json',side_effect=AssertionError('GitHub asked')):
                self.assertEqual(u.check(current)['urls'][0],u.ALIYUN+info['name'])
                self.assertIsNone(u.check({'version':'0.27.0-dev.5','build':5}))
            self.assertEqual(asked[:2],[dev,dev+'.sig'])
            for aliyun in ({},{dev:raw,dev+'.sig':b'forged\n'},{dev:b'{',dev+'.sig':b'good'},{dev:IncompleteRead(b'')}):
                read,_=self.serve(dict(aliyun,**on_github))
                with patch.object(u,'read_bytes',read),patch.object(u,'read_json',return_value=[github]):
                    found=u.check(current)
                self.assertEqual(found['urls'],[u.REPO+r['tag_name']+'/'+info['name'],u.ALIYUN+info['name']])
            read,asked=self.serve({})
            with patch.object(u,'read_bytes',read),patch.object(u,'read_json',return_value=[]):self.assertIsNone(u.check({'version':'0.27.0','build':1}))
            self.assertEqual(asked,[u.ALIYUN+'stable/windows-update.json'])

    def test_github_needs_the_signed_manifest_and_respects_the_channel(self):
        _,info,r=self.fixture();raw=json.dumps(info).encode();base=u.REPO+r['tag_name']+'/'
        def with_assets(*names):return dict(r,assets=r['assets']+[dict(name=n,browser_download_url=base+n) for n in names])
        read,_=self.serve({base+'windows-update.json':raw,base+'windows-update.json.sig':b'good'})
        with patch.object(u,'verify_signature',good_only),patch.object(u,'read_bytes',read):
            with patch.object(u,'read_json',return_value=[with_assets('windows-update.json')]):self.assertIsNone(u.check_github({'version':'0.27.0-dev.1','build':1}))
            with patch.object(u,'read_json',return_value=[with_assets('windows-update.json','windows-update.json.sig')]):
                self.assertEqual(u.check_github({'version':'0.27.0-dev.1','build':1})['build'],2)
                self.assertIsNone(u.check_github({'version':'0.27.0','build':1}))
            with patch.object(u,'read_json',return_value=[dict(with_assets('windows-update.json','windows-update.json.sig'),draft=True)]):
                self.assertIsNone(u.check_github({'version':'0.27.0-dev.1','build':1}))

    def test_only_https_repository_official_hosts_and_the_windows_folder(self):
        self.assertTrue(u.allowed_url(u.API))
        for value in [u.ALIYUN+'dev/windows-update.json',u.ALIYUN+'AgentRemote-0.27.0-dev.24-Setup.exe',u.MIRROR+'AgentRemote-0.27.0-dev.24-Setup.exe']:
            self.assertTrue(u.allowed_url(value))
        for value in ['http://github.com/a','https://github.com/another/repo/releases/download/a','https://user:pass@release-assets.githubusercontent.com/a','https://release-assets.githubusercontent.com.evil.test/a','https://release-assets.githubusercontent.com:8000/a',
                      'https://teleply-updates.oss-cn-guangzhou.aliyuncs.com/android/android-update.json','https://other.oss-cn-guangzhou.aliyuncs.com/windows/a.exe','https://teleply-updates.oss-cn-guangzhou.aliyuncs.com.evil.test/windows/a.exe',
                      u.ALIYUN+'a.exe?x-oss-process=1',u.ALIYUN+'../android/a','http://teleply-updates.oss-cn-guangzhou.aliyuncs.com/windows/a.exe']:
            self.assertFalse(u.allowed_url(value),value)


if __name__=='__main__':
    unittest.main()
