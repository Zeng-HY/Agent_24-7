"""遥应's own notifications on the iPhone, through Apple's push service (APNs), sent by this relay (10-26).

The iPhone app, signed in, registers the push token iOS gave it (POST /account/push/register). The token belongs to
the account, not to the sign-in, so it keeps working after a 7-day sign-in runs out (relay_accounts TTL); signing out
removes it, and a new password removes all of an account's phones. While an account has a phone, the relay keeps a
stream open to each of its connected computers: GET /api/notify/push through the tunnel (notify.py, ntfy_feed.py),
which says only which app, which conversation and what happened. The relay writes the words itself, "Claude · 我的
电脑" over "有个对话好了", and hands them to Apple for each of the account's phones. Apple sees those words and the
computer's and the conversation's ids, never the conversation. A tap opens that conversation in the app, which checks
the account and the computer first.

APNs takes HTTP/2 only (httpx with h2) and a token signed with the team's key (ES256, cryptography); both are
imported only when push is configured, so a relay without them still runs, with push off. The settings come from
/etc/agent-relay/push.env (root 0600, read by systemd for the service; configure-push.py): AR_APNS_KEY (the .p8 key,
base64), AR_APNS_KEY_ID, AR_APNS_TEAM_ID, AR_APNS_TOPIC. Nothing of the key, and never a whole token, is logged.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import quote

from aiohttp import web

from relay_transport import Refused

log = logging.getLogger('relay.push')

TOPIC = 'com.pocketagentdesk.teleply'
HOSTS = {'production': 'api.push.apple.com', 'development': 'api.sandbox.push.apple.com'}
PLATFORMS = ('ios',)        # an Android channel (Huawei, FCM) would add its own name and sender here
APPS = {'codex': 'Codex', 'claude': 'Claude', 'deepseek': 'DeepSeek'}
WORDS = {'done': '有个对话好了', 'failed': '有个对话出错停了', 'waiting': '有个对话在等你处理'}
KEEP = {'done': 86400, 'failed': 86400, 'waiting': 3 * 86400}  # how long Apple holds one for a phone that is away
PHONES = 10                 # an account's phones; the one not seen for longest makes way for a new one
PER_CHAT = 60               # seconds between two notices of one kind for one conversation
PER_HOUR = 30               # notices an account gets in an hour
SWEEP = 30                  # seconds between looks at which computers to listen to
TOKEN_AGE = 50 * 60         # a provider token is used this long (APNs: renewed after 20 to 60 minutes)
SINCE = '10m'               # what a computer is asked for when the relay has not read from it yet (a restart)
TOKEN = re.compile(r'[0-9a-f]{32,256}')
NDJSON = 'application/x-ndjson'


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def provider_token(key, key_id, team_id, issued):
    """The bearer token APNs wants: a JWT with the key's id and the team, signed ES256 with the team's .p8 key."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    head = _b64(json.dumps({'alg': 'ES256', 'kid': key_id}, separators=(',', ':')).encode())
    claims = _b64(json.dumps({'iss': team_id, 'iat': int(issued)}, separators=(',', ':')).encode())
    r, s = decode_dss_signature(key.sign(f'{head}.{claims}'.encode('ascii'), ec.ECDSA(hashes.SHA256())))
    return f'{head}.{claims}.{_b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}'


def short(token):
    """A token as logs show it: the start of its hash."""
    return hashlib.sha256(token.encode()).hexdigest()[:8]


