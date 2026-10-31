"""遥应's own notifications on the iPhone, through Apple's push service (APNs), sent by this relay (10-26).

The iPhone app, signed in, registers the push token iOS gave it (POST /account/push/register). The token belongs to
the account, not to the sign-in, so it keeps working after a 7-day sign-in runs out (relay_accounts TTL); signing out
removes it, and a new password removes all of an account's phones. While an account has a phone, the relay keeps a
stream open to each of its connected computers: GET /api/notify/push through the tunnel (notify.py, ntfy_feed.py),
which says only which app, which conversation and what happened. The relay writes the words itself, "Claude · 我的
电脑" over "有个对话好了", and hands them to Apple for each of the account's phones. A tap opens that conversation in
the app, which checks the account and the computer first.

10-28 (user's choice) a notice also carries the conversation's title, as its first line, and the app's category that
groups a computer's notices into one stack. Apple then sees the title too; the conversation's words and commands
still never leave the computer. This is the same exception the island's long-press list already has (README 0.6.2,
handoff 1).

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
LANGS = ('zh-Hans', 'en')
WORDS = {'done': '有个对话好了', 'failed': '有个对话出错停了', 'waiting': '有个对话在等你处理'}
ISLAND_STATES = ('working', 'waiting', 'done', 'failed', 'offline', 'limited')
ISLAND_FIELDS = ('ask', 'askType', 'choices', 'askText', 'askOptions', 'step', 'resets', 'working', 'waiting', 'ended',
                 'more')
ISLAND_RELEVANCE = {'waiting': 100, 'limited': 90, 'failed': 80, 'offline': 60, 'working': 50, 'done': 10}
ISLAND_GAP = 10                 # seconds between two pushes to one island; a burst merges into the latest (0.6.4 fix)
ISLAND_PER_HOUR = 600           # a safety valve, not a drop: past this, pushes wait and merge (0.6.4 fix)
REMOTE_AFTER = 60               # a turn running this long gets an island started from afar
START_HOLD = 30 * 60            # 0.6.6: a start from afar that went out is not sent again until its island reports in
CALM_CHAT = 5 * 60              # 0.6.6: a conversation that just opened the island changes it quietly for this long
CALM_DONE = 60                  # 0.6.6: after the island opened for anything, a done this soon changes it quietly
OFFLINE_AFTER = 60              # a computer gone this long turns its islands grey
OFFLINE_END_AFTER = 30 * 60     # gone this long ends them; the lock screen keeps one an hour
END_AFTER = 2 * 60              # done or failed islands end this long after the state began (0.6.4: was 5 min)
ISLAND_REFRESH = 10 * 60        # a working island is pushed again this often, so 可能不是最新 never shows
STEP_GAP = 15                   # seconds between two progress updates of one conversation (0.6.4)
SNAPSHOT_MISSES = 2             # snapshots without a working conversation before it is taken as gone
GONE_REASONS = ('BadDeviceToken', 'DeviceTokenNotForTopic', 'Unregistered', 'ExpiredToken')
KEEP = {'done': 86400, 'failed': 86400, 'waiting': 3 * 86400}  # how long Apple holds one for a phone that is away
PHONES = 10                 # an account's phones; the one not seen for longest makes way for a new one
PER_CHAT = 60               # seconds between two notices of one kind for one conversation
PER_HOUR = 30               # notices an account gets in an hour
RING_GAP = 10               # seconds in which an account's events make one sound only (user 10-28)
NOTICE_CATEGORY = 'teleply.conversation'   # the app registers it: its group summary reads 还有 N 个对话
SWEEP = 10                  # seconds between looks at which computers to listen to (user 10-28: faster islands)
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
        if value is not None and not (key == 'step' and value == ''):
            content[key] = value
    if extra.get('peers') is not None:  # the long-press list (user 10-28: titles in the island)
        content['peers'] = extra['peers']
    return content


def island_gone(status, reason):
    """Apple says this token is dead: the island is dropped and its update falls back to a notice."""
    return status == 410 or (status == 400 and reason in GONE_REASONS)


def chat_tail(chat):
    """The last six characters of a conversation's id, for a log line that says which one without its title."""
    return '…' + str(chat)[-6:]


def language_of(value):
    """The two languages 0.6.5 sends; anything else reads English."""
    return 'en' if str(value or '').lower().startswith('en') else 'zh-Hans'


def english(value):
    return language_of(value) == 'en'


def used_text(turn, now, language='zh-Hans'):
    """'用了 6 分钟' or 'Took 6 min' for a turn that took a minute or more; '' when shorter or unknown."""
    try:
        turn = int(turn)
        seconds = int(now) - turn
    except (TypeError, ValueError):
        return ''
    if turn <= 0 or seconds < 60:
        return ''
    minutes = seconds // 60
    if minutes < 60:
        return f'Took {minutes} min' if english(language) else f'用了 {minutes} 分钟'
    hours, rest = divmod(minutes, 60)
    if english(language):
        return f'Took {hours} hr' + (f' {rest} min' if rest else '')
    return f'用了 {hours} 小时' + (f' {rest} 分钟' if rest else '')


def notice_body(kind, turn, now, ended=0, language='zh-Hans'):
    """A notice's body in the phone's language (0.6.5)."""
    if kind == 'waiting':
        return 'Waiting for you' if english(language) else '在等你选'
    if kind == 'failed':
        return 'Failed' if english(language) else '出错停了'
    used = used_text(turn, ended or now, language)
    done = 'Done' if english(language) else '好了'
    return done + (f' · {used}' if used else '')


def alert_text(raw, language='zh-Hans'):
    """The island's alert body in the phone's language; conversation titles never pass through here."""
    if not english(language):
        return raw
    exact = {'在等你选': 'Waiting for you', '出错停了': 'Failed', '开始干活了': 'Work started',
             '有个对话好了': 'A conversation is done', '有个对话出错停了': 'A conversation failed',
             '有个对话在等你处理': 'A conversation is waiting for you', '好了': 'Done'}
    if raw in exact:
        return exact[raw]
    m = re.fullmatch(r'好了 · 用了 (\d+) 分钟', raw)
    if m:
        return f'Done · Took {m.group(1)} min'
    m = re.fullmatch(r'好了 · 用了 (\d+) 小时(?: (\d+) 分钟)?', raw)
    if m:
        return f'Done · Took {m.group(1)} hr' + (f' {m.group(2)} min' if m.group(2) else '')
    return raw


def notice_title(title, app, label):
    """A notice's first line: the conversation's title, or the fallback when the computer has none (user 10-28)."""
    title = (title or '').strip()
    if title in ('', '（无标题）'):
        return f'{APPS.get(app, "")} · {label}'
    return title


def notice_thread(device):
    """thread-id: one stack for every notice of one computer. A new notice of a conversation replaces the old one."""
    return hashlib.sha256(device.encode()).hexdigest()[:24]


