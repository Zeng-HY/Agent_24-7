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
# 灵动岛 (Live Activities) pushes go to this topic and header (handoff 5.3). The key is Topic Specific and the
# developer portal lists themes by Bundle ID, so the topic is the app's plus Apple's suffix; 阶段零 proves it.
ISLAND_TOPIC = TOPIC + '.push-type.liveactivity'
HOSTS = {'production': 'api.push.apple.com', 'development': 'api.sandbox.push.apple.com'}
PLATFORMS = ('ios',)        # an Android channel (Huawei, FCM) would add its own name and sender here
APPS = {'codex': 'Codex', 'claude': 'Claude', 'deepseek': 'DeepSeek'}
WORDS = {'done': '有个对话好了', 'failed': '有个对话出错停了', 'waiting': '有个对话在等你处理'}
ISLAND_STATES = ('working', 'waiting', 'done', 'failed', 'offline', 'limited')
ISLAND_FIELDS = ('ask', 'askType', 'choices', 'askText', 'askOptions', 'step', 'resets')
ISLAND_RELEVANCE = {'waiting': 100, 'limited': 90, 'failed': 80, 'offline': 60, 'working': 50, 'done': 10}
ISLAND_GAP = 5                  # seconds between two pushes to one island
ISLAND_PER_HOUR = 120           # island pushes an account gets in an hour (notices are counted apart)
REMOTE_AFTER = 60               # a turn running this long gets an island started from afar
OFFLINE_AFTER = 60              # a computer gone this long turns its islands grey
OFFLINE_END_AFTER = 30 * 60     # gone this long ends them; the lock screen keeps one an hour
END_AFTER = 5 * 60              # done or failed islands end this long after the state began
GONE_REASONS = ('BadDeviceToken', 'DeviceTokenNotForTopic', 'Unregistered', 'ExpiredToken')
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


def island_state(state, since, turn, **extra):
    """One island's changing part as the extension decodes it (tests/fixtures/island-states.json has the samples).

    Only the fields the state has: a push that leaves one out must not write null into a previous value, and the
    relay never writes the conversation's words (askText/askOptions are the phone's alone)."""
    content = {'state': state, 'since': int(since), 'turn': int(turn)}
    for key in ISLAND_FIELDS:
        value = extra.get(key)
        if value is not None:
            content[key] = value
    return content