class Apns:
    """Sends to Apple: one HTTP/2 connection per host, kept open; the provider token renewed every 50 minutes."""

    def __init__(self, key_pem, key_id, team_id, topic=TOPIC, clock=time.time, transport=None):
        import httpx
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        self.key = load_pem_private_key(key_pem, password=None)
        self.key_id, self.team_id, self.topic, self.clock = key_id, team_id, topic, clock
        self.client = httpx.AsyncClient(http2=transport is None, transport=transport, timeout=httpx.Timeout(15.0))
        self.token, self.made = '', 0.0

    def bearer(self, renew=False):
        if renew or not self.token or self.clock() - self.made >= TOKEN_AGE:
            self.made = self.clock()
            self.token = provider_token(self.key, self.key_id, self.team_id, self.made)
        return self.token

    async def send(self, environment, token, payload, collapse, expires):
        """(status, reason): (200, '') when Apple took it."""
        url = f'https://{HOSTS.get(environment, HOSTS["production"])}/3/device/{token}'
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        for attempt in (1, 2):
            headers = {'authorization': 'bearer ' + self.bearer(renew=attempt == 2), 'apns-topic': self.topic,
                       'apns-push-type': 'alert', 'apns-priority': '10', 'apns-expiration': str(int(expires)),
                       'content-type': 'application/json'}
            if collapse:
                headers['apns-collapse-id'] = collapse
            response = await self.client.post(url, content=body, headers=headers)
            reason = ''
            if response.status_code != 200:
                try:
                    reason = str(response.json().get('reason', ''))
                except (ValueError, AttributeError):
                    reason = ''
            if response.status_code == 403 and reason == 'ExpiredProviderToken' and attempt == 1:
                continue
            return response.status_code, reason
        return 403, 'ExpiredProviderToken'

    async def close(self):
        await self.client.aclose()


def from_env(env=None):
    """The sender the server is set up for (configure-push.py), or None: push stays off and the app is told so.
    The key comes base64 in AR_APNS_KEY, or as a file the service can read (AR_APNS_KEY_FILE)."""
    env = os.environ if env is None else env
    key, path = env.get('AR_APNS_KEY', ''), env.get('AR_APNS_KEY_FILE', '')
    key_id, team_id = env.get('AR_APNS_KEY_ID', ''), env.get('AR_APNS_TEAM_ID', '')
    if not (key or path or key_id or team_id):
        return None
    try:
        pem = base64.b64decode(key, validate=True) if key else Path(path).read_bytes()
        return Apns(pem, key_id, team_id, env.get('AR_APNS_TOPIC', '') or TOPIC)
    except Exception as exc:  # a missing library, an unreadable or broken key: said once, without the key
        log.warning('push off: %s', type(exc).__name__)
        return None


