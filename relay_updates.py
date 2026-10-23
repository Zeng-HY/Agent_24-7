"""Explicit Windows updates from this repository; no credentials or silent execution."""
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

REPO='https://github.com/Zeng-HY/Agent_24-7/releases/download/'
API='https://api.github.com/repos/Zeng-HY/Agent_24-7/releases?per_page=30'
MAX_SIZE=200*1024*1024


def release_notes(data,release):
    """Use authored highlights; retain the full remote text without rendering HTML."""
    notes=str(release.get('body') or data.get('notes') or '')
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


def allowed_url(url):
    try:
        p=urlsplit(url)
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443):return False
        return url==API or (p.hostname=='github.com' and url.startswith(REPO) and '..' not in p.path) or p.hostname in ('release-assets.githubusercontent.com','objects.githubusercontent.com')
    except ValueError:return False


class Redirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not allowed_url(newurl):raise ValueError('更新下载地址不可信')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def open_url(url):
    if not allowed_url(url):raise ValueError('更新下载地址不可信')
    return build_opener(Redirects()).open(Request(url,headers={'User-Agent':'AgentRemote-Windows-Updater','Accept':'application/vnd.github+json, application/octet-stream'}),timeout=20)


def read_json(url,limit):
    with open_url(url) as response:
        raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('更新信息过大')
    return json.loads(raw)


def validate_manifest(data,release,current):
    if not isinstance(data,dict) or data.get('schema')!=1:raise ValueError('更新清单格式不正确')
    version=data.get('version','');build=data.get('build')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-dev\.\d+)?',version):raise ValueError('更新版本不正确')
    if type(build) is not int or build<=current['build']:return None
    if not re.fullmatch('[0-9a-f]{40}',data.get('commit','')):raise ValueError('更新提交不正确')
    name='AgentRemote-'+version+'-Setup.exe'
    if data.get('name')!=name or not re.fullmatch('[0-9a-f]{64}',data.get('sha256','')):raise ValueError('更新文件信息不正确')
    if type(data.get('size')) is not int or not 0<data['size']<=MAX_SIZE:raise ValueError('更新文件大小不正确')
    asset=next((a for a in release.get('assets',[]) if a.get('name')==name),None)
    url=REPO+release['tag_name']+'/'+name
    if not asset or asset.get('browser_download_url')!=url or not allowed_url(url) or asset.get('size')!=data['size'] or asset.get('digest')!='sha256:'+data['sha256']:
        raise ValueError('更新文件与发布清单不一致')
    summary,notes=release_notes(data,release)
    return dict(data,url=url,notes=notes,summary=summary)


def check(current=None):
    current=current or metadata();best=None
    for release in read_json(API,4*1024*1024):
        if release.get('draft') or (release.get('prerelease') and '-dev.' not in current['version']):continue
        asset=next((a for a in release.get('assets',[]) if a.get('name')=='windows-update.json'),None)
        if not asset:continue
        url=REPO+release['tag_name']+'/windows-update.json'
        if asset.get('browser_download_url')!=url:continue
        data=validate_manifest(read_json(url,16384),release,current)
        if data and (best is None or data['build']>best['build']):best=data
    return best


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
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    target=folder/info['name'];partial=folder/(info['name']+'.part')
    try:
        with open_url(info['url']) as response:transfer(response,partial,info,cancel,progress)
        partial.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


def verify_file(path,info):
    if path.stat().st_size!=info['size']:raise ValueError('安装包已变化，请重新下载')
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest!=info['sha256']:raise ValueError('安装包已变化，请重新下载')
