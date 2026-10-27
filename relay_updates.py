"""Explicit Windows updates, Alibaba Cloud first and this repository's GitHub Releases second; no credentials or silent execution.

Both sources carry the same windows-update.json and windows-update.json.sig. deploy/updates/publish.py signs the
manifest with a key that stays on the publisher's computer; the app checks that signature before it reads anything,
then the installer's size and SHA-256. So neither source, nor whoever breaks into one, can swap the installer.
"""
import base64
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import struct
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

REPO='https://github.com/Zeng-HY/Agent_24-7/releases/download/'
API='https://api.github.com/repos/Zeng-HY/Agent_24-7/releases?per_page=30'
# Alibaba Cloud OSS, bucket teleply-updates in cn-guangzhou: <channel>/windows-update.json (.sig) and the installers.
ALIYUN='https://teleply-updates.oss-cn-guangzhou.aliyuncs.com/windows/'
# The same bucket under the ICP-filed domain, once it is bound; a signed manifest may name it.
MIRROR='https://dl.pocketagentdesk.com/windows/'
# Public half of the manifest signing key: ECDSA P-256, X.509 SubjectPublicKeyInfo. The Android app carries the same.
KEY='MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEjHQ+zWxB7EZkKiwzv6Xgkyu0RjbzWW0qtW1L4qNgVHAx4/r/Hk29tMlDlWUjer+q+L91XkMnOWhVwDgVCmlSew=='
# DER prefix of a P-256 SubjectPublicKeyInfo, up to the uncompressed point's 0x04.
P256=bytes.fromhex('3059301306072a8648ce3d020106082a8648ce3d03010703420004')
MAX_SIZE=200*1024*1024
# What a source that cannot answer raises: network and HTTP errors (a dropped body is an HTTPException), bad data.
FAILED=(OSError,ValueError,HTTPException)


def release_notes(data,release):
    """Use authored highlights; retain the full remote text without rendering HTML."""
    notes=str((release or {}).get('body') or data.get('notes') or '')
    summary=data.get('summary')
    if not summary:
        from app_paths import ASSETS
        path=ASSETS/'windows-release-notes.json'
        try:summary=json.loads(path.read_text(encoding='utf-8')).get(data['version'],{}).get('summary')
        except (OSError,ValueError,KeyError):summary=None
    if not isinstance(summary,list) or not 1<=len(summary)<=3 or any(not isinstance(line,str) or not line.strip() or len(line)>160 for line in summary):
        summary=['此版本未提供简版说明，请展开更新详情。']
    # New manifests carry plain-text details; GitHub may wrap the same content in <details>.
    if isinstance(data.get('notes'),str) and data['notes']:notes=data['notes']
    return summary,notes


def metadata():
    from app_paths import ASSETS
    path=ASSETS/'windows-build.json'
    if not path.exists():path=ASSETS/'windows-version.json'
    return json.loads(path.read_text(encoding='utf-8'))


def channel(current):
    """dev installs follow every release; stable installs only stable ones."""
    return 'dev' if '-dev.' in current['version'] else 'stable'


def allowed_url(url):
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443):return False
        if url.startswith((ALIYUN,MIRROR)):return '..' not in p.path and not p.query
        return url==API or (p.hostname=='github.com' and url.startswith(REPO) and '..' not in p.path) or p.hostname in ('release-assets.githubusercontent.com','objects.githubusercontent.com')
    except ValueError:return False


class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed_url(newurl):raise ValueError('更新下载地址不可信')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def open_url(url):
    if not allowed_url(url):raise ValueError('更新下载地址不可信')
    return build_opener(Redirects()).open(Request(url,headers={'User-Agent':'AgentRemote-Windows-Updater','Accept':'application/vnd.github+json, application/octet-stream'}),timeout=20)


def read_bytes(url,limit):
    with open_url(url) as response:
        raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('更新信息过大')
    return raw


def read_json(url,limit):
    return json.loads(read_bytes(url,limit))


