"""0.27 loopback cloud service behind trusted Caddy. No access/body logging."""
import argparse
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qsl, urlencode
from aiohttp import web, ClientSession, ClientTimeout, ClientError

from relay_accounts import TTL, digest
from relay_identity import Identity, Limited
from relay_mail import Mailer
from relay_transport import TunnelHub, MAX_BODY, REQUEST_HEADERS, RESPONSE_HEADERS
from relay_pages import scoped_page

COOKIE='__Host-ar_account'
HERE=Path(__file__).resolve().parent


def bearer(request):
    value=request.headers.get('Authorization','')
    return value[7:] if value.startswith('Bearer ') else ''


def clean_target(value):
    p=urlsplit(value)
    if not value.startswith('/') or value.startswith('//') or p.netloc or p.scheme or '\\' in value or '\r' in value or '\n' in value:
        raise ValueError('无效请求地址')
    query=urlencode([(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k!='t'])
    return p.path+('?' +query if query else '')


REASONS={400:'请求无效',401:'请先登录',403:'没有权限',404:'找不到',405:'请求无效',413:'请求过大',421:'请求无效',429:'太频繁了，稍后再试',502:'电脑连接中断，请重试',503:'暂时不可用'}

class Service:
    def __init__(self, origin, store, mailer=None, trusted_proxy=False):
        p=urlsplit(origin)
        if p.scheme!='https' or not p.netloc or p.path or p.username or p.query or p.fragment:
            raise ValueError('HTTPS origin required')
        self.origin,self.authority=origin,p.netloc
        self.store=store
        self.mailer=mailer or Mailer(origin)
        self.hub=TunnelHub(store)
        self.trusted_proxy=trusted_proxy
        self.kdf=asyncio.Semaphore(2);self.kdf_ip={}  # source address -> [lock, requests holding or awaiting it]
        self.legacy_counts={}
        self.app=web.Application(client_max_size=MAX_BODY,middlewares=[self.guard])
        self.app.router.add_get('/tunnel/connect',self.hub.control)
        self.app.router.add_get('/tunnel/stream/{stream:[0-9a-f]{32}}',self.hub.stream)
        self.app.router.add_route('*','/{tail:.*}',self.route)
        self.app.on_cleanup.append(self.close)

    async def close(self,app):
        for ident in list(self.hub.connections): await self.hub.disconnect(ident)

    @web.middleware
    async def guard(self, request, handler):
        try:
            if request.headers.getall('Host',[]) != [self.authority]: raise web.HTTPMisdirectedRequest()
            origin=request.headers.get('Origin')
            if origin is not None and origin!=self.origin: raise web.HTTPForbidden()
            if request.headers.get('Sec-Fetch-Site')=='cross-site': raise web.HTTPForbidden()
            if request.method=='POST' and origin!=self.origin: raise web.HTTPForbidden()
            if request.method not in ('GET','HEAD','POST'): raise web.HTTPMethodNotAllowed(request.method,['GET','HEAD','POST'])
            if request.method!='POST' and (request.content_length or request.headers.get('Transfer-Encoding')):raise web.HTTPBadRequest()
            if request.content_length is not None and request.content_length>MAX_BODY: raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY,actual_size=request.content_length)
            response=await handler(request)
            if not response.prepared:
                response.headers.setdefault('Cache-Control','no-store')
                response.headers.setdefault('Referrer-Policy','no-referrer')
                response.headers.setdefault('X-Content-Type-Options','nosniff')
            return response
        except Limited as exc:
            return web.json_response({'error':str(exc),'retry_after':exc.seconds},status=429,headers={'Retry-After':str(exc.seconds),'Cache-Control':'no-store'})
        except ValueError as exc:
            return web.json_response({'error':str(exc)},status=400,headers={'Cache-Control':'no-store'})
        except (ClientError,TimeoutError,ConnectionError):
            return web.json_response({'error':'电脑连接中断，请重试'},status=502,headers={'Cache-Control':'no-store'})
        except web.HTTPException as exc:
            headers={k:v for k,v in exc.headers.items() if k.lower() not in ('content-type','content-length')}
            headers['Cache-Control']='no-store'
            # aiohttp's own text is "503: Service Unavailable"; the page shows this to people
            said=exc.text if exc.text and not exc.text.startswith(f'{exc.status}:') else REASONS.get(exc.status,exc.reason)
            return web.json_response({'error':said},status=exc.status,headers=headers)

    def source(self, request):
        # Only deployment's loopback proxy may supply this header. Never trust XFF.
        peer=request.remote or ''
        if self.trusted_proxy and peer in ('127.0.0.1','::1'):
            value=request.headers.get('X-AR-Client-IP','')
            try: return str(ipaddress.ip_address(value))
            except ValueError: pass
        return peer

    async def costly(self, request, method, *args):
        # A password hash takes a moment and two run at a time; the rest wait their turn, one per address. (Turned
        # away at once, three people signing in together got 429, and two busy addresses kept everyone else out.)
        source=self.source(request)
        entry=self.kdf_ip.setdefault(source,[asyncio.Lock(),0]);entry[1]+=1
        try:
            async with entry[0],self.kdf: return await asyncio.to_thread(method,*args)
        finally:
            entry[1]-=1
            if not entry[1]: self.kdf_ip.pop(source,None)

    async def data(self, request):
        if request.content_length is None or request.content_length>8192: raise ValueError('请求过大或长度缺失')
        try: data=await request.json()
        except (json.JSONDecodeError,UnicodeError): raise ValueError('请求格式错误') from None
        if not isinstance(data,dict) or any(not isinstance(x,str) for x in data.values()): raise ValueError('请求格式错误')
        return data

    async def route(self, request):
        path=request.path
        token=request.cookies.get(COOKIE,'')
        if path in ('/account','/account/ui.css','/account/ui.js') and request.method in ('GET','HEAD'):
            name={'/account':'relay_account.html','/account/ui.css':'relay_account.css','/account/ui.js':'relay_account.js'}[path]
            response=web.Response(body=(HERE/name).read_bytes(),content_type={'html':'text/html','css':'text/css','js':'application/javascript'}[name.rsplit('.',1)[1]])
            response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
                'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
            return response
        if path=='/account/config':
            return web.json_response({'email_enabled':self.mailer.ready,'version':'0.27.0-dev'})
        if path.startswith('/device-auth/'):
            return await self.device_auth(request,token)
        if path.startswith('/account/'):
            return await self.account(request,token)
        if path=='/': raise web.HTTPSeeOther('/account')
        match=re.fullmatch(r'/d/([0-9a-f]{32})(/.*)?',path)
        # Old already-open pages may finish requests using their legacy selector.
        # New /d/ pages never read this cookie and cannot be switched by another tab.
        device=match[1] if match else request.cookies.get('__Host-ar_device','')
        if not re.fullmatch('[0-9a-f]{32}',device):
            if not self.store.valid(token):raise web.HTTPUnauthorized()
            raise web.HTTPNotFound()
        row=self.store.device(token,device)
        if not row:
            if not self.store.valid(token): raise web.HTTPUnauthorized()
            raise web.HTTPNotFound()
        prefix='/d/'+device if match else ''
        if not request.raw_path.startswith(prefix):raise web.HTTPBadRequest()
        suffix=request.raw_path[len(prefix):]
        target=clean_target(suffix if suffix.startswith('/') else '/'+suffix)
        # Local-only account/pair endpoints are not reachable as desktop routes.
        if urlsplit(target).path.startswith(('/account','/relay/','/tunnel/','/device-auth/')): raise web.HTTPNotFound()
        if device in self.hub.connections:
            return await self.hub.proxy(request,token,device,target)
        if row['port'] and row['gateway_secret']:
            return await self.legacy(request,token,row,target)
        raise web.HTTPServiceUnavailable(text='电脑未连接')

    async def account(self, request, token):
        action=request.path.removeprefix('/account/')
        if request.method in ('GET','HEAD') and action=='state':
            if not self.store.valid(token): raise web.HTTPUnauthorized()
            devices=self.store.devices(token)
            for d in devices:
                row=self.store.device(token,d['id'])
                online=d['id'] in self.hub.connections
                d.update(online=online,legacy=bool(row['port']),transport='wss' if online else 'legacy' if row['port'] else 'offline',url='/d/'+d['id']+'/')
            return web.json_response({'devices':devices,'email':self.store.profile(token),'usage':self.store.usage_for(token)})
        if request.method!='POST': raise web.HTTPMethodNotAllowed(request.method,['POST'])
        data=await self.data(request)
        self.store.rate('ip:'+digest(self.source(request)),120,60)
        public={'login','register','resend','forgot','verify','reset'}
        if action not in public and not self.store.valid(token): raise web.HTTPUnauthorized()
        result={'ok':True}
        session=None
        if action=='login':
            session=await self.costly(request,self.store.login,data.get('name',''),data.get('password',''))
        elif action=='logout': self.store.logout(token);session=''
        elif action=='password':
            await self.costly(request,self.store.change_password,token,data.get('old',''),data.get('password',''));session=''
        elif action in ('register','forgot','link-email'):
            if not self.mailer.ready: raise ValueError('邮箱服务暂未启用')
            self.store.rate('mail-ip:'+digest(self.source(request)),10,3600)
            kind={'register':'signup','forgot':'reset','link-email':'link'}[action]
            email=data.get('email','')
            code=await self.costly(request,self.store.email_grant,kind,email,data.get('password',''),token,data.get('old',''))
            if code: await asyncio.to_thread(self.mailer.send,self.store.email(email),kind,code,getattr(code,'pin',''))
            result={'ok':True,'message':'请查收邮件'}
        elif action=='resend':
            if not self.mailer.ready:raise ValueError('邮箱服务暂未启用')
            self.store.rate('mail-ip:'+digest(self.source(request)),10,3600)
            email=self.store.email(data.get('email',''))
            code=self.store.resend_signup(email)
            if code:await asyncio.to_thread(self.mailer.send,email,'signup',code,getattr(code,'pin',''))
            result={'ok':True,'message':'请查收邮件'}
        elif action=='verify':
            if data.get('pin'):session=self.store.start_session(await self.costly(request,self.store.consume_pin,data.get('email',''),'signup',data['pin']))
            else:await self.costly(request,self.store.consume_email,data.get('code',''))
        elif action=='reset':
            if data.get('pin'):session=self.store.start_session(await self.costly(request,self.store.consume_pin,data.get('email',''),'reset',data['pin'],data.get('password','')))
            else:await self.costly(request,self.store.reset_compatible,data.get('code',''),data.get('password',''))
        elif action=='rename': self.store.rename(token,data.get('id',''),data.get('label',''))
        elif action=='revoke':
            ident=data.get('id','')
            if not self.store.revoke(token,ident): raise web.HTTPNotFound()
            await self.hub.disconnect(ident)
        elif action=='select':
            ident=data.get('id','')
            if not self.store.device(token,ident): raise web.HTTPNotFound()
            result['url']='/d/'+ident+'/'
        else: raise web.HTTPNotFound()
        response=web.json_response(result,headers={'Cache-Control':'no-store'})
        if session is not None:
            response.set_cookie(COOKIE,session,path='/',secure=True,httponly=True,samesite='Strict',max_age=TTL if session else 0)
        return response

    async def device_auth(self, request, token):
        action=request.path.removeprefix('/device-auth/')
        if action=='start' and request.method=='POST':
            self.store.rate('auth-start:'+digest(self.source(request)),30,3600)
            self.store.rate('auth-start-global',120,3600)
            data=await self.data(request)
            ident=self.store.start_authorization(bearer(request),data.get('label',''))
            return web.json_response({'id':ident,'url':self.origin+'/account?authorize='+ident})
        if action=='poll' and request.method=='POST':
            data=await self.data(request)
            row=self.store.authorization(data.get('id',''),bearer(request))
            return web.json_response({'approved':bool(row['approved']),'device':row['device']})
        if not self.store.valid(token): raise web.HTTPUnauthorized()
        if action=='details' and request.method=='GET':
            row=self.store.authorization(request.query.get('id',''))
            return web.json_response({'label':row['label'],'approved':bool(row['approved'])})
        if action=='approve' and request.method=='POST':
            data=await self.data(request)
            ident=self.store.approve(token,data.get('id',''),data.get('existing',''))
            await self.hub.disconnect(ident)
            return web.json_response({'ok':True,'device':ident})
        raise web.HTTPNotFound()

    async def legacy(self,request,token,row,target):
        if self.hub.active>=64 or self.legacy_counts.get(row['id'],0)>=16:
            raise web.HTTPServiceUnavailable(headers={'Retry-After':'2'})
        self.hub.active+=1
        self.legacy_counts[row['id']]=self.legacy_counts.get(row['id'],0)+1
        request['usage']=[0,0]
        try:return await self.legacy_proxy(request,token,row,target)
        finally:
            self.hub.active-=1
            self.legacy_counts[row['id']]-=1
            self.store.usage(row['id'],*request['usage'],1)

    async def legacy_proxy(self,request,token,row,target):
        # Temporary fallback for existing FRP devices; destination never comes from callers.
        headers={k:request.headers[k] for k in REQUEST_HEADERS if k in request.headers}
        headers.update({'Host':self.authority,'Origin':self.origin,'Authorization':'Bearer '+row['gateway_secret']})
        if request.content_length is not None: headers['Content-Length']=str(request.content_length)
        async def body():
            total=0
            async for chunk in request.content.iter_chunked(65536):
                if not self.store.device(token,row['id']): raise PermissionError()
                total+=len(chunk)
                if total>MAX_BODY: raise ValueError('请求过大')
                request['usage'][0]+=len(chunk)
                yield chunk
        async with ClientSession(timeout=ClientTimeout(total=None,sock_connect=10,sock_read=120),auto_decompress=False) as client:
            async with client.request(request.method,'http://127.0.0.1:'+str(row['port'])+target,
                    headers=headers,data=body() if request.method=='POST' else None,allow_redirects=False) as upstream:
                if not self.store.device(token,row['id']): raise web.HTTPUnauthorized()
                if request.method=='GET' and urlsplit(target).path in ('/','/input-diagnostics') and 'text/html' in upstream.headers.get('Content-Type',''):
                    page=bytearray()
                    async for chunk in upstream.content.iter_chunked(65536):
                        if not self.store.device(token,row['id']): raise web.HTTPUnauthorized()
                        page.extend(chunk)
                        if len(page)>2*1024*1024: raise ValueError('网页过大')
                    body=scoped_page(bytes(page),row['id'])
                    request['usage'][1]=len(body)
                    return web.Response(body=body,content_type='text/html',headers={'Cache-Control':'no-store','X-Agent-Remote-Transport':'legacy'})
                response=web.StreamResponse(status=upstream.status,headers={k:v for k,v in upstream.headers.items() if k.lower() in RESPONSE_HEADERS})
                response.headers['Cache-Control']='no-store'
                response.headers['X-Agent-Remote-Transport']='legacy'
                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    if not self.store.device(token,row['id']):
                        if request.transport: request.transport.close()
                        return response
                    await response.write(chunk)
                    request['usage'][1]+=len(chunk)
                await response.write_eof()
                return response


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--port',type=int,default=18771)
    parser.add_argument('--trusted-proxy',action='store_true')
    args=parser.parse_args()
    os.umask(0o077)
    store=Identity(args.state,int(os.getenv('AR_ACCOUNT_LIMIT','20')),int(os.getenv('AR_DEVICE_LIMIT','3')))
    service=Service(args.origin,store,trusted_proxy=args.trusted_proxy)
    web.run_app(service.app,host='127.0.0.1',port=args.port,access_log=None,print=None)


if __name__=='__main__': main()
