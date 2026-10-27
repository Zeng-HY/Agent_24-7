"""Publishes a Windows or Android update: signs its manifest, uploads it to Alibaba Cloud OSS, lays out the GitHub files.

  new-key                        once: the manifest signing key, in the private folder below
  windows                        after deploy/windows/build.ps1 (dist/AgentRemote-<v>-Setup.exe, dist/windows-update.json)
  android APK --notes-file TXT   after apps/android/scripts/release.ps1 (apps/android/build/Teleply-<v>-<code>.apk)

The apps ask Alibaba Cloud first and GitHub second (relay_updates.py, apps/android/.../Updates.kt); they check this
signature, then the file's size and SHA-256. The signing key and the upload AccessKey stay in the publisher's own
folder, %USERPROFILE%\\.teleply-updates (or TELEPLY_UPDATES_DIR): never in the repository, a command line or a chat.
Run with .toolchain\\release-venv\\Scripts\\python.exe (requirements-release.txt). See deploy/updates/README.md.
"""
import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import relay_updates

BUCKET='teleply-updates';REGION='cn-guangzhou'
ENDPOINT='https://'+BUCKET+'.oss-'+REGION+'.aliyuncs.com/'
PACKAGE='com.pocketagentdesk.teleply'
KOTLIN=ROOT/'apps/android/app/src/main/java/com/pocketagentdesk/teleply/Updates.kt'
# The certificate of the app's own release key (apps/android/scripts/release.ps1); phones refuse an APK with another.
APK_CERT='1df09ab72fd7e3e1c9f57569d2050ae1db933148d1d5fbb7517a28edb2e22946'
MAX_APK=128*1024*1024
# Alibaba Cloud refuses APK downloads over the bucket's own address. Once dl.pocketagentdesk.com (ICP-filed) is bound
# to the bucket with HTTPS, set this to True: new manifests then offer the APK from Alibaba Cloud first.
ANDROID_FROM_ALIYUN=False
ANDROID_MIRROR='https://dl.pocketagentdesk.com/android/'
KEY_FILE='update-signing-key.pem';PUBLIC_FILE='update-signing-key.pub.txt';ACCESS_FILE='oss-upload-key.json'
IMMUTABLE='public, max-age=31536000, immutable'
NOTE='''这个文件夹放遥应发更新用的两把钥匙，只在这台电脑上。

update-signing-key.pem：给更新清单签名的私钥。电脑端和安卓应用里写着它的公钥，只认它签过的更新。
- 另外拷一份到 U 盘这类不联网的地方。丢了以后新发的更新所有应用都不认，只能让每个人手动重装一次。
- 不要发给任何人，不要放进仓库、网盘或聊天。别人拿到它，就能签出应用会认的更新。
- 不要重新生成。publish.py new-key 只在第一次用；这个文件已经在时它会拒绝。

oss-upload-key.json：阿里云 RAM 用户的 AccessKey，只能在 teleply-updates 存储空间的 windows/ 和 android/ 里上传和查看文件。
- 用记事本打开，把 AccessKey ID 和 AccessKey Secret 分别填进两对引号里，保存。
- 丢了或者泄露了：在阿里云 RAM 控制台禁用它，再建一个填进来，应用不受影响。

update-signing-key.pub.txt：公钥，可以公开，和应用里写的一样。

用法见仓库里的 deploy/updates/README.md。
'''


def home():
    return Path(os.environ.get('TELEPLY_UPDATES_DIR') or Path.home()/'.teleply-updates')


def crypto():
    try:
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        raise SystemExit('缺少 cryptography。先在仓库目录运行：\n  python -m venv .toolchain\\release-venv\n'
                         '  .toolchain\\release-venv\\Scripts\\python.exe -m pip install -r requirements-release.txt\n'
                         '再用 .toolchain\\release-venv\\Scripts\\python.exe 运行本脚本。')
    return hashes,serialization,ec


def public_text(key):
    _,serialization,_=crypto()
    return base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).decode('ascii')