def notice_collapse(device, app, chat):
    """apns-collapse-id: one conversation keeps one row (user 10-28)."""
    return hashlib.sha256(f'{device}|{app}|{chat}'.encode()).hexdigest()[:24]


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
        self.rang = {}              # account -> when something last made a sound (RING_GAP)
        self.starts = {}            # (computer, app, conversation) -> when the turn began, for a remote start
        self.away = {}              # computer -> when it was first missed, for 断开了
        self.seen = set()           # computers seen connected since this relay started
        self.island_last = {}       # island id -> when it was last pushed (ISLAND_GAP)
        self.island_hours = {}      # account -> when its island pushes of the last hour went
        self.fresh_islands = set()  # islands registered just now: their computer's state is pushed once (0.6.3)
        self.snapshot_misses = {}   # (device, app, chat) -> snapshots in a row without it (0.6.4)
        self.island_refreshed = {}  # island id -> when it was last pushed without a change
        self.start_tried = {}       # (device, app, chat) -> when a remote start was last tried
        self.start_sent = {}        # computer -> when a remote start went out, until its island registers (0.6.6)
        self.popped = {}            # (device, app, chat) -> when it last opened the island with a sound (0.6.6)
        self.step_last = {}         # (device, app, chat) -> when its last progress push went (STEP_GAP)
        self.pending = {}           # island id -> the latest content waiting for its 10-second turn
        self.sent_content = {}      # island id -> canonical content last sent, to skip unchanged snapshots
        self.pump_task = None
        self.pump_lock = None       # made in start(), on the service's loop
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
        if action == 'island-state':
            return self.island_summary(owner, data)
        raise web.HTTPNotFound()

    def register(self, owner, data):
        token = data.get('token', '').strip().lower()
        platform, environment = data.get('platform', 'ios'), data.get('environment', 'production')
        label, version = data.get('label', '').strip()[:40] or 'iPhone', data.get('version', '').strip()[:20]
        language = language_of(data.get('language'))
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
                db.execute('UPDATE push_phones SET owner=?,platform=?,environment=?,label=?,version=?,refreshed=?,'
                           'language=? WHERE id=?', (owner, platform, environment, label, version, now, language, row['id']))
                return
            stale = db.execute('SELECT id FROM push_phones WHERE owner=? ORDER BY refreshed DESC LIMIT -1 OFFSET ?',
                               (owner, PHONES - 1)).fetchall()
            db.executemany('DELETE FROM push_phones WHERE id=?', [(r['id'],) for r in stale])
            db.execute('INSERT INTO push_phones VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (secrets.token_hex(16), owner, platform, environment, token, label, version, now, now, '', language))

    async def test(self, owner, token):
        with self.store.connect() as db:
            phone = db.execute('SELECT * FROM push_phones WHERE owner=? AND token=?', (owner, token)).fetchone()
        if not phone:
            raise ValueError('这部手机还没登记遥应通知，请重新打开')
        lang = language_of(phone['language'])
        payload = {'aps': {'alert': {'title': 'Teleply' if english(lang) else '遥应',
                                     'body': 'Test notification. Notifications are working.' if english(lang)
                                     else '试推一条：通知是好的'}, 'sound': 'default'}}
        status, reason = await self.send(dict(phone), payload, '', self.clock() + 600)
        if status == 200:
            return {'ok': True, 'text': 'Sent. Check your notifications.' if english(lang) else '刚推了一条，看看通知'}
        if status in (400, 410) and reason in ('BadDeviceToken', 'DeviceTokenNotForTopic', 'Unregistered', 'ExpiredToken'):
            raise ValueError('这部手机的推送令牌已失效，请重新打开遥应通知')
        raise ValueError('苹果没收下这条通知：' + (reason or f'HTTP {status}' if status else '连不上苹果的推送服务'))

    # -- 灵动岛 (handoff 5.3, 阶段零)

    def activity(self, owner, data):
        """One island's push token. 0.6.3: one island per computer, its app and chat empty; an older phone still
        registers one per conversation, which stays supported. op=unregister forgets it."""
        op = str(data.get('op', 'register'))
        token = str(data.get('token', '')).strip().lower()
        device = str(data.get('device', '')).strip().lower()
        app, chat = data.get('app', ''), data.get('chat', '')
        environment = data.get('environment', 'production')
        title = str(data.get('title', '')).strip()[:200]
        language = language_of(data.get('language'))
        if op not in ('register', 'unregister'):
            raise ValueError('不认识的操作')
        if not TOKEN.fullmatch(token):
            raise ValueError('岛的推送令牌无效')
        if not re.fullmatch(r'[0-9a-f]{32}', device):
            raise ValueError('电脑标识无效')
        computer_island = not app and not chat  # 0.6.3: the island of a whole computer
        if not computer_island and (app not in APPS or not isinstance(chat, str) or not 0 < len(chat) <= 200):
            raise ValueError('岛的内容无效')
        if environment not in HOSTS:
            raise ValueError('推送环境无效')
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM devices WHERE id=? AND owner=? AND revoked=0', (device, owner)).fetchone():
                raise ValueError('这台电脑不属于这个账号')
            if op == 'unregister':
                db.execute('DELETE FROM push_activities WHERE owner=? AND token=?', (owner, token))
                return {'ok': True}
            if computer_island:
                app, chat, title = '', '', ''
                # 0.6.3 upgrade: the conversations' own islands from 0.6.2 are replaced by this one.
                db.execute('DELETE FROM push_activities WHERE owner=? AND device=? AND (app!="" OR chat!="")',
                           (owner, device))
            state = data.get('state', 'working')
            state = state if state in ISLAND_STATES else 'working'
            now = self.clock()
            try:
                since, turn = int(data.get('since') or now), int(data.get('turn') or now)
            except (TypeError, ValueError):
                raise ValueError('岛的时间无效')
            row = db.execute('SELECT id,title FROM push_activities WHERE token=?', (token,)).fetchone()
            if row:  # the same island registered again (its token does not change)
                db.execute('UPDATE push_activities SET owner=?,device=?,app=?,chat=?,environment=?,state=?,since=?,'
                           'turn=?,title=?,refreshed=?,language=? WHERE id=?',
                           (owner, device, app, chat, environment, state, since, turn,
                            title or (row['title'] or ''), now, language, row['id']))
            else:
                db.execute('INSERT INTO push_activities (id,owner,device,app,chat,token,environment,state,since,turn,'
                           'created,refreshed,result,title,language) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (secrets.token_hex(16), owner, device, app, chat, token, environment, state, since, turn,
                            now, now, '', title, language))
            if computer_island:  # catch up at once: a done may have come before this island's token did
                kept = db.execute('SELECT id FROM push_activities WHERE token=?', (token,)).fetchone()
                if kept:
                    self.fresh_islands.add(kept['id'])
                self.start_sent.pop(device, None)  # the island reported in: a later one may be started again
        if computer_island:
            self.wake()
        return {'ok': True}

    def start_token(self, owner, data):
        """A phone's push-to-start token (remote-started islands, iOS 18): one row per token."""
        token = str(data.get('token', '')).strip().lower()
        environment = data.get('environment', 'production')
        language = language_of(data.get('language'))
        if not TOKEN.fullmatch(token):
            raise ValueError('推送令牌无效')
        if environment not in HOSTS:
            raise ValueError('推送环境无效')
        with self.store.connect() as db:
            db.execute('INSERT INTO push_start(token,owner,environment,refreshed,language) VALUES (?,?,?,?,?) '
                       'ON CONFLICT(token) DO UPDATE SET owner=excluded.owner,environment=excluded.environment,'
                       'refreshed=excluded.refreshed,language=excluded.language',
                       (token, owner, environment, self.clock(), language))
        return {'ok': True}

    def island_summary(self, owner, data):
        """The summary the phone can apply itself when it comes to the front (0.6.5), without spending a push."""
        device = str(data.get('device', '')).strip().lower()
        if not re.fullmatch(r'[0-9a-f]{32}', device):
            raise ValueError('电脑标识无效')
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM devices WHERE id=? AND owner=? AND revoked=0',
                              (device, owner)).fetchone():
                raise ValueError('这台电脑不属于这个账号')
        now = self.clock()
        agg = self.aggregate(device, now)
        return {'ok': True, 'content-state': island_state(agg['state'], agg['since'], agg['turn'],
                                                          peers=agg['peers'], working=agg['working'],
                                                          waiting=agg['waiting'], step=agg.get('step'),
                                                          ended=agg.get('ended') or None, more=agg.get('more'))}

    async def island_test(self, owner, data):
        """One update to an island this account registered, so the app can prove the key may send the topic 3.5
        could not settle with a made-up phone. It only ever says 好了."""
        device = str(data.get('device', '')).strip().lower()
        with self.store.connect() as db:
            row = db.execute('SELECT a.*, d.label FROM push_activities a JOIN devices d ON d.id=a.device '
                             'WHERE a.owner=? AND a.device=? ORDER BY a.refreshed DESC LIMIT 1',
                             (owner, device)).fetchone()
        if not row:
            raise ValueError('先在这部手机上开一个岛，再点这个。')
        now = int(self.clock())
        lang = language_of(row['language'] if 'language' in row.keys() else 'zh-Hans')
        payload = {'aps': {'timestamp': now, 'event': 'update',
                           'content-state': island_state('done', now, row['turn'] or now, ended=now),
                           'relevance-score': 10,
                           'alert': {'title': f'{APPS[row["app"]]} · {row["label"]}',
                                     'body': 'Done' if english(lang) else '好了', 'sound': 'default'}}}
        status, reason = await self.send_island(dict(row), payload)
        if status == 200:
            with self.store.connect() as db:
                db.execute('UPDATE push_activities SET state=?,since=?,refreshed=? WHERE id=?',
                           ('done', now, self.clock(), row['id']))
            return {'ok': True, 'text': 'Sent. The Live Activity should show a checkmark now.' if english(lang)
                    else '中转推了一条，岛应该变成 ✓ 了'}
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
            self.pump_lock = asyncio.Lock()
            self.task = asyncio.create_task(self.sweep())
            self.pump_task = asyncio.create_task(self.island_loop())

    async def stop(self, app=None):
        tasks = [t for t in [self.task, self.pump_task, *self.watchers.values()] if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.task, self.pump_task, self.watchers = None, None, {}
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
        if kind == 'snapshot':  # 0.6.4: what a restarted relay missed
            await self.snapshot(device, event)
            return
        if kind not in (*WORDS, 'running', 'step') or app not in APPS or not isinstance(chat, str) or not 0 < len(chat) <= 200:
            return
        now = self.clock()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM push_events WHERE time<?', (now - 7 * 86400,))
            fresh = db.execute('INSERT OR IGNORE INTO push_events VALUES (?,?)', (device + ':' + event['id'], now)).rowcount
            computer = db.execute('SELECT owner,label FROM devices WHERE id=? AND revoked=0', (device,)).fetchone()
            islands, legacy = [], None
            if computer:
                islands = [dict(r) for r in db.execute(
                    'SELECT a.*, d.label FROM push_activities a JOIN devices d ON d.id=a.device '
                    'WHERE a.device=? AND a.app="" AND a.chat=""', (device,))]
                legacy = db.execute('SELECT a.*, d.label FROM push_activities a JOIN devices d ON d.id=a.device '
                                    'WHERE a.device=? AND a.app=? AND a.chat=? ORDER BY a.refreshed DESC LIMIT 1',
                                    (device, app, chat)).fetchone()
            phones = [dict(r) for r in db.execute('SELECT * FROM push_phones WHERE owner=?', (computer['owner'],))] if computer else []
        if not fresh or not computer:
            return
        owner, conv = computer['owner'], (device, app, chat)
        quiet = bool(event.get('quiet'))  # the phone has this conversation open: no banner, but the island still changes
        title = str(event.get('title', '')).strip()[:200]
        if kind == 'step':  # 方案六: progress, priority 5, never a banner, never a record, at most every STEP_GAP
            action = str(event.get('step') or '')
            if action not in ('edit', 'run', 'search', 'read'):
                return
            if now - self.step_last.get(conv, -STEP_GAP) < STEP_GAP:
                return
            self.step_last[conv] = now
            since, turn, started, ended, source = self.remember_step(owner, device, app, chat, action, title, now)
            if islands:
                agg = self.aggregate(device, now)
                for row in islands:
                    await self.update_island(row, agg['state'], agg['since'], agg['turn'], alert=False, priority=5,
                                             working=agg['working'], waiting=agg['waiting'], peers=agg['peers'],
                                             step=agg.get('step'), ended=agg.get('ended'), more=agg.get('more'))
                self.decided(kind, app, chat, '岛静默', f'动作变成 {action}', started=started, ended=now, source=source)
            elif legacy:
                await self.update_island(dict(legacy), 'working', since, turn, alert=False, priority=5, step=action)
                self.decided(kind, app, chat, '岛静默', f'动作变成 {action}', started=started, ended=now, source=source)
            return
        state, since, turn, started, ended, source = self.remember(owner, device, app, chat, kind, event, title, now)
        if islands:  # 0.6.3: one island for the whole computer, its counts and list built from every conversation
            if kind in ('done', 'failed'):
                # The record goes in at once (user 10-28): the island can stay up for the computer's other work.
                await self.notice(owner, device, app, chat, kind, computer['label'], phones, now, turn, title,
                                  loud=False, force=True, ended=ended)
            if kind == 'running':
                self.starts[conv] = {'since': since, 'title': title}
            loud = self.may_pop(owner, conv, kind, now) and not quiet
            calmed = self.calm(owner, conv, kind, now) if not quiet else ''
            agg = self.aggregate(device, now, last_kind=kind)
            state_change = kind in ('running', 'waiting', 'done', 'failed')
            async def fallback_notice():
                loud2 = self.may_ring(owner, now)
                went, why = await self.notice(owner, device, app, chat, kind, computer['label'], phones, now, turn,
                                              title, loud2, ended=ended)
                if went and loud2:
                    self.rang[owner] = now
                self.decided(kind, app, chat, ('通知响' if loud2 else '通知静默') if went else '不发',
                             '电脑岛的令牌失效了，改发通知；' + why, started=started, ended=ended, source=source)

            took = False
            for row in islands:
                status = await self.update_island(row, agg['state'], agg['since'], agg['turn'], alert=loud,
                                                  priority=10 if state_change else 5, force=state_change,
                                                  working=agg['working'], waiting=agg['waiting'], peers=agg['peers'],
                                                  step=agg.get('step'), ended=agg.get('ended'), more=agg.get('more'),
                                                  alert_title=notice_title(title, app, computer['label']),
                                                  alert_body=notice_body(kind, turn, now, ended),
                                                  fallback=fallback_notice if not quiet else None)
                took = status in ('sent', 'queued', 'same') or took
            if loud and took:
                self.rang[owner] = now
                self.popped[conv] = now
            if not took and kind != 'running' and not quiet:  # every island's token is dead: the notice is the only word
                loud = self.may_ring(owner, now)
                went, why = await self.notice(owner, device, app, chat, kind, computer['label'], phones, now, turn,
                                              title, loud, ended=ended)
                if went and loud:
                    self.rang[owner] = now
                self.decided(kind, app, chat, ('通知响' if loud else '通知静默') if went else '不发',
                             '电脑岛的令牌失效了，改发通知；' + why, started=started, ended=ended, source=source)
                return
            if kind != 'running':
                self.starts.pop(conv, None)
            route = '通知静默' if kind in ('done', 'failed') else '岛静默' if kind == 'running' or not loud else '岛提醒'
            self.decided(kind, app, chat, route,
                         f'这台电脑的岛按汇总更新（{agg["working"]} 个工作中、{agg["waiting"]} 个等你定）'
                         + (f'，{calmed}，岛不弹' if calmed else '') + ('，岛弹一下' if loud and took else ''),
                         started=started, ended=ended, source=source)
            return
        if kind == 'running':
            self.starts[conv] = {'since': since, 'title': title}
            if legacy and now - since < 12 * 3600:  # a 0.6.2 phone's island for this one conversation
                legacy = dict(legacy)
                await self.update_island(legacy, 'working', since, legacy['turn'] or since, alert=False, priority=10,
                                         force=True, step=event.get('step'))
                self.decided(kind, app, chat, '岛静默', '在干活，只改 0.6.2 的旧岛，不带提醒',
                             started=started, ended=ended, source=source)
            else:
                self.decided(kind, app, chat, '不发', '在干活还没岛，跑过一分钟再远程开',
                             started=started, ended=ended, source=source)
            return
        self.starts.pop(conv, None)
        fallback = ''
        if legacy:  # a 0.6.2 phone still has one island per conversation
            loud = self.may_pop(owner, conv, kind, now) and not quiet
            turn = int(legacy['turn'] or turn or now)
            status = await self.update_island(legacy, state, ended or int(now), turn, alert=loud,
                                              priority=10, force=True, step=event.get('step'), ended=ended)
            if status in ('sent', 'queued', 'same'):
                if loud:
                    self.rang[owner] = now
                    self.popped[conv] = now
                self.decided(kind, app, chat, '岛提醒' if loud else '岛静默', self.why_island(quiet, loud),
                             started=started, ended=ended, source=source)
                return
            fallback = '岛的令牌失效了，改发通知；'
        if quiet:
            self.decided(kind, app, chat, '不发', fallback + '手机正开着这个对话，也没有岛',
                         started=started, ended=ended, source=source)
            return
        loud = self.may_ring(owner, now)
        went, why = await self.notice(owner, device, app, chat, kind, computer['label'], phones, now, turn, title, loud,
                                      ended=ended)
        if went and loud:
            self.rang[owner] = now
        self.decided(kind, app, chat, ('通知响' if loud else '通知静默') if went else '不发', fallback + why,
                     started=started, ended=ended, source=source)

    @staticmethod
    def _moment(value, fallback=0):
        try:
            number = int(value)
            return number if number > 0 else int(fallback or 0)
        except (TypeError, ValueError):
            return int(fallback or 0)

    def remember(self, owner, device, app, chat, kind, event, title, now):
        """One conversation's latest state and the record's own times (0.6.4). Returns state, since, turn, started,
        ended, started_source; the fallbacks keep an older computer working."""
        state = {'running': 'working', 'waiting': 'waiting', 'done': 'done', 'failed': 'failed'}[kind]
        with self.store.connect() as db:
            db.execute('DELETE FROM push_conversations WHERE refreshed<?', (now - 86400,))
            row = db.execute('SELECT turn,ended,title,step,started_source FROM push_conversations '
                             'WHERE device=? AND app=? AND chat=?', (device, app, chat)).fetchone()
            old_turn = int(row['turn'] or 0) if row else 0
            old_source = (row['started_source'] or '') if row else ''
            started = self._moment(event.get('started'), event.get('since') if kind == 'running' else old_turn)
            ended = self._moment(event.get('ended'), now if kind in ('done', 'failed') else 0)
            source = str(event.get('started_source') or '').strip() or old_source
            if kind == 'running':
                since = self._moment(event.get('since'), started or now)
                started = since
                ended, turn, step = 0, since, str(event.get('step') or (row['step'] if row else '') or '')
                action_at = since
                source = source or '不知道'
            elif kind == 'waiting':
                since = int(now)
                turn = started or old_turn or int(now)
                started, ended = turn, 0
                step = str(event.get('step') or (row['step'] if row else '') or '')
                action_at = int(now)
                source = source or '不知道'
            else:
                ended = ended or int(now)
                started = started or old_turn or ended
                since, turn, step = ended, started, ''
                action_at = 0
                source = source or ('记录' if old_turn else '不知道')
            title = title or (row['title'] if row else '') or ''
            if row:
                db.execute('UPDATE push_conversations SET owner=?,title=?,state=?,since=?,turn=?,refreshed=?,'
                           'ended=?,step=?,started_source=?,action_at=? WHERE device=? AND app=? AND chat=?',
                           (owner, title or '', state, since, turn, now, ended, step, source, action_at,
                            device, app, chat))
            else:
                db.execute('INSERT INTO push_conversations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (device, app, chat, owner, title or '', state, since, turn, now, ended, step, source,
                            action_at))
        return state, since, turn, started, ended, source

    def remember_step(self, owner, device, app, chat, action, title, now):
        """A progress event changes only the action; the turn and its times stay (0.6.4)."""
        with self.store.connect() as db:
            row = db.execute('SELECT since,turn,ended,started_source FROM push_conversations '
                             'WHERE device=? AND app=? AND chat=?', (device, app, chat)).fetchone()
            if not row:
                return int(now), int(now), int(now), 0, '不知道'
            db.execute('UPDATE push_conversations SET owner=?,step=?,refreshed=?,action_at=?,'
                       'title=CASE WHEN ?!="" THEN ? ELSE title END WHERE device=? AND app=? AND chat=?',
                       (owner, action, now, int(now), title or '', title or '', device, app, chat))
            return int(row['since'] or now), int(row['turn'] or now), int(row['turn'] or now), int(row['ended'] or 0), \
                (row['started_source'] or '不知道')

    async def snapshot(self, device, event):
        """A computer's running and waiting conversations, every 60 s (0.6.4). Fills in what a restarted relay missed;
        a working conversation absent from two snapshots in a row is taken as no longer running, silently."""
        items = event.get('items')
        if not isinstance(items, list):
            return
        now = self.clock()
        with self.store.connect() as db:
            computer = db.execute('SELECT owner,label FROM devices WHERE id=? AND revoked=0', (device,)).fetchone()
            if not computer:
                return
            owner = computer['owner']
            islands = [dict(r) for r in db.execute(
                'SELECT a.*, d.label FROM push_activities a JOIN devices d ON d.id=a.device '
                'WHERE a.device=? AND a.app="" AND a.chat=""', (device,))]
            seen = set()
            for item in items[:100]:
                if not isinstance(item, dict):
                    continue
                app, chat = item.get('app'), item.get('chat')
                state = item.get('state')
                if app not in APPS or not isinstance(chat, str) or not 0 < len(chat) <= 200 or state not in ('working', 'waiting'):
                    continue
                started = self._moment(item.get('started'), item.get('since') or now)
                since = started if state == 'working' else int(now)
                step = str(item.get('step') or '')
                if step not in ('edit', 'run', 'search', 'read'):
                    step = ''
                title = str(item.get('title') or '').strip()[:200]
                row = db.execute('SELECT title FROM push_conversations WHERE device=? AND app=? AND chat=?',
                                 (device, app, chat)).fetchone()
                if row:
                    db.execute('UPDATE push_conversations SET owner=?,title=?,state=?,since=?,turn=?,refreshed=?,'
                               'ended=0,step=?,started_source="记录",action_at=? WHERE device=? AND app=? AND chat=?',
                               (owner, title or (row['title'] or ''), state, since, started, now, step,
                                started if state == 'working' else now, device, app, chat))
                else:
                    db.execute('INSERT INTO push_conversations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (device, app, chat, owner, title, state, since, started, now, 0, step, '记录',
                                started if state == 'working' else now))
                seen.add((app, chat))
            active = [dict(r) for r in db.execute(
                'SELECT app,chat,state FROM push_conversations WHERE device=? AND state IN ("working","waiting")',
                (device,))]
            for row in active:
                key = (row['app'], row['chat'])
                if key in seen:
                    self.snapshot_misses.pop((device, *key), None)
                    continue
                if row['state'] == 'waiting':  # a waiting turn stays until its own event says otherwise
                    continue
                misses = self.snapshot_misses.get((device, *key), 0) + 1
                self.snapshot_misses[(device, *key)] = misses
                if misses >= SNAPSHOT_MISSES:
                    db.execute('UPDATE push_conversations SET state="gone",refreshed=?,step="" '
                               'WHERE device=? AND app=? AND chat=?', (now, device, *key))
                    self.snapshot_misses.pop((device, *key), None)
            for conv in list(self.snapshot_misses):
                if conv[0] == device and (conv[1], conv[2]) in seen:
                    self.snapshot_misses.pop(conv, None)
        if islands:
            agg = self.aggregate(device, now)
            for row in islands:
                await self.update_island(row, agg['state'], agg['since'], agg['turn'], alert=False, priority=10,
                                         working=agg['working'], waiting=agg['waiting'], peers=agg['peers'],
                                         step=agg.get('step'), ended=agg.get('ended'), more=agg.get('more'))
        log.info('push: snapshot %s -> %s 个在干活/等你', chat_tail(device), len(seen))

    def aggregate(self, device, now, last_kind=''):
        """A computer island's changing part: how many conversations work, how many wait, and the few the list shows.
        0.6.4: with nothing running, the one that just finished stays as the card's title and real 用时."""
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute(
                'SELECT app,chat,title,state,since,turn,ended,step FROM push_conversations WHERE device=? '
                'AND state IN ("working","waiting") ORDER BY CASE state WHEN "waiting" THEN 0 ELSE 1 END, '
                'COALESCE(NULLIF(action_at,0),turn) DESC, refreshed DESC', (device,))]
            last = None
            if not rows:
                last = db.execute(
                    'SELECT app,chat,title,state,since,turn,ended,step FROM push_conversations WHERE device=? '
                    'AND state IN ("done","failed") ORDER BY refreshed DESC LIMIT 1', (device,)).fetchone()
                last = dict(last) if last else None
        working = sum(1 for r in rows if r['state'] == 'working')
        waiting = len(rows) - working
        if waiting:
            state = 'waiting'
        elif working:
            state = 'working'
        elif last:
            state = last['state']
        else:
            state = 'failed' if last_kind == 'failed' else 'done'
        step, ended = '', 0
        if rows:
            if len(rows) == 1:  # one conversation: the card keeps its own timer and state
                since, turn = int(rows[0]['since']), int(rows[0]['turn'])
                step = rows[0].get('step') or ''
            else:
                since, turn = int(now), int(now)
            peers = [{'app': r['app'], 'chat': r['chat'], 'title': (r['title'] or '')[:40], 'state': r['state'],
                      'since': int(r['since']), 'turn': int(r['turn']), 'ended': int(r.get('ended') or 0),
                      'step': r.get('step') or ''} for r in rows[:3]]
            more = max(0, len(rows) - len(peers))
        elif last:  # nothing runs: the card says which one finished, with the record's own times
            since, turn, ended = int(last['since']), int(last['turn']), int(last['since'])
            peers = [{'app': last['app'], 'chat': last['chat'], 'title': (last['title'] or '')[:40],
                      'state': last['state'], 'since': int(last['since']), 'turn': int(last['turn']),
                      'ended': int(last['since']), 'step': ''}]
            more = 0
        else:
            since, turn = int(now), int(now)
            peers, more = [], 0
        return {'state': state, 'since': since, 'turn': turn, 'working': working, 'waiting': waiting,
                'peers': peers, 'ended': ended, 'step': step, 'more': more}

    def may_ring(self, owner, now):
        """One sound an account in RING_GAP seconds (user 10-28): the first of a burst rings, the rest are silent."""
        last = self.rang.get(owner)
        return last is None or now - last >= RING_GAP

    def calm(self, owner, conv, kind, now):
        """Why this done changes the island quietly instead of opening it, or '' (0.6.6, user 10-31: the island opened
        too often). A conversation that opened it CALM_CHAT ago or less is mostly a quick follow-up turn (three in one
        minute on 10-31); any opening CALM_DONE ago or less already brought the user to the phone. Asking and failing
        still open it, with RING_GAP only."""
        if kind != 'done':
            return ''
        if now - self.popped.get(conv, -CALM_CHAT) < CALM_CHAT:
            return '这个对话五分钟内刚让岛弹过'
        if now - self.rang.get(owner, -CALM_DONE) < CALM_DONE:
            return '一分钟内岛刚弹过'
        return ''

    def may_pop(self, owner, conv, kind, now):
        """Whether this event opens the island with a sound: only done, failed and waiting ever do, never running or a
        step (0.6.6)."""
        return kind in WORDS and self.may_ring(owner, now) and not self.calm(owner, conv, kind, now)

    def why_island(self, quiet, loud):
        if quiet:
            return '手机正开着这个对话，岛静默改状态'
        if not loud:
            return f'{RING_GAP} 秒内刚响过，岛静默改状态'
        return '有岛，只改岛，不发普通通知'

    def decided(self, kind, app, chat, route, why, started=0, ended=0, source=''):
        """One line per decision, for a later 响了两次 (user 10-28): no title, only the end of the conversation's id.
        0.6.4 adds how long the turn took and where its start came from (记录 / 电脑注意到 / 不知道)."""
        used = used_text(started, ended or self.clock()) if started else ''
        timing = f'用时 {used}' if used else '用时 不到一分钟或不知道'
        log.info('push: %s %s %s -> %s (%s; %s; 开始 %s)', kind, app, chat_tail(chat), route, why, timing,
                 source or '不知道')

    async def notice(self, owner, device, app, chat, kind, label, phones, now, turn=0, title='', loud=True, force=False,
                     ended=0):
        """A normal notification on the lock screen: the conversation's title over 模型 · 电脑 over the state (user
        10-28), one stack per computer and one row per conversation. Only for a conversation without a working island,
        and never while the phone shows it. [force] is the computer island's record, which skips the per-chat hold.
        Says whether it went, and why it did not or why it was silent."""
        if not phones:
            return False, '这个账号没有登记的手机'
        if not force and now - self.sent.get((device, app, chat, kind), -PER_CHAT) < PER_CHAT:
            return False, '同一对话同一种事一分钟内已经发过'
        hour = [t for t in self.hours.get(owner, []) if now - t < 3600]
        if not force and len(hour) >= PER_HOUR:
            self.hours[owner] = hour
            return False, '这个账号一小时的通知到上限了'
        if not force:
            self.hours[owner] = hour + [now]
        self.sent = {k: t for k, t in self.sent.items() if now - t < PER_CHAT}
        self.sent[(device, app, chat, kind)] = now
        fallback = f'{APPS[app]} · {label}'
        collapse = notice_collapse(device, app, chat)
        for phone in phones:
            lang = language_of(phone.get('language'))
            aps = {'alert': {'title': notice_title(title, app, label), 'subtitle': fallback,
                             'body': notice_body(kind, turn, now, ended, lang)},
                   'thread-id': notice_thread(device), 'category': NOTICE_CATEGORY}
            if loud:
                aps['sound'] = 'default'
            else:
                aps['interruption-level'] = 'passive'
            payload = {'aps': aps, 'teleply': {'d': device, 'a': app, 'c': chat}}
            await self.send(phone, payload, collapse, now + KEEP[kind], priority=10 if loud else 5)
        return True, '第一件，响一次' if loud else f'{RING_GAP} 秒内刚响过，静默进通知中心'

    # -- 灵动岛's own pushes (方案一、四)

    def island_since(self, row, now):
        return int(row['since'] or now)

    def peers(self, row, state, since, turn):
        """The conversations still running on this computer, for the island's long-press list: model, title, state
        and times. The current island takes the state being pushed; finished ones drop out."""
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute(
                'SELECT id,app,chat,title,state,since,turn FROM push_activities WHERE owner=? AND device=? '
                'ORDER BY refreshed DESC', (row['owner'], row['device']))]
        peers = []
        for item in rows:
            current = item['id'] == row['id']
            status = state if current else item['state']
            if status not in ('working', 'waiting'):
                continue
            peers.append({'app': item['app'], 'chat': item['chat'],
                          'title': (row.get('title') if current else item['title']) or '',
                          'state': status,
                          'since': int(since if current else item['since']),
                          'turn': int(turn if current else item['turn']), 'ended': 0})
        return peers[:3]

    async def update_island(self, row, state, since, turn, alert, priority, clear_saved=False,
                            working=None, waiting=None, peers=None, alert_title=None, alert_body=None,
                            step=None, ended=0, force=False, refresh=False, more=None, fallback=None):
        """Queue one island update (0.6.4 fix). At most one push to an island every ISLAND_GAP seconds; a burst merges
        into the latest and the last change still goes out within 20 seconds. Returns "sent", "queued", "same" or
        "gone"; only "gone" (Apple rejected the token) means the caller must fall back to a notice."""
        row = dict(row)
        now = self.clock()
        if peers is None:
            peers = self.peers(row, state, since, turn) if row['app'] else []
        content = island_state(state, int(since), int(turn), peers=peers, working=working, waiting=waiting,
                               step=step, ended=ended or None, more=more)
        alert_payload = None
        if alert:
            alert_payload = {'title': alert_title or f'{APPS[row["app"]]} · {row["label"]}',
                             'body': alert_body or {'waiting': '有个对话在等你处理', 'done': '有个对话好了',
                                                    'failed': '有个对话出错停了'}.get(state, '有个对话好了'),
                             'sound': 'default'}
        canonical = json.dumps(content, sort_keys=True, ensure_ascii=False)
        if not refresh and canonical == self.sent_content.get(row['id']):
            return 'same'
        pending = self.pending.get(row['id'])
        if pending:
            pending.update(row=row, content=content, canonical=canonical, priority=priority,
                           alert=alert_payload or pending.get('alert'), clear_saved=clear_saved or pending['clear_saved'],
                           refresh=refresh or pending['refresh'], fallback=fallback or pending.get('fallback'))
            return 'queued'
        last = self.island_last.get(row['id'])
        due = now if last is None or now - last >= ISLAND_GAP else last + ISLAND_GAP
        item = {'row': row, 'content': content, 'canonical': canonical, 'priority': priority, 'alert': alert_payload,
                'clear_saved': clear_saved, 'refresh': refresh, 'fallback': fallback, 'due': due}
        self.pending[row['id']] = item
        if due <= now:
            return await self._flush_island(row['id'])
        return 'queued'

    async def _flush_island(self, ident):
        """Send the one latest update waiting for this island, if it is due. Never sends older content."""
        item = self.pending.get(ident)
        if item is None or item['due'] > self.clock():
            return 'queued'
        if self.pump_lock is None:
            self.pump_lock = asyncio.Lock()
        async with self.pump_lock:
            item = self.pending.pop(ident, None)
            if item is None:
                return 'queued'
            now = self.clock()
            row = item['row']
            owner = row['owner']
            hour = [t for t in self.island_hours.get(owner, []) if now - t < 3600]
            if len(hour) >= ISLAND_PER_HOUR:
                self.island_hours[owner] = hour
                item['due'] = now + 60
                self.pending[ident] = item
                log.info('push: island %s -> 合并延后（一小时安全阀已到，等一分钟再试）', chat_tail(row['device']))
                return 'queued'
            self.island_hours[owner] = hour + [now]
            content = item['content']
            payload = {'aps': {'timestamp': int(now), 'event': 'update', 'content-state': content,
                               'relevance-score': ISLAND_RELEVANCE.get(content['state'], 50)}}
            if content['state'] == 'working':
                payload['aps']['stale-date'] = int(now + 15 * 60)
            if item['alert']:
                alert = dict(item['alert'])
                alert['body'] = alert_text(alert.get('body', ''), row.get('language'))
                payload['aps']['alert'] = alert
            status, reason = await self.send_island(dict(row), payload, priority=item['priority'])
            if status == 200:
                self.sent_content[ident] = item['canonical']
                self.island_last[ident] = now
                self.island_refreshed[ident] = now
                with self.store.connect() as db:
                    if item['clear_saved']:
                        db.execute('UPDATE push_activities SET state=?,since=?,turn=?,refreshed=?,saved_state=NULL,'
                                   'saved_since=NULL,saved_turn=NULL WHERE id=?',
                                   (content['state'], int(content['since']), int(content['turn']), now, ident))
                    else:
                        db.execute('UPDATE push_activities SET state=?,since=?,turn=?,refreshed=? WHERE id=?',
                                   (content['state'], int(content['since']), int(content['turn']), now, ident))
                return 'sent'
            if island_gone(status, reason):
                self.sent_content.pop(ident, None)
                callback = item.get('fallback')
                if callback:
                    scope = ('device=? AND app="" AND chat=""' if not row['app'] else 'device=? AND app=? AND chat=?')
                    args = (row['device'],) if not row['app'] else (row['device'], row['app'], row['chat'])
                    with self.store.connect() as db:
                        other = db.execute('SELECT 1 FROM push_activities WHERE ' + scope + ' LIMIT 1', args).fetchone()
                    if not other:
                        await callback()
                return 'gone'
            item['due'] = now + 30
            self.pending[ident] = item
            log.info('push: island %s -> 合并延后（苹果没答好，三十秒后再试）', chat_tail(row['device']))
            return 'queued'

    async def flush_islands(self):
        """Send every island update whose ten seconds are up; the background loop calls this every half second."""
        for ident in list(self.pending):
            await self._flush_island(ident)

    async def island_loop(self):
        while True:
            try:
                await self.flush_islands()
            except Exception as exc:
                log.warning('push: island pump %s', type(exc).__name__)
            await asyncio.sleep(0.5)

    async def end_island(self, row, dismissal, state=None):
        """The turn is over (or the computer has been away too long): the island leaves after `dismissal`."""
        now = int(self.clock())
        payload = {'aps': {'timestamp': now, 'event': 'end',
                           'content-state': island_state(state or row['state'], row['since'] or now, row['turn'] or now,
                                                         ended=(row['since'] or now)
                                                         if (state or row['state']) in ('done', 'failed') else None),
                           'dismissal-date': int(dismissal)}}
        status, reason = await self.send_island(row, payload, priority=10)
        return status == 200

    async def remote_start(self, device, app, chat, since, computer, starts, title=''):
        """方案一: a turn on the computer has run a minute; start this computer's island from afar with the phone's
        start token (0.6.3: one island per computer, its counts and list from every conversation)."""
        now = int(self.clock())
        agg = self.aggregate(device, now)
        content = island_state(agg['state'], agg['since'], agg['turn'], peers=agg['peers'],
                               working=agg['working'], waiting=agg['waiting'], step=agg.get('step'),
                               ended=agg.get('ended') or None, more=agg.get('more'))
        sent = False
        for start in starts:
            lang = language_of(start.get('language'))
            payload = {'aps': {'timestamp': now, 'event': 'start', 'attributes-type': 'IslandAttributes',
                               'attributes': {'device': device, 'app': '', 'chat': '',
                                              'computer': computer['label'], 'title': ''},
                               'content-state': content,
                               # Apple wants an alert to start an island from afar; it carries no sound (user 10-28).
                               'alert': {'title': notice_title(title, app, computer['label']),
                                         'body': 'Work started' if english(lang) else '开始干活了'},
                               'input-push-token': 1}}
            status, reason = await self.send_live(start['environment'], start['token'], payload, priority=10)
            if status == 200:
                sent = True
            elif island_gone(status, reason):
                with self.store.connect() as db:
                    db.execute('DELETE FROM push_start WHERE token=?', (start['token'],))
        self.decided('start', app, chat, '远程开岛' if sent else '不发',
                     '跑过一分钟了，带提醒文字但不带声音' if sent else '启动令牌没能用上')
        return sent

    async def sweep_islands(self):
        """Every SWEEP seconds: remote starts, done or failed islands ending, and a computer gone grey."""
        now = self.clock()
        connected = set(self.hub.connections)
        self.seen |= connected
        with self.store.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT a.*, d.label FROM push_activities a '
                                                'JOIN devices d ON d.id=a.device')]
        aggs = {}  # device -> the computer island's counts, computed once per sweep
        for row in rows:
            # 0.6.3 upgrade and the done-before-token race: an island that just registered gets the computer's
            # current state at once, so it never stays 在干活 after the work is over.
            if row['id'] not in self.fresh_islands:
                continue
            self.fresh_islands.discard(row['id'])
            if row['app']:
                continue
            with self.store.connect() as db:
                last = db.execute('SELECT state FROM push_conversations WHERE device=? ORDER BY refreshed DESC LIMIT 1',
                                  (row['device'],)).fetchone()
            if not last:
                continue  # nothing has happened yet: the state the phone registered stays
            agg = self.aggregate(row['device'], now, last_kind=last['state'])
            aggs[row['device']] = agg
            await self.update_island(row, agg['state'], agg['since'], agg['turn'], alert=False, priority=10, force=True,
                                     working=agg['working'], waiting=agg['waiting'], peers=agg['peers'],
                                     step=agg.get('step'), ended=agg.get('ended'), more=agg.get('more'))
            log.info('push: register island %s -> 岛静默 (岛刚登记，补推这台电脑当前的状态)', chat_tail(row['device']))
        for row in rows:  # 0.6.4: a long silence on a working island still gets a fresh stale-date every 10 minutes
            if row['app'] or row['state'] != 'working':
                continue
            if now - self.island_refreshed.get(row['id'], 0) < ISLAND_REFRESH:
                continue
            agg = aggs.get(row['device']) or self.aggregate(row['device'], now)
            aggs[row['device']] = agg
            await self.update_island(row, agg['state'], agg['since'], agg['turn'], alert=False, priority=5,
                                     refresh=True, working=agg['working'], waiting=agg['waiting'], peers=agg['peers'],
                                     step=agg.get('step'), ended=agg.get('ended'), more=agg.get('more'))
            log.info('push: refresh island %s -> 岛静默 (十分钟没有变化，更新一次)', chat_tail(row['device']))
        # 0.6.4: a remote start comes from the conversations the relay knows, not from memory, so it survives a restart.
        with self.store.connect() as db:
            waiting_start = [dict(r) for r in db.execute(
                'SELECT * FROM push_conversations WHERE state="working" AND turn<=? '
                'ORDER BY refreshed DESC', (int(now) - REMOTE_AFTER,))]
        tried = set()  # 0.6.6: one start per computer a sweep, not one per running conversation
        for conv in waiting_start:
            device, app, chat = conv['device'], conv['app'], conv['chat']
            if device not in connected or device in tried:
                continue
            with self.store.connect() as db:
                island = db.execute('SELECT 1 FROM push_activities WHERE device=? AND app="" AND chat=""',
                                    (device,)).fetchone()
                computer = db.execute('SELECT owner,label FROM devices WHERE id=? AND revoked=0',
                                      (device,)).fetchone()
                starts = [dict(r) for r in db.execute('SELECT * FROM push_start WHERE owner=?',
                                                      (computer['owner'],))] if computer else []
            if island or not computer or not starts:
                continue
            # 0.6.6: Apple opens the island for every start, and one sent before has no row here until the phone hands
            # over its token (a phone the app is not running on never does): starting it again each minute opened it
            # again and again, with whatever the computer was doing at that moment (user 10-31: 运行中、跑命令…).
            if now - self.start_sent.get(device, -START_HOLD) < START_HOLD:
                continue
            key = (device, app, chat)
            if now - self.start_tried.get(key, -REMOTE_AFTER) < REMOTE_AFTER:
                continue
            self.start_tried[key] = now
            tried.add(device)
            if await self.remote_start(device, app, chat, int(conv['turn']), computer, starts, conv['title'] or ''):
                self.start_sent[device] = now
                self.starts.pop(key, None)
        for row in rows:
            device = row['device']
            agg = None
            if not row['app']:  # a computer island's counts and list (0.6.3)
                agg = aggs.get(device) or self.aggregate(device, now)
                aggs[device] = agg
            if device in connected:
                self.away.pop(device, None)
                if row['state'] == 'offline' and row['saved_state']:
                    if agg:
                        await self.update_island(row, agg['state'], agg['since'], agg['turn'], alert=False, priority=10,
                                                 force=True, clear_saved=True, working=agg['working'], waiting=agg['waiting'],
                                                 peers=agg['peers'], step=agg.get('step'), ended=agg.get('ended'),
                                                 more=agg.get('more'))
                    else:
                        await self.update_island(row, row['saved_state'], row['saved_since'] or int(now),
                                                 row['saved_turn'] or int(now), alert=False, priority=10, clear_saved=True)
                    self.decided(row['saved_state'], row['app'], row['chat'], '岛静默', '电脑连回来了，恢复原状态')
            elif device in self.seen:
                first = self.away.setdefault(device, now)
                if row['state'] != 'offline' and now - first >= OFFLINE_AFTER:
                    with self.store.connect() as db:
                        db.execute('UPDATE push_activities SET saved_state=?,saved_since=?,saved_turn=? WHERE id=?',
                                   (row['state'], row['since'], row['turn'], row['id']))
                    if agg:
                        await self.update_island(row, 'offline', int(first), row['turn'] or int(first), alert=False,
                                                 priority=10, force=True, working=agg['working'], waiting=agg['waiting'],
                                                 peers=agg['peers'], ended=agg.get('ended'), more=agg.get('more'))
                    else:
                        await self.update_island(row, 'offline', int(first), row['turn'] or int(first), alert=False, priority=10)
                    self.decided('offline', row['app'], row['chat'], '岛静默', '电脑断开超过一分钟，变灰，不响')
                elif row['state'] == 'offline' and now - first >= OFFLINE_END_AFTER:
                    if await self.end_island(row, int(now) + 3600, 'offline'):
                        with self.store.connect() as db:
                            db.execute('DELETE FROM push_activities WHERE id=?', (row['id'],))
                        self.decided('offline', row['app'], row['chat'], '不发', '断开超过半小时，收起岛，不补通知')
        for row in rows:
            if row['state'] not in ('done', 'failed') or now - (row['since'] or now) < END_AFTER:
                continue
            if row['app']:  # a 0.6.2 phone's island for one conversation: its record is left now
                if await self.end_island(row, int(now)):
                    with self.store.connect() as db:
                        phones = [dict(r) for r in db.execute('SELECT * FROM push_phones WHERE owner=?', (row['owner'],))]
                    recorded = await self.record_notice(row, phones, int(now))
                    with self.store.connect() as db:
                        db.execute('DELETE FROM push_activities WHERE id=?', (row['id'],))
                    self.decided(row['state'], row['app'], row['chat'], '通知静默' if recorded else '不发',
                                 '岛收起了，补一条静默记录' if recorded else '岛收起了，没有登记的手机')
            elif await self.end_island(row, int(now)):  # computer island: records went in as conversations finished
                with self.store.connect() as db:
                    db.execute('DELETE FROM push_activities WHERE id=?', (row['id'],))
                log.info('push: end island %s -> 不发 (电脑岛收起，记录已在对话结束时补过)', chat_tail(row['device']))

    async def record_notice(self, row, phones, now):
        """The record a finished island leaves: a silent notice in the notification centre, with the same stack and
        row as any other notice of that conversation. It never makes a sound or a banner."""
        if not phones:
            return False
        app, chat, label = row['app'], row['chat'], row['label']
        fallback = f'{APPS[app]} · {label}'
        collapse = notice_collapse(row['device'], app, chat)
        for phone in phones:
            lang = language_of(phone.get('language'))
            aps = {'alert': {'title': notice_title(row.get('title', ''), app, label), 'subtitle': fallback,
                             'body': notice_body(row['state'], row['turn'], row['since'] or now, row['since'] or now,
                                                 lang)},
                   'thread-id': notice_thread(row['device']), 'category': NOTICE_CATEGORY,
                   'interruption-level': 'passive'}
            payload = {'aps': aps, 'teleply': {'d': row['device'], 'a': app, 'c': chat}}
            await self.send(phone, payload, collapse, now + KEEP.get(row['state'], 86400), priority=5)
        return True

    async def send(self, phone, payload, collapse, expires, priority=10):
        """To one phone, once more after a moment when Apple or the network had a hiccup. A token Apple says is
        dead is dropped. Priority 5 for a silent notice (user 10-28)."""
        for attempt in (1, 2):
            try:
                status, reason = await self.sender.send(phone['environment'], phone['token'], payload, collapse, expires,
                                                        priority=priority)
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