class Push:
    """The phones' registry, the streams from the computers and the sending (module docstring)."""

    def __init__(self, store, hub, sender=None, clock=time.time):
        self.store, self.hub, self.sender, self.clock = store, hub, sender, clock
        self.watchers = {}          # computer -> the task reading its events
        self.since = {}             # computer -> the id of the last event read from it
        self.sent = {}              # (computer, app, conversation, kind) -> when its last notice went
        self.hours = {}             # account -> when its notices of the last hour went
        self.task = None
        self.woken = None           # made in start(), on the service's own loop (Python 3.9 ties it at creation)

    @property
    def available(self):
        return self.sender is not None

    # -- what the app asks (POST /account/push/<action>, relay_service.Service.account)

    async def account(self, action, token, data):
        owner = self.store.owner(token)
        if not owner:
            raise web.HTTPUnauthorized()
        if action == 'state':
            given = data.get('token', '').strip().lower()
            with self.store.connect() as db:
                phones = db.execute('SELECT count(*) FROM push_phones WHERE owner=?', (owner,)).fetchone()[0]
                mine = bool(given) and db.execute('SELECT 1 FROM push_phones WHERE owner=? AND token=?',
                                                  (owner, given)).fetchone() is not None
            return {'available': self.available, 'registered': mine, 'phones': phones}
        if action == 'register':
            self.register(owner, data)
            self.wake()
            return {'ok': True}
        if action == 'unregister':
            with self.store.connect() as db:
                db.execute('DELETE FROM push_phones WHERE owner=? AND token=?', (owner, data.get('token', '').strip().lower()))
            return {'ok': True}
        if action == 'test':
            return await self.test(owner, data.get('token', '').strip().lower())
        raise web.HTTPNotFound()

    def register(self, owner, data):
        token = data.get('token', '').strip().lower()
        platform, environment = data.get('platform', 'ios'), data.get('environment', 'production')
        label, version = data.get('label', '').strip()[:40] or 'iPhone', data.get('version', '').strip()[:20]
        if not TOKEN.fullmatch(token):
            raise ValueError('推送令牌无效')
        if platform not in PLATFORMS:
            raise ValueError('这种手机还不能收遥应通知')
        if environment not in HOSTS:
            raise ValueError('推送环境无效')
        now = self.clock()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM push_phones WHERE token=?', (token,)).fetchone()
            if row:  # the same phone again, or signed in to another account now: it follows the sign-in
                db.execute('UPDATE push_phones SET owner=?,platform=?,environment=?,label=?,version=?,refreshed=? '
                           'WHERE id=?', (owner, platform, environment, label, version, now, row['id']))
                return
            stale = db.execute('SELECT id FROM push_phones WHERE owner=? ORDER BY refreshed DESC LIMIT -1 OFFSET ?',
                               (owner, PHONES - 1)).fetchall()
            db.executemany('DELETE FROM push_phones WHERE id=?', [(r['id'],) for r in stale])
            db.execute('INSERT INTO push_phones VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (secrets.token_hex(16), owner, platform, environment, token, label, version, now, now, ''))

    async def test(self, owner, token):
        with self.store.connect() as db:
            phone = db.execute('SELECT * FROM push_phones WHERE owner=? AND token=?', (owner, token)).fetchone()
        if not phone:
            raise ValueError('这部手机还没登记遥应通知，请重新打开')
        payload = {'aps': {'alert': {'title': '遥应', 'body': '试推一条：通知是好的'}, 'sound': 'default'}}
        status, reason = await self.send(dict(phone), payload, '', self.clock() + 600)
        if status == 200:
            return {'ok': True, 'text': '刚推了一条，看看通知'}
        if status in (400, 410) and reason in ('BadDeviceToken', 'DeviceTokenNotForTopic', 'Unregistered', 'ExpiredToken'):
            raise ValueError('这部手机的推送令牌已失效，请重新打开遥应通知')
        raise ValueError('苹果没收下这条通知：' + (reason or f'HTTP {status}' if status else '连不上苹果的推送服务'))

    # -- listening to the computers

    async def start(self, app=None):
        if self.available and self.task is None:
            self.woken = asyncio.Event()
            self.task = asyncio.create_task(self.sweep())

    async def stop(self, app=None):
        tasks = [t for t in [self.task, *self.watchers.values()] if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.task, self.watchers = None, {}
        if self.sender is not None and hasattr(self.sender, 'close'):
            await self.sender.close()

    def wake(self):
        """A phone was added: look at once instead of within SWEEP seconds."""
        if self.woken is not None:
            self.woken.set()

    async def sweep(self):
        while True:
            try:
                self.look()
            except Exception as exc:  # the database busy for a moment: the next look tries again
                log.warning('push: %s', type(exc).__name__)
            try:
                await asyncio.wait_for(self.woken.wait(), SWEEP)
            except asyncio.TimeoutError:
                pass
            self.woken.clear()

    def look(self):
        """Listen to each connected computer of an account with a phone, and to no other."""
        with self.store.connect() as db:
            owners = {r[0] for r in db.execute('SELECT DISTINCT owner FROM push_phones')}
            owned = {r['id']: r['owner'] for r in db.execute('SELECT id,owner FROM devices WHERE revoked=0')}
        wanted = {device for device in self.hub.connections if owned.get(device) in owners}
        for device, task in list(self.watchers.items()):
            if device not in wanted or task.done():
                task.cancel()
                del self.watchers[device]
        for device in wanted - set(self.watchers):
            self.watchers[device] = asyncio.create_task(self.watch(device))

    async def watch(self, device):
        """One computer's events, read again after a break; a computer without the route is asked every 30 minutes."""
        delay = 5
        while device in self.hub.connections:
            started = self.clock()
            try:
                target = '/api/notify/push?since=' + quote(self.since.get(device, SINCE), safe='')
                chunks = self.hub.fetch(device, target, {'Accept': NDJSON})
                try:  # not contextlib.aclosing: the server's Python may be 3.9
                    rest = b''
                    async for chunk in chunks:
                        *lines, rest = (rest + chunk).split(b'\n')
                        for line in lines:
                            await self.receive(device, line)
                        if len(rest) > 65536:
                            raise ValueError('line too long')
                finally:
                    await chunks.aclose()
                wait = 1
            except asyncio.CancelledError:
                raise
            except Refused as exc:
                wait = 1800 if exc.status == 404 else 60
            except Exception:
                wait = delay
            delay = 5 if self.clock() - started > 120 else min(delay * 2, 300)
            await asyncio.sleep(wait)

    async def receive(self, device, line):
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict) or event.get('event') != 'message':
            return  # the stream's "open" and "keepalive"
        ident = event.get('id')
        if isinstance(ident, str) and 0 < len(ident) <= 64:
            self.since[device] = ident
            await self.deliver(device, event)

    async def deliver(self, device, event):
        kind, app, chat = event.get('kind'), event.get('app'), event.get('chat')
        if kind not in WORDS or app not in APPS or not isinstance(chat, str) or not 0 < len(chat) <= 200:
            return
        now = self.clock()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM push_events WHERE time<?', (now - 7 * 86400,))
            fresh = db.execute('INSERT OR IGNORE INTO push_events VALUES (?,?)', (device + ':' + event['id'], now)).rowcount
            computer = db.execute('SELECT owner,label FROM devices WHERE id=? AND revoked=0', (device,)).fetchone()
            phones = [dict(r) for r in db.execute('SELECT * FROM push_phones WHERE owner=?', (computer['owner'],))] if computer else []
        if not fresh or not phones:  # read again after a break (since=10m), or nobody to tell
            return
        owner = computer['owner']
        if now - self.sent.get((device, app, chat, kind), -PER_CHAT) < PER_CHAT:
            return
        hour = [t for t in self.hours.get(owner, []) if now - t < 3600]
        if len(hour) >= PER_HOUR:
            self.hours[owner] = hour
            return
        self.hours[owner] = hour + [now]
        self.sent = {k: t for k, t in self.sent.items() if now - t < PER_CHAT}
        self.sent[(device, app, chat, kind)] = now
        thread = hashlib.sha256(f'{device}|{app}|{chat}'.encode()).hexdigest()[:24]
        payload = {'aps': {'alert': {'title': f'{APPS[app]} · {computer["label"]}', 'body': WORDS[kind]},
                           'sound': 'default', 'thread-id': thread},
                   'teleply': {'d': device, 'a': app, 'c': chat}}
        for phone in phones:
            await self.send(phone, payload, thread, now + KEEP[kind])

    async def send(self, phone, payload, collapse, expires):
        """To one phone, once more after a moment when Apple or the network had a hiccup. A token Apple says is
        dead is dropped."""
        for attempt in (1, 2):
            try:
                status, reason = await self.sender.send(phone['environment'], phone['token'], payload, collapse, expires)
            except Exception as exc:
                status, reason = 0, type(exc).__name__
            if attempt == 1 and (status in (0, 429) or status >= 500):
                await asyncio.sleep(3)
                continue
            break
        gone = status == 410 or (status == 400 and reason in ('BadDeviceToken', 'DeviceTokenNotForTopic'))
        with self.store.connect() as db:
            if gone:
                db.execute('DELETE FROM push_phones WHERE id=?', (phone['id'],))
            else:
                result = time.strftime('%m-%d %H:%M', time.localtime(self.clock())) + (' ok' if status == 200 else f' {status} {reason}'.rstrip())
                db.execute('UPDATE push_phones SET result=? WHERE id=?', (result, phone['id']))
        if status != 200:
            log.warning('push: %s %s for phone %s%s', status or 'no answer', reason, short(phone['token']), ' (dropped)' if gone else '')
        return status, reason
