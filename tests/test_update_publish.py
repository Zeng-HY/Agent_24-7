import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'deploy/updates'))
import relay_updates
import publish

try:import cryptography
except ImportError:cryptography=None


def good_only(data,signature,key=None):
    if signature.strip()!='good':raise ValueError('更新签名不正确')


class FakeOss:
    """Objects by key; records what was asked, in order."""
    def __init__(self,objects=None):self.objects=dict(objects or {});self.calls=[]

    def head(self,key):
        self.calls.append(('HEAD',key));body=self.objects.get(key)
        return None if body is None else (len(body),hashlib.md5(body).hexdigest())

    def put(self,key,body,content_type,cache,keep=False):
        self.calls.append(('PUT',key,keep));self.objects[key]=body

    def public(self,url,method='GET'):
        key=url[len(publish.ENDPOINT):]
        if key not in self.objects:raise HTTPError(url,404,'Not Found',{},io.BytesIO(b''))
        return self.objects[key] if method=='GET' else len(self.objects[key])


class Publish(unittest.TestCase):
    def test_oss_signature_matches_alibaba_clouds_own_sdk(self):
        # Computed with alibabacloud-oss-v2 1.4.1 (SignerV4) from these inputs.
        stamp='20261027T083005Z';key_id='LTAI5tTestKeyId00000000';secret='TestSecret0123456789abcdefghijk'
        put={'x-oss-date':stamp,'x-oss-content-sha256':'UNSIGNED-PAYLOAD','Content-Type':'application/json','Content-MD5':'ICy5YqxZB1uWSwcVLSNLcA==','Cache-Control':'no-cache','x-oss-forbid-overwrite':'true'}
        self.assertEqual(publish.authorization('PUT','windows/dev/windows-update.json',put,key_id,secret,stamp),
            'OSS4-HMAC-SHA256 Credential=LTAI5tTestKeyId00000000/20261027/cn-guangzhou/oss/aliyun_v4_request,Signature=89db3e6b2ec924f1e372687c0b516688ef327f478b67ccb056dfa4c3d51594af')
        head={'x-oss-date':stamp,'x-oss-content-sha256':'UNSIGNED-PAYLOAD'}
        self.assertEqual(publish.authorization('HEAD','android/Teleply-1.0.3-14.apk',head,key_id,secret,stamp),
            'OSS4-HMAC-SHA256 Credential=LTAI5tTestKeyId00000000/20261027/cn-guangzhou/oss/aliyun_v4_request,Signature=aaf77c47be91f4f9a77970b6bfe894a2561ad870b2e100838d0e28b48fead1d7')

    def test_requests_go_to_the_bucket_signed(self):
        sent=[]
        class Answer(io.BytesIO):
            headers={'Content-Length':'9','ETag':'"ABC"'}
        def opener(request,timeout):sent.append(request);return Answer(b'')
        oss=publish.Oss('id','secret',opener)
        oss.put('windows/AgentRemote-0.27.0-dev.24-Setup.exe',b'installer','application/octet-stream',publish.IMMUTABLE,keep=True)
        self.assertEqual(oss.head('windows/dev/windows-update.json'),(9,'abc'))
        put,head=sent
        self.assertEqual((put.get_method(),put.full_url),('PUT',publish.ENDPOINT+'windows/AgentRemote-0.27.0-dev.24-Setup.exe'))
        self.assertEqual(put.get_header('X-oss-forbid-overwrite'),'true');self.assertTrue(put.get_header('Authorization').startswith('OSS4-HMAC-SHA256 Credential=id/'))
        self.assertEqual(put.get_header('Content-md5'),'lzhCYbi7+WbfFuWtUJki2w==')
        self.assertEqual(head.get_method(),'HEAD');self.assertIsNone(head.data)

    def test_addresses_and_key_agree_with_the_apps(self):
        self.assertEqual(publish.ENDPOINT+'windows/',relay_updates.ALIYUN)
        self.assertEqual(publish.ENDPOINT+'android/',publish.kotlin_constant('Aliyun'))
        self.assertEqual(publish.ANDROID_MIRROR,publish.kotlin_constant('Mirror'))
        self.assertEqual(publish.kotlin_constant('Key'),relay_updates.KEY)

    def test_android_manifest_names_the_apk_and_its_release(self):
        with tempfile.TemporaryDirectory() as temp:
            apk=Path(temp)/'Teleply-1.0.3-14.apk';apk.write_bytes(b'apk');notes=Path(temp)/'notes.txt';notes.write_text('﻿说明\n',encoding='utf-8')
            raw,info,tag=publish.android_files(apk,notes)
            self.assertEqual(tag,'android-v1.0.3');self.assertEqual(json.loads(raw),info)
            self.assertEqual((info['product'],info['package'],info['version'],info['code'],info['size'],info['notes']),('android','com.pocketagentdesk.teleply','1.0.3',14,3,'说明'))
            self.assertEqual(info['sha256'],hashlib.sha256(b'apk').hexdigest())
            self.assertEqual(info['urls'],[relay_updates.REPO+'android-v1.0.3/Teleply-1.0.3-14.apk'])
            with patch.object(publish,'ANDROID_FROM_ALIYUN',True):
                self.assertEqual(publish.android_files(apk,notes)[1]['urls'][0],publish.ANDROID_MIRROR+apk.name)
            for name in ('TeleplyNative-1.0.3-14.apk','Teleply-1.0.3.apk'):
                other=Path(temp)/name;other.write_bytes(b'apk')
                with self.assertRaises(SystemExit):publish.android_files(other,notes)
            notes.write_text('长'*4001,encoding='utf-8')
            with self.assertRaises(SystemExit):publish.android_files(apk,notes)

    def windows_dist(self,temp,**change):
        dist=Path(temp);version='0.27.0-dev.24';name='AgentRemote-'+version+'-Setup.exe';data=b'installer'
        (dist/name).write_bytes(data)
        info=dict(version=version,build=24,commit='a'*40,schema=1,name=name,size=len(data),sha256=hashlib.sha256(data).hexdigest(),summary=['说明'],notes='详细',
                  product='windows',channel='dev',urls=[relay_updates.ALIYUN+name,relay_updates.REPO+'windows-v'+version+'/'+name])
        info.update(change)
        (dist/'windows-update.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
        return dist,info

    def test_windows_manifest_must_match_its_installer_and_offer_alibaba_cloud_first(self):
        with tempfile.TemporaryDirectory() as temp:
            dist,info=self.windows_dist(temp)
            raw,parsed,installer=publish.windows_files(dist)
            self.assertEqual(raw,(dist/'windows-update.json').read_bytes());self.assertEqual(installer.name,info['name'])
            (dist/info['name']).write_bytes(b'other')
            with self.assertRaises(SystemExit):publish.windows_files(dist)
        for change in ({'urls':[relay_updates.REPO+'windows-v0.27.0-dev.24/AgentRemote-0.27.0-dev.24-Setup.exe']},{'product':None},{'channel':'stable'}):
            with tempfile.TemporaryDirectory() as temp,self.assertRaises(SystemExit):publish.windows_files(self.windows_dist(temp,**change)[0])

    def upload(self,oss,force=False,body=b'installer',number=24,sha=None):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'AgentRemote-0.27.0-dev.24-Setup.exe';path.write_bytes(body)
            raw=json.dumps({'build':number,'sha256':sha or hashlib.sha256(body).hexdigest()}).encode()
            with patch.object(publish,'public',oss.public),patch.object(relay_updates,'verify_signature',good_only),patch('sys.stdout',io.StringIO()):
                publish.upload(oss,'windows/'+path.name,path,'application/octet-stream',[('windows/dev/windows-update.json',raw,b'good\n')],number,force)

    def test_upload_puts_the_file_before_its_manifest_and_never_swaps_a_published_file(self):
        oss=FakeOss();self.upload(oss)
        installer='windows/AgentRemote-0.27.0-dev.24-Setup.exe';manifest='windows/dev/windows-update.json'
        self.assertEqual(oss.calls,[('HEAD',installer),('PUT',installer,True),('PUT',manifest+'.sig',False),('PUT',manifest,False)])
        oss.calls.clear();self.upload(oss)
        self.assertEqual(oss.calls,[('HEAD',installer),('PUT',manifest+'.sig',False),('PUT',manifest,False)])
        oss.calls.clear()
        with self.assertRaises(SystemExit):self.upload(oss,body=b'another installer')
        self.assertFalse([c for c in oss.calls if c[0]=='PUT'])

    def test_upload_never_puts_an_older_release_over_a_newer_one(self):
        manifest='windows/dev/windows-update.json'
        newer=FakeOss({manifest:json.dumps({'build':25,'sha256':'b'*64}).encode(),manifest+'.sig':b'good'})
        with self.assertRaises(SystemExit):self.upload(newer)
        self.assertEqual(newer.calls,[])
        self.upload(newer,force=True);self.assertEqual(json.loads(newer.objects[manifest])['build'],24)
        other=FakeOss({manifest:json.dumps({'build':24,'sha256':'b'*64}).encode(),manifest+'.sig':b'good'})
        with self.assertRaises(SystemExit):self.upload(other)
        forged=FakeOss({manifest:json.dumps({'build':1}).encode(),manifest+'.sig':b'forged'})
        with self.assertRaises(SystemExit):self.upload(forged)

    def test_android_goes_to_github_only_until_the_domain_is_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            apk=Path(temp)/'Teleply-1.0.3-14.apk';apk.write_bytes(b'apk');notes=Path(temp)/'notes.txt';notes.write_text('说明',encoding='utf-8')
            with patch.object(publish,'signing_key',return_value=None),patch.object(publish,'sign',return_value=b'good\n'),\
                 patch.object(publish,'check_apk_certificate'),patch.object(publish,'credentials',side_effect=AssertionError('AccessKey asked')),\
                 patch.object(publish,'upload',side_effect=AssertionError('uploaded')),patch('sys.stdout',io.StringIO()) as out:
                publish.main(['android',str(apk),'--notes-file',str(notes)])
            self.assertEqual((Path(temp)/'android-update.json.sig').read_bytes(),b'good\n')
            self.assertEqual(json.loads((Path(temp)/'android-update.json').read_bytes())['code'],14)
            self.assertIn('只发 GitHub',out.getvalue())

    def test_access_key_comes_only_from_the_private_file(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            with self.assertRaises(SystemExit) as stop:publish.credentials(folder)
            self.assertIn(publish.ACCESS_FILE,str(stop.exception));self.assertTrue((folder/'说明.txt').exists())
            (folder/publish.ACCESS_FILE).write_text('﻿'+json.dumps({'access_key_id':' LTAI-test ','access_key_secret':'s3cret'}),encoding='utf-8')
            self.assertEqual(publish.credentials(folder),('LTAI-test','s3cret'))

    @unittest.skipUnless(cryptography,'needs requirements-release.txt')
    def test_new_key_signs_what_the_windows_app_accepts_and_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'keys'
            with patch('sys.stdout',io.StringIO()):publish.new_key(folder)
            public=(folder/publish.PUBLIC_FILE).read_text(encoding='ascii').strip()
            self.assertTrue((folder/publish.ACCESS_FILE).exists())
            with self.assertRaises(SystemExit):publish.new_key(folder)
            with self.assertRaises(SystemExit):publish.signing_key(folder)
            with patch.object(relay_updates,'KEY',public),patch.object(publish,'kotlin_constant',return_value=public):
                signature=publish.sign(publish.signing_key(folder),b'{"manifest": 1}').decode('ascii')
            self.assertTrue(signature.endswith('\n'))
            relay_updates.verify_signature(b'{"manifest": 1}',signature,public)
            with self.assertRaises(ValueError):relay_updates.verify_signature(b'{"manifest": 2}',signature,public)


if __name__=='__main__':
    unittest.main()