def raw_signature(der):
    """r and s, 32 bytes each, as Windows wants them, from the DER form SEQUENCE { INTEGER r, INTEGER s }."""
    if len(der)<8 or der[0]!=0x30 or der[1]!=len(der)-2:raise ValueError('签名格式不正确')
    out=b'';i=2
    for _ in range(2):
        if i+2>len(der) or der[i]!=2 or not 1<=der[i+1]<=33 or i+2+der[i+1]>len(der):raise ValueError('签名格式不正确')
        value=der[i+2:i+2+der[i+1]].lstrip(b'\0');i+=2+der[i+1]
        if len(value)>32:raise ValueError('签名格式不正确')
        out+=value.rjust(32,b'\0')
    if i!=len(der):raise ValueError('签名格式不正确')
    return out


def windows_verify(point,digest,signature):
    """ECDSA P-256 check by Windows' own cryptography (CNG); point is the key's X and Y."""
    import ctypes
    if not hasattr(ctypes,'WinDLL'):raise OSError('需要 Windows 核对更新签名')
    bcrypt=ctypes.WinDLL('bcrypt');handle=ctypes.c_void_p;ulong=ctypes.c_ulong
    for name,args in (('BCryptOpenAlgorithmProvider',[ctypes.POINTER(handle),ctypes.c_wchar_p,ctypes.c_wchar_p,ulong]),
                      ('BCryptImportKeyPair',[handle,handle,ctypes.c_wchar_p,ctypes.POINTER(handle),ctypes.c_char_p,ulong,ulong]),
                      ('BCryptVerifySignature',[handle,handle,ctypes.c_char_p,ulong,ctypes.c_char_p,ulong,ulong]),
                      ('BCryptDestroyKey',[handle]),('BCryptCloseAlgorithmProvider',[handle,ulong])):
        function=getattr(bcrypt,name);function.argtypes=args;function.restype=ctypes.c_long
    algorithm=handle();key=handle()
    if bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm),'ECDSA_P256',None,0):raise OSError('无法核对更新签名')
    try:
        blob=struct.pack('<II',0x31534345,32)+point  # BCRYPT_ECCKEY_BLOB, magic ECS1 (P-256 public key)
        if bcrypt.BCryptImportKeyPair(algorithm,None,'ECCPUBLICBLOB',ctypes.byref(key),blob,len(blob),0):return False
        try:return bcrypt.BCryptVerifySignature(key,None,digest,len(digest),signature,len(signature),0)==0
        finally:bcrypt.BCryptDestroyKey(key)
    finally:bcrypt.BCryptCloseAlgorithmProvider(algorithm,0)


def verify_signature(data,signature,key=KEY):
    """The .sig is base64 of an ECDSA P-256 / SHA-256 signature (DER) over the manifest's exact bytes."""
    try:
        spki=base64.b64decode(key,validate=True);der=base64.b64decode(signature.strip(),validate=True)
        ok=len(spki)==91 and spki[:27]==P256 and windows_verify(spki[27:],hashlib.sha256(data).digest(),raw_signature(der))
    except (ValueError,OSError):ok=False
    if not ok:raise ValueError('更新签名不正确')


def signed_manifest(raw,signature):
    verify_signature(raw,signature.decode('ascii','replace') if isinstance(signature,bytes) else signature)
    return json.loads(raw)