def kotlin_constant(name):
    match=re.search(r'const val '+name+r' = "([^"]*)"',KOTLIN.read_text(encoding='utf-8'))
    return match.group(1) if match else None


def prepare(folder):
    """The note and an empty AccessKey file; what is already there stays."""
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'说明.txt').write_text(NOTE,encoding='utf-8')
    access=folder/ACCESS_FILE
    if not access.exists():access.write_text(json.dumps({'access_key_id':'','access_key_secret':''},indent=2)+'\n',encoding='utf-8')


def new_key(folder):
    _,serialization,ec=crypto()
    path=folder/KEY_FILE
    if path.exists():raise SystemExit('签名钥匙已经在了，不会覆盖：'+str(path))
    prepare(folder)
    key=ec.generate_private_key(ec.SECP256R1())
    with path.open('xb') as f:f.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    public=public_text(key)
    (folder/PUBLIC_FILE).write_text(public+'\n',encoding='ascii')
    print('签名钥匙已生成：'+str(path))
    print('公钥，写进 relay_updates.py 的 KEY 和 Updates.kt 的 Key：')
    print(public)
    print('请把 '+str(folder)+' 整个另外拷一份到不联网的地方。')


def signing_key(folder):
    _,serialization,ec=crypto()
    path=folder/KEY_FILE
    if not path.exists():raise SystemExit('找不到签名钥匙 '+str(path)+'。换了电脑就从离线备份拷回整个文件夹；只有第一次才运行 new-key。')
    key=serialization.load_pem_private_key(path.read_bytes(),password=None)
    if not isinstance(key,ec.EllipticCurvePrivateKey) or key.curve.name!='secp256r1':raise SystemExit('签名钥匙不是 P-256：'+str(path))
    public=public_text(key)
    if public!=relay_updates.KEY or public!=kotlin_constant('Key'):
        raise SystemExit('签名钥匙和应用里写的公钥对不上（relay_updates.py 的 KEY、Updates.kt 的 Key），不签。')
    return key


def sign(key,data):
    """base64 of the DER signature plus a newline; checked with the Windows app's own code before anything leaves."""
    hashes,_,ec=crypto()
    signature=(base64.b64encode(key.sign(data,ec.ECDSA(hashes.SHA256()))).decode('ascii')+'\n').encode('ascii')
    relay_updates.verify_signature(data,signature.decode('ascii'),relay_updates.KEY)
    return signature