def island_gone(status, reason):
    """Apple says this token is dead: the island is dropped and its update falls back to a notice."""
    return status == 410 or (status == 400 and reason in GONE_REASONS)


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

    async def send(self, environment, token, payload, collapse, expires, push_type='alert', priority=10, topic=None):
        """(status, reason): (200, '') when Apple took it. Islands pass push_type='liveactivity', their topic and a
        lower priority for 在干活 (handoff 5.3)."""
        url = f'https://{HOSTS.get(environment, HOSTS["production"])}/3/device/{token}'
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        for attempt in (1, 2):
            headers = {'authorization': 'bearer ' + self.bearer(renew=attempt == 2),
                       'apns-topic': topic or self.topic, 'apns-push-type': push_type,
                       'apns-priority': str(priority), 'apns-expiration': str(int(expires)),
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
        self.starts = {}            # (computer, app, conversation) -> when the turn began, for a remote start
        self.away = {}              # computer -> when it was first missed, for 断开了
        self.seen = set()           # computers seen connected since this relay started
        self.island_last = {}       # island id -> when it was last pushed (ISLAND_GAP)
        self.island_hours = {}      # account -> when its island pushes of the last hour went
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
        if action == 'activity':
            return self.activity(owner, data)
        if action == 'start-token':
            return self.start_token(owner, data)
        if action == 'island-test':
            return await self.island_test(owner, data)
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

    # -- 灵动岛 (handoff 5.3, 阶段零)

    def activity(self, owner, data):
        """One island's push token, for the account's computer and conversation; op=unregister forgets it."""
        op = str(data.get('op', 'register'))
        token = str(data.get('token', '')).strip().lower()
        device = str(data.get('device', '')).strip().lower()
        app, chat = data.get('app', ''), data.get('chat', '')
        environment = data.get('environment', 'production')
        if op not in ('register', 'unregister'):
            raise ValueError('不认识的操作')
        if not TOKEN.fullmatch(token):
            raise ValueError('岛的推送令牌无效')
        if not re.fullmatch(r'[0-9a-f]{32}', device):
            raise ValueError('电脑标识无效')
        if app not in APPS or not isinstance(chat, str) or not 0 < len(chat) <= 200:
            raise ValueError('岛的内容无效')
        if environment not in HOSTS:
            raise ValueError('推送环境无效')
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM devices WHERE id=? AND owner=? AND revoked=0', (device, owner)).fetchone():
                raise ValueError('这台电脑不属于这个账号')
            if op == 'unregister':
                db.execute('DELETE FROM push_activities WHERE owner=? AND token=?', (owner, token))
                return {'ok': True}
            state = data.get('state', 'working')
            state = state if state in ISLAND_STATES else 'working'
            now = self.clock()
            try:
                since, turn = int(data.get('since') or now), int(data.get('turn') or now)
            except (TypeError, ValueError):
                raise ValueError('岛的时间无效')
            row = db.execute('SELECT id FROM push_activities WHERE token=?', (token,)).fetchone()
            if row:  # the same island registered again (its token does not change)
                db.execute('UPDATE push_activities SET owner=?,device=?,app=?,chat=?,environment=?,state=?,since=?,'
                           'turn=?,refreshed=? WHERE id=?', (owner, device, app, chat, environment, state, since, turn,
                                                            now, row['id']))
            else:
                db.execute('INSERT INTO push_activities (id,owner,device,app,chat,token,environment,state,since,turn,'
                           'created,refreshed,result) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (secrets.token_hex(16), owner, device, app, chat, token, environment, state, since, turn,
                            now, now, ''))
        return {'ok': True}

    def start_token(self, owner, data):
        """A phone's push-to-start token (remote-started islands, iOS 18): one row per token."""
        token = str(data.get('token', '')).strip().lower()
        environment = data.get('environment', 'production')
        if not TOKEN.fullmatch(token):
            raise ValueError('推送令牌无效')
        if environment not in HOSTS:
            raise ValueError('推送环境无效')
        with self.store.connect() as db:
            db.execute('INSERT INTO push_start VALUES (?,?,?,?) ON CONFLICT(token) DO UPDATE SET owner=excluded.owner,'
                       'environment=excluded.environment,refreshed=excluded.refreshed',
                       (token, owner, environment, self.clock()))
        return {'ok': True}

    async def island_test(self, owner, data):
        """One update to an island this account registered, so the app can prove the key may send the topic 3.5
        could not settle with a made-up phone. It only ever says 好了."""
        device, app, chat = str(data.get('device', '')).strip().lower(), data.get('app', ''), data.get('chat', '')
        with self.store.connect() as db:
            row = db.execute('SELECT a.*, d.label FROM push_activities a JOIN devices d ON d.id=a.device '
                             'WHERE a.owner=? AND a.device=? AND a.app=? AND a.chat=? ORDER BY a.refreshed DESC LIMIT 1',
                             (owner, device, app, chat)).fetchone()
        if not row:
            raise ValueError('先在这部手机上开一个岛，再点这个。')
        now = int(self.clock())
        payload = {'aps': {'timestamp': now, 'event': 'update',
                           'content-state': island_state('done', now, row['turn'] or now),
                           'relevance-score': 10,
                           'alert': {'title': f'{APPS[row["app"]]} · {row["label"]}', 'body': '好了', 'sound': 'default'}}}
        status, reason = await self.send_island(dict(row), payload)
        if status == 200:
            with self.store.connect() as db:
                db.execute('UPDATE push_activities SET state=?,since=?,refreshed=? WHERE id=?',
                           ('done', now, self.clock(), row['id']))
            return {'ok': True, 'text': '中转推了一条，岛应该变成 ✓ 了'}
        if status in (400, 410) and reason in ('BadDeviceToken', 'DeviceTokenNotForTopic', 'Unregistered', 'ExpiredToken'):
            raise ValueError('苹果不认这个岛的令牌：请关掉试的岛再开一次。')
        raise ValueError('苹果没收下岛的推送：' + (reason or f'HTTP {status}' if status else '连不上苹果的推送服务')
                         + '（密钥可能不认灵动岛的主题，见交接 3.5）')

    async def send_live(self, environment, token, payload, priority=10, expires=None):
        """One Live Activity push to Apple, tried once more after a hiccup; no database row of its own."""
        expires = self.clock() + 600 if expires is None else expires
        status, reason = 0, ''
        for attempt in (1, 2):
            try:
                status, reason = await self.sender.send(environment, token, payload, '', expires,
                                                        push_type='liveactivity', priority=priority, topic=ISLAND_TOPIC)
            except Exception as exc:  # no answer: tried once more below
                status, reason = 0, type(exc).__name__
            if attempt == 1 and (status in (0, 429) or status >= 500):
                await asyncio.sleep(3)
                continue
            break
        if status != 200:
            log.warning('island: %s %s for token %s', status or 'no answer', reason, short(token))
        return status, reason

    async def send_island(self, activity, payload, priority=10):
        """A Live Activity push for one registered island; a dead token drops the island."""
        status, reason = await self.send_live(activity['environment'], activity['token'], payload, priority=priority)
        gone = island_gone(status, reason)
        with self.store.connect() as db:
            if gone:
                db.execute('DELETE FROM push_activities WHERE id=?', (activity['id'],))
            else:
                result = time.strftime('%m-%d %H:%M', time.localtime(self.clock())) + (
                    ' ok' if status == 200 else f' {status} {reason}'.rstrip())
                db.execute('UPDATE push_activities SET result=?,refreshed=? WHERE id=?',
                           (result, self.clock(), activity['id']))
        return status, reason

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
                await self.sweep_islands()
            except Exception as exc:  # the database busy for a moment: the next look tries again
                log.warning('push: %s', type(exc).__name__)
            try:
                await asyncio.wait_for(self.woken.wait(), SWEEP)
            except asyncio.TimeoutError:
                pass
            self.woken.clear()

    def look(self):
        """Listen to each connected computer of an account with a phone, and to no other."""
        self.seen |= set(self.hub.connections)
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
        if kind not in (*WORDS, 'running') or app not in APPS or not isinstance(chat, str) or not 0 < len(chat) <= 200:
            return
        now = self.clock()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM push_events WHERE time<?', (now - 7 * 86400,))
            fresh = db.execute('INSERT OR IGNORE INTO push_events VALUES (?,?)', (device + ':' + event['id'], now)).rowcount
            computer = db.execute('SELECT owner,label FROM devices WHERE id=? AND revoked=0', (device,)).fetchone()
            island = None
            if computer:
                island = db.execute('SELECT a.*, d.label FROM push_activities a JOIN devices d ON d.id=a.device '
                                    'WHERE a.device=? AND a.app=? AND a.chat=? ORDER BY a.refreshed DESC LIMIT 1',
                                    (device, app, chat)).fetchone()
            phones = [dict(r) for r in db.execute('SELECT * FROM push_phones WHERE owner=?', (computer['owner'],))] if computer else []
        if not fresh or not computer:
            return
        owner, conv = computer['owner'], (device, app, chat)
        quiet = bool(event.get('quiet'))  # the phone has this conversation open: no banner, but the island still changes
        if kind == 'running':
            since = event.get('since')
            since = int(since) if isinstance(since, (int, float)) and since > 0 else int(now)
            self.starts[conv] = since
            if island and now - since < 12 * 3600:  # a turn that began hours ago is not shown as running now
                await self.update_island(island, 'working', since, island['turn'] or since, alert=False, priority=5)
            return
        self.starts.pop(conv, None)
        if island:  # 方案一: with an island, the island is the notice (user 10-28: only the island, no second banner)
            state = {'waiting': 'waiting', 'done': 'done', 'failed': 'failed'}[kind]
            if await self.update_island(island, state, int(now), island['turn'] or int(now), alert=True, priority=10):
                return
        if quiet:
            return
        await self.notice(owner, device, app, chat, kind, computer['label'], phones, now)

    async def notice(self, owner, device, app, chat, kind, label, phones, now):
        """A normal notification on the lock screen, as before 10-28: only for a conversation without a working
        island (or one whose token Apple says is dead), and never while the phone shows that conversation."""
        if not phones:
            return
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
        payload = {'aps': {'alert': {'title': f'{APPS[app]} · {label}', 'body': WORDS[kind]},
                           'sound': 'default', 'thread-id': thread},
                   'teleply': {'d': device, 'a': app, 'c': chat}}
        for phone in phones:
            await self.send(phone, payload, thread, now + KEEP[kind])

    # -- 灵动岛's own pushes (方案一、四)

    def island_since(self, row, now):
        return int(row['since'] or now)

    async def update_island(self, row, state, since, turn, alert, priority, clear_saved=False):
        """One update to an island. True when the island took it (or was held back by a limit, which still means the
        notice must not be sent as well); False only when Apple says the token is dead, so the caller falls back."""
        now = self.clock()
        if not alert and now - self.island_last.get(row['id'], -ISLAND_GAP) < ISLAND_GAP:
            return True  # 在干活 and progress wait their five seconds; a state change does not
        owner = row['owner']
        hour = [t for t in self.island_hours.get(owner, []) if now - t < 3600]
        if len(hour) >= ISLAND_PER_HOUR:
            self.island_hours[owner] = hour
            return True
        self.island_hours[owner] = hour + [now]
        self.island_last[row['id']] = now
        payload = {'aps': {'timestamp': int(now), 'event': 'update',
                           'content-state': island_state(state, int(since), int(turn)),
                           'relevance-score': ISLAND_RELEVANCE.get(state, 50)}}
        if state == 'working':
            payload['aps']['stale-date'] = int(now + 15 * 60)
        if alert:
            payload['aps']['alert'] = {'title': f'{APPS[row["app"]]} · {row["label"]}',
                                       'body': {'waiting': '有个对话在等你处理', 'done': '有个对话好了',
                                                'failed': '有个对话出错停了'}.get(state, '有个对话好了'),
                                       'sound': 'default'}
        status, reason = await self.send_island(dict(row), payload, priority=priority)
        if status == 200:
            with self.store.connect() as db:
                if clear_saved:
                    db.execute('UPDATE push_activities SET state=?,since=?,turn=?,refreshed=?,saved_state=NULL,'
                               'saved_since=NULL,saved_turn=NULL WHERE id=?',
                               (state, int(since), int(turn), self.clock(), row['id']))
                else:
                    db.execute('UPDATE push_activities SET state=?,since=?,turn=?,refreshed=? WHERE id=?',
                               (state, int(since), int(turn), self.clock(), row['id']))
            return True
        return not island_gone(status, reason)

    async def end_island(self, row, dismissal, state=None):
        """The turn is over (or the computer has been away too long): the island leaves after `dismissal`."""
        now = int(self.clock())
        payload = {'aps': {'timestamp': now, 'event': 'end',
                           'content-state': island_state(state or row['state'], row['since'] or now, row['turn'] or now),
                           'dismissal-date': int(dismissal)}}
        status, reason = await self.send_island(row, payload, priority=10)
        return status == 200

    async def remote_start(self, device, app, chat, since, computer, starts):
        """方案一: a turn on the computer has run a minute; start an island from afar with the phone's start token."""
        now = int(self.clock())
        payload = {'aps': {'timestamp': now, 'event': 'start', 'attributes-type': 'IslandAttributes',
                           'attributes': {'device': device, 'app': app, 'chat': chat,
                                          'computer': computer['label'], 'title': ''},
                           'content-state': island_state('working', int(since), int(since)),
                           'alert': {'title': f'{APPS[app]} · {computer["label"]}', 'body': '开始干活了',
                                     'sound': 'default'},
                           'input-push-token': 1}}
        sent = False
        for start in starts:
            status, reason = await self.send_live(start['environment'], start['token'], payload, priority=10)
            if status == 200:
                sent = True
            elif island_gone(status, reason):
                with self.store.connect() as db:
                    db.execute('DELETE FROM push_start WHERE token=?', (start['token'],))
        return sent

    async def sweep_islands(self):
        """Every SWEEP seconds: remote starts, done or failed islands ending, and a computer gone grey."""
        now = self.clock()
        connected = set(self.hub.connections)
        self.seen |= connected
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT a.*, d.label FROM push_activities a '
                                                'JOIN devices d ON d.id=a.device')]
        for conv, since in list(self.starts.items()):
            device, app, chat = conv
            if now - since < REMOTE_AFTER or device not in connected:
                continue
            with self.store.connect() as db:
                island = db.execute('SELECT 1 FROM push_activities WHERE device=? AND app=? AND chat=?',
                                    (device, app, chat)).fetchone()
                computer = db.execute('SELECT owner,label FROM devices WHERE id=? AND revoked=0', (device,)).fetchone()
                starts = [dict(r) for r in db.execute('SELECT * FROM push_start WHERE owner=?',
                                                      (computer['owner'],))] if computer else []
            if island or not computer:
                self.starts.pop(conv, None)
                continue
            if not starts:
                if now - since > 10 * 60:
                    self.starts.pop(conv, None)
                continue
            if await self.remote_start(device, app, chat, since, computer, starts):
                self.starts.pop(conv, None)
            elif now - since > 10 * 60:
                self.starts.pop(conv, None)
        for row in rows:
            device = row['device']
            if device in connected:
                self.away.pop(device, None)
                if row['state'] == 'offline' and row['saved_state']:
                    await self.update_island(row, row['saved_state'], row['saved_since'] or int(now),
                                             row['saved_turn'] or int(now), alert=False, priority=10, clear_saved=True)
            elif device in self.seen:
                first = self.away.setdefault(device, now)
                if row['state'] != 'offline' and now - first >= OFFLINE_AFTER:
                    with self.store.connect() as db:
                        db.execute('UPDATE push_activities SET saved_state=?,saved_since=?,saved_turn=? WHERE id=?',
                                   (row['state'], row['since'], row['turn'], row['id']))
                    await self.update_island(row, 'offline', int(first), row['turn'] or int(first), alert=False, priority=10)
                elif row['state'] == 'offline' and now - first >= OFFLINE_END_AFTER:
                    if await self.end_island(row, int(now) + 3600, 'offline'):
                        with self.store.connect() as db:
                            db.execute('DELETE FROM push_activities WHERE id=?', (row['id'],))
        for row in rows:
            if row['state'] in ('done', 'failed') and now - (row['since'] or now) >= END_AFTER:
                if await self.end_island(row, int(now)):
                    with self.store.connect() as db:
                        db.execute('DELETE FROM push_activities WHERE id=?', (row['id'],))

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