def validate_manifest(data,release,current):
    """A signed manifest from Alibaba Cloud (release None) or from this GitHub release; None when it is not newer."""
    if not isinstance(data,dict) or data.get('schema')!=1:raise ValueError('更新清单格式不正确')
    if data.get('product')!='windows':raise ValueError('更新清单不是电脑端的')
    version=data.get('version','');build=data.get('build')
    if not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-dev\.\d+)?',version):raise ValueError('更新版本不正确')
    if data.get('channel')!=channel({'version':version}):raise ValueError('更新清单格式不正确')
    if data['channel']=='dev' and channel(current)=='stable':return None
    if type(build) is not int or build<=current['build']:return None
    if not re.fullmatch('[0-9a-f]{40}',data.get('commit','')):raise ValueError('更新提交不正确')
    name='AgentRemote-'+version+'-Setup.exe'
    if data.get('name')!=name or not re.fullmatch('[0-9a-f]{64}',data.get('sha256','')):raise ValueError('更新文件信息不正确')
    if type(data.get('size')) is not int or not 0<data['size']<=MAX_SIZE:raise ValueError('更新文件大小不正确')
    listed=data.get('urls') if isinstance(data.get('urls'),list) else []
    urls=[]
    if release is not None:
        asset=next((a for a in release.get('assets',[]) if a.get('name')==name),None)
        url=REPO+release['tag_name']+'/'+name
        if not asset or asset.get('browser_download_url')!=url or not allowed_url(url) or asset.get('size')!=data['size'] or asset.get('digest')!='sha256:'+data['sha256']:
            raise ValueError('更新文件与发布清单不一致')
        urls.append(url)
    # Addresses this build does not know (a later mirror) are skipped, not refused: the signature already vouches for them.
    urls+=[u for u in listed[:5] if isinstance(u,str) and u.endswith('/'+name) and allowed_url(u) and u not in urls]
    if not urls:raise ValueError('更新清单没有可用的下载地址')
    summary,notes=release_notes(data,release)
    return dict(data,urls=urls,notes=notes,summary=summary)


def check_aliyun(current):
    url=ALIYUN+channel(current)+'/windows-update.json'
    return validate_manifest(signed_manifest(read_bytes(url,16384),read_bytes(url+'.sig',1024)),None,current)


def check_github(current):
    best=None
    for release in read_json(API,4*1024*1024):
        if release.get('draft') or (release.get('prerelease') and channel(current)=='stable'):continue
        urls={a.get('browser_download_url') for a in release.get('assets',[])}
        url=REPO+release['tag_name']+'/windows-update.json'
        # Releases before dev.25 carry no signature; this build is newer than all of them anyway.
        if url not in urls or url+'.sig' not in urls:continue
        data=validate_manifest(signed_manifest(read_bytes(url,16384),read_bytes(url+'.sig',1024)),release,current)
        if data and (best is None or data['build']>best['build']):best=data
    return best


def check(current=None):
    """Alibaba Cloud's answer counts, "nothing newer" included; GitHub only when it cannot give one."""
    current=current or metadata()
    try:return check_aliyun(current)
    except FAILED:pass
    return check_github(current)


class Cancelled(Exception):pass


def transfer(stream,target,info,cancel,progress=lambda percent:None):
    digest=hashlib.sha256();size=0;last=-1
    with target.open('wb') as output:
        while True:
            if cancel.is_set():raise Cancelled()
            block=stream.read(65536)
            if not block:break
            size+=len(block)
            if size>info['size'] or size>MAX_SIZE:raise ValueError('下载文件过大')
            digest.update(block);output.write(block)
            percent=int(size*100/info['size'])
            if percent!=last:progress(percent);last=percent
        output.flush();os.fsync(output.fileno())
    if cancel.is_set():raise Cancelled()
    if size!=info['size'] or digest.hexdigest()!=info['sha256']:raise ValueError('安装包校验失败，请重新下载')


def download(info,folder,cancel,progress=lambda percent:None):
    """Each address in turn, the manifest's own source first; every one is checked the same way."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    target=folder/info['name'];partial=folder/(info['name']+'.part');error=None
    try:
        for url in info['urls']:
            try:
                with open_url(url) as response:transfer(response,partial,info,cancel,progress)
            except FAILED as exc:error=exc;continue
            partial.replace(target)
            return target
        raise error or ValueError('更新清单没有可用的下载地址')
    finally:
        partial.unlink(missing_ok=True)


def verify_file(path,info):
    if path.stat().st_size!=info['size']:raise ValueError('安装包已变化，请重新下载')
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest!=info['sha256']:raise ValueError('安装包已变化，请重新下载')