def file_sha256(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def windows_files(dist):
    """dist/windows-update.json as build.ps1 wrote it, checked against the installer beside it."""
    manifest=dist/'windows-update.json'
    if not manifest.is_file():raise SystemExit('找不到 '+str(manifest)+'，先运行 deploy/windows/build.ps1。')
    raw=manifest.read_bytes();info=json.loads(raw)
    installer=dist/str(info.get('name',''))
    if not installer.is_file():raise SystemExit('找不到安装包 '+str(installer)+'，先运行 deploy/windows/build.ps1。')
    if info.get('size')!=installer.stat().st_size or info.get('sha256')!=file_sha256(installer):raise SystemExit('windows-update.json 和安装包对不上，重新运行 build.ps1。')
    try:data=relay_updates.validate_manifest(info,None,{'version':'0.0.0-dev.0','build':0})
    except ValueError as exc:raise SystemExit('windows-update.json 不对：'+str(exc)+'。用这一版的 build.ps1 重新打包。')
    if data['urls'][0]!=relay_updates.ALIYUN+installer.name:raise SystemExit('windows-update.json 的第一个下载地址不是阿里云，用这一版的 build.ps1 重新打包。')
    return raw,info,installer


def android_files(apk,notes_file):
    """android-update.json for a release APK; the GitHub Release is android-v<version>, as before."""
    match=re.fullmatch(r'Teleply-(\d+\.\d+\.\d+)-(\d+)\.apk',apk.name)
    if not match or not apk.is_file():raise SystemExit('要发的是 release.ps1 打出的 Teleply-版本-版本号.apk：'+str(apk))
    if not 0<apk.stat().st_size<=MAX_APK:raise SystemExit('APK 大小不对：'+str(apk))
    notes=Path(notes_file).read_text(encoding='utf-8-sig').strip()
    if len(notes)>4000:raise SystemExit('更新说明太长，最多 4000 字；手机上只显示前 500 字。')
    version,code=match.group(1),int(match.group(2));tag='android-v'+version
    urls=([ANDROID_MIRROR+apk.name] if ANDROID_FROM_ALIYUN else [])+[relay_updates.REPO+tag+'/'+apk.name]
    info=dict(schema=1,product='android',package=PACKAGE,version=version,code=code,name=apk.name,size=apk.stat().st_size,sha256=file_sha256(apk),notes=notes,urls=urls)
    return (json.dumps(info,ensure_ascii=False,indent=2)+'\n').encode('utf-8'),info,tag


def check_apk_certificate(apk):
    """release.ps1 checked it already; this catches a wrong file before phones download it. Skipped without the SDK."""
    sdk=Path(os.environ.get('ANDROID_HOME') or ROOT/'mobile/.toolchain/sdk')
    tools=sorted((sdk/'build-tools').glob('*/apksigner.bat'))
    if not tools:print('提醒：没找到 apksigner，这次没核对 APK 的签名证书（release.ps1 打包时核对过）。');return
    env=dict(os.environ)
    if not env.get('JAVA_HOME'):
        java=sorted((ROOT/'mobile/.toolchain/jdk').glob('*/bin/java.exe'))
        if java:env['JAVA_HOME']=str(java[-1].parents[1])
    result=subprocess.run([str(tools[-1]),'verify','--print-certs',str(apk)],capture_output=True,text=True,env=env)
    if result.returncode:raise SystemExit('APK 签名核对没通过：\n'+result.stdout[-600:]+result.stderr[-600:])
    if 'certificate SHA-256 digest: '+APK_CERT not in result.stdout:raise SystemExit('这个 APK 不是用遥应自己的钥匙签的，手机装不上，不发。')


def authorization(method,key,headers,key_id,secret,stamp):
    """Alibaba Cloud's V4 header signature (OSS4-HMAC-SHA256), as its own Python SDK computes it."""
    day=stamp[:8];scope=day+'/'+REGION+'/oss/aliyun_v4_request'
    signed=sorted((k.lower(),str(v).strip()) for k,v in headers.items() if k.lower().startswith('x-oss-') or k.lower() in ('content-type','content-md5'))
    canonical='\n'.join([method,quote('/'+BUCKET+'/'+key,safe='/'),'',''.join(k+':'+v+'\n' for k,v in signed),'','UNSIGNED-PAYLOAD'])
    text='\n'.join(['OSS4-HMAC-SHA256',stamp,scope,hashlib.sha256(canonical.encode('utf-8')).hexdigest()])
    signing=('aliyun_v4'+secret).encode('utf-8')
    for part in (day,REGION,'oss','aliyun_v4_request'):signing=hmac.new(signing,part.encode('utf-8'),hashlib.sha256).digest()
    return 'OSS4-HMAC-SHA256 Credential='+key_id+'/'+scope+',Signature='+hmac.new(signing,text.encode('utf-8'),hashlib.sha256).hexdigest()


def oss_error(exc):
    try:body=exc.read().decode('utf-8','replace')
    except OSError:body=''
    code=re.search(r'<Code>(.*?)</Code>',body);message=re.search(r'<Message>(.*?)</Message>',body)
    return 'HTTP '+str(exc.code)+(' '+code.group(1) if code else '')+(': '+message.group(1) if message else '')


class Oss:
    """HeadObject and PutObject with the upload AccessKey."""
    def __init__(self,key_id,secret,opener=urlopen):
        self.key_id=key_id;self.secret=secret;self.opener=opener

    def send(self,method,key,body=None,headers=None):
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        headers={'x-oss-date':stamp,'x-oss-content-sha256':'UNSIGNED-PAYLOAD',**(headers or {})}
        headers['Authorization']=authorization(method,key,headers,self.key_id,self.secret,stamp)
        return self.opener(Request(ENDPOINT+quote(key,safe='/'),data=body,method=method,headers=headers),timeout=120)

    def head(self,key):
        """(size, MD5 hex) of an object, or None when there is none."""
        try:
            with self.send('HEAD',key) as r:return int(r.headers['Content-Length']),r.headers.get('ETag','').strip('"').lower()
        except HTTPError as exc:
            if exc.code==404:return None
            raise SystemExit('阿里云查文件没成功（'+key+'）：'+oss_error(exc))

    def put(self,key,body,content_type,cache,keep=False):
        headers={'Content-Type':content_type,'Content-MD5':base64.b64encode(hashlib.md5(body).digest()).decode('ascii'),'Cache-Control':cache}
        if keep:headers['x-oss-forbid-overwrite']='true'
        try:
            with self.send('PUT',key,body,headers) as r:r.read()
        except HTTPError as exc:raise SystemExit('上传阿里云没成功（'+key+'）：'+oss_error(exc))


def public(url,method='GET'):
    """What anyone gets from the address, as the apps do: the bytes, or the size for HEAD."""
    with urlopen(Request(url,method=method,headers={'Cache-Control':'no-cache','User-Agent':'Teleply-Publish'}),timeout=60) as r:
        return r.read() if method=='GET' else int(r.headers['Content-Length'])


def published(key):
    """The manifest there now as (build or code, sha256), or None; one that does not check out stops the publish."""
    try:raw=public(ENDPOINT+key)
    except HTTPError as exc:
        if exc.code==404:return None
        raise SystemExit('别人下载不了阿里云上的文件（'+oss_error(exc)+'）。看存储空间的读写权限是不是「公共读」，「阻止公共访问」关了没有。')
    try:
        relay_updates.verify_signature(raw,public(ENDPOINT+key+'.sig').decode('ascii','replace'),relay_updates.KEY)
        info=json.loads(raw);number=info.get('build',info.get('code'))
        if type(number) is not int:raise ValueError('number')
    except (OSError,ValueError):raise SystemExit('阿里云上现有的 '+key+' 核对不过。查清楚原因；确定要覆盖就加 --force。')
    return number,info.get('sha256')


def upload(oss,file_key,path,content_type,manifests,number,force,check_file=True):
    """The file first, then each manifest's .sig and the manifest; then fetched back the way the apps fetch them."""
    sha=file_sha256(path)
    for key,_,_ in manifests:
        there=None if force else published(key)
        if there and (there[0]>number or there[0]==number and there[1]!=sha):
            raise SystemExit('阿里云上的 '+key+' 是 '+str(there[0])+'，比这次（'+str(number)+'）新或者是另一个文件，不覆盖。确定要覆盖就加 --force。')
    body=path.read_bytes();there=oss.head(file_key)
    if there is None:
        oss.put(file_key,body,content_type,IMMUTABLE,keep=True);print('已上传 '+file_key)
    elif there!=(len(body),hashlib.md5(body).hexdigest()):
        raise SystemExit('阿里云上已有同名但内容不同的 '+file_key+'。同一个版本不能换文件，升版本号重新打包。')
    else:print('阿里云上已有 '+file_key+'，内容一样，不重传。')
    for key,raw,signature in manifests:
        oss.put(key+'.sig',signature,'text/plain; charset=utf-8','no-cache')
        oss.put(key,raw,'application/json; charset=utf-8','no-cache');print('已上传 '+key+' 和签名')
    for key,raw,signature in manifests:
        if public(ENDPOINT+key)!=raw or public(ENDPOINT+key+'.sig')!=signature:raise SystemExit('从阿里云取回的 '+key+' 和刚传的不一样，再运行一次。')
    if check_file and public(ENDPOINT+file_key,'HEAD')!=len(body):raise SystemExit('从阿里云取回的 '+file_key+' 大小不对，再运行一次。')


def credentials(folder):
    prepare(folder);path=folder/ACCESS_FILE
    try:data=json.loads(path.read_text(encoding='utf-8-sig'))
    except ValueError:raise SystemExit(str(path)+' 格式坏了。删掉它，再运行一次会生成一个空的。')
    key_id=str(data.get('access_key_id','')).strip();secret=str(data.get('access_key_secret','')).strip()
    if not key_id or not secret:
        raise SystemExit('先用记事本打开 '+str(path)+'，填上阿里云 RAM 用户的 AccessKey ID 和 AccessKey Secret。只填在这个文件里，不要发到聊天。')
    return key_id,secret


def github_note(tag,files):
    print('GitHub：在 Release '+tag+' 附上这几个文件，文件名不改：')
    for path in files:print('  '+str(path))


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(errors='replace')
    parser=argparse.ArgumentParser(description='签名并发布遥应的更新（阿里云优先，GitHub 其次）。')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('new-key',help='第一次用：生成更新清单的签名钥匙')
    windows=commands.add_parser('windows',help='发电脑端：dist 里 build.ps1 打出的安装包和 windows-update.json')
    windows.add_argument('--dist',default=str(ROOT/'dist'))
    android=commands.add_parser('android',help='发安卓：release.ps1 打出的 APK')
    android.add_argument('apk')
    android.add_argument('--notes-file',required=True,help='更新说明，UTF-8 文本；和 GitHub Release 的说明用同一份')
    for command in (windows,android):
        command.add_argument('--sign-only',action='store_true',help='只签名、写出给 GitHub 的文件，不上传阿里云')
        command.add_argument('--force',action='store_true',help='阿里云上现有的清单更新或核对不过时也覆盖')
    args=parser.parse_args(argv)
    folder=home()
    if args.command=='new-key':return new_key(folder)
    key=signing_key(folder)
    # Until the APK can be downloaded from Alibaba Cloud, an Android manifest there would offer phones in mainland China
    # an update they cannot fetch; so Android goes to GitHub only, as before.
    if args.command=='android' and not ANDROID_FROM_ALIYUN and not args.sign_only:
        print('dl.pocketagentdesk.com 还没绑好（ANDROID_FROM_ALIYUN 是 False），安卓这次只签名、只发 GitHub。');args.sign_only=True
    oss=None if args.sign_only else Oss(*credentials(folder))
    if args.command=='windows':
        dist=Path(args.dist);raw,info,installer=windows_files(dist)
        signature=sign(key,raw);(dist/'windows-update.json.sig').write_bytes(signature)
        channels=['dev']+(['stable'] if info['channel']=='stable' else [])
        if oss:
            upload(oss,'windows/'+installer.name,installer,'application/octet-stream',[('windows/'+c+'/windows-update.json',raw,signature) for c in channels],info['build'],args.force)
            print('阿里云直接下载（连不上 GitHub 的人手动装这一个）：'+relay_updates.ALIYUN+installer.name)
        github_note('windows-v'+info['version'],[installer,dist/'windows-update.json',dist/'windows-update.json.sig'])
    else:
        apk=Path(args.apk);raw,info,tag=android_files(apk,args.notes_file)
        check_apk_certificate(apk)
        signature=sign(key,raw)
        manifest=apk.parent/'android-update.json';manifest.write_bytes(raw);(apk.parent/'android-update.json.sig').write_bytes(signature)
        if oss:
            # The bucket's own address answers APK downloads with ApkDownloadForbidden; the bound domain serves them.
            upload(oss,'android/'+apk.name,apk,'application/vnd.android.package-archive',[('android/android-update.json',raw,signature)],info['code'],args.force,check_file=False)
            if public(ANDROID_MIRROR+apk.name,'HEAD')!=info['size']:raise SystemExit('从 '+ANDROID_MIRROR+' 取回的 APK 大小不对，看域名和 HTTPS 证书绑好了没有。')
            print('阿里云直接下载：'+ANDROID_MIRROR+apk.name)
        github_note(tag,[apk,manifest,apk.parent/'android-update.json.sig'])


if __name__=='__main__':
    main()
