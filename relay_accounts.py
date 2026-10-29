"""Invite-only relay state. Store this database in an OS-private directory.

Passwords use scrypt; session/invite/reset/binding tokens are stored as hashes.
Device forwarding and frp credentials must be recoverable by the trusted relay.
Never serve this database or put it in backups accessible to relay users.
"""
from contextlib import contextmanager
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

PASSWORD_LOCK = threading.Lock()  # Bound scrypt memory use on the 2 GiB server.
TTL = 7 * 86400


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('密码须为 12 至 256 个字符')
    salt = salt or secrets.token_hex(16)
    with PASSWORD_LOCK:
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                             n=131072, r=8, p=1, maxmem=160*1024*1024).hex()
    return salt + ':' + key


def password_matches(password, encoded):
    try:
        return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)
    except (ValueError, TypeError, AttributeError):
        return False


class Accounts:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE, password TEXT);
                CREATE TABLE IF NOT EXISTS grants(hash TEXT PRIMARY KEY, kind TEXT, owner TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, owner TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, owner TEXT, label TEXT,
                    gateway_secret TEXT, tunnel_secret TEXT, ingress INTEGER UNIQUE,
                    port INTEGER UNIQUE, revoked INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS attempts(bucket TEXT, time REAL);
                CREATE INDEX IF NOT EXISTS attempts_bucket ON attempts(bucket,time);
                CREATE TABLE IF NOT EXISTS usage(device TEXT, day TEXT, requests INTEGER DEFAULT 0,
                    uploads INTEGER DEFAULT 0, downloads INTEGER DEFAULT 0,
                    PRIMARY KEY(device,day));
                -- the phones an account's notifications go to, and the events already sent (relay_push.py)
                CREATE TABLE IF NOT EXISTS push_phones(id TEXT PRIMARY KEY, owner TEXT, platform TEXT,
                    environment TEXT, token TEXT UNIQUE, label TEXT, version TEXT, created REAL, refreshed REAL,
                    result TEXT DEFAULT '', language TEXT DEFAULT 'zh-Hans');
                CREATE INDEX IF NOT EXISTS push_phones_owner ON push_phones(owner);
                CREATE TABLE IF NOT EXISTS push_events(id TEXT PRIMARY KEY, time REAL);
                -- 灵动岛 (relay_push.py): one row per island's push token, and the phones' push-to-start tokens
                CREATE TABLE IF NOT EXISTS push_activities(id TEXT PRIMARY KEY, owner TEXT, device TEXT, app TEXT,
                    chat TEXT, token TEXT UNIQUE, environment TEXT, state TEXT, since INTEGER, turn INTEGER,
                    created REAL, refreshed REAL, result TEXT DEFAULT '',
                    saved_state TEXT, saved_since INTEGER, saved_turn INTEGER, title TEXT DEFAULT '', language TEXT DEFAULT 'zh-Hans');
                CREATE INDEX IF NOT EXISTS push_activities_owner ON push_activities(owner);
                CREATE INDEX IF NOT EXISTS push_activities_chat ON push_activities(device, app, chat);
                -- 0.6.3: one island per computer; these are the conversations its counts and list are made of
                CREATE TABLE IF NOT EXISTS push_conversations(device TEXT, app TEXT, chat TEXT, owner TEXT,
                    title TEXT DEFAULT '', state TEXT, since INTEGER, turn INTEGER, refreshed REAL,
                    ended INTEGER DEFAULT 0, step TEXT DEFAULT '', started_source TEXT DEFAULT '',
                    action_at INTEGER DEFAULT 0,
                    PRIMARY KEY(device, app, chat));
                CREATE INDEX IF NOT EXISTS push_conversations_device ON push_conversations(device);
                CREATE TABLE IF NOT EXISTS push_start(token TEXT PRIMARY KEY, owner TEXT, environment TEXT,
                    refreshed REAL, language TEXT DEFAULT 'zh-Hans');
            ''')
            # A database from an earlier build has push_activities without the columns added since.
            columns = {row[1] for row in db.execute('PRAGMA table_info(push_activities)')}
            for name, kind in (('saved_state', 'TEXT'), ('saved_since', 'INTEGER'), ('saved_turn', 'INTEGER'),
                               ('title', "TEXT DEFAULT ''"), ('language', "TEXT DEFAULT 'zh-Hans'")):
                if name not in columns:
                    db.execute(f'ALTER TABLE push_activities ADD COLUMN {name} {kind}')
            columns = {row[1] for row in db.execute('PRAGMA table_info(push_phones)')}
            if 'language' not in columns:
                db.execute("ALTER TABLE push_phones ADD COLUMN language TEXT DEFAULT 'zh-Hans'")
            columns = {row[1] for row in db.execute('PRAGMA table_info(push_start)')}
            if 'language' not in columns:
                db.execute("ALTER TABLE push_start ADD COLUMN language TEXT DEFAULT 'zh-Hans'")
            columns = {row[1] for row in db.execute('PRAGMA table_info(push_conversations)')}
            for name, kind in (('ended', 'INTEGER DEFAULT 0'), ('step', "TEXT DEFAULT ''"),
                               ('started_source', "TEXT DEFAULT ''"), ('action_at', 'INTEGER DEFAULT 0')):
                if name not in columns:
                    db.execute(f'ALTER TABLE push_conversations ADD COLUMN {name} {kind}')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def rate(self, bucket, limit=10, window=300):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE time<?', (now-86400,))
            n = db.execute('SELECT count(*) FROM attempts WHERE bucket=? AND time>?',
                           (bucket, now-window)).fetchone()[0]
            if n >= limit:
                raise ValueError('尝试过于频繁，请稍后重试')
            db.execute('INSERT INTO attempts VALUES (?,?)', (bucket, now))

    def grant(self, kind, owner='', ttl=600):
        if kind not in ('invite', 'reset', 'bind'):
            raise ValueError('unknown grant')
        code = secrets.token_urlsafe(32)
        with self.connect() as db:
            if kind == 'reset':
                db.execute('DELETE FROM grants WHERE kind=? AND owner=?', (kind, owner))
            db.execute('INSERT INTO grants VALUES (?,?,?,?)', (digest(code), kind, owner, time.time()+ttl))
        return code

    def consume(self, db, code, kind):
        row = db.execute('SELECT owner FROM grants WHERE hash=? AND kind=? AND expires>?',
                         (digest(code), kind, time.time())).fetchone()
        if row is None:
            raise ValueError('链接或绑定码无效、已使用或已过期')
        db.execute('DELETE FROM grants WHERE hash=?', (digest(code),))
        return row['owner']

    def register(self, name, password, invite):
        name = name.strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', name):
            raise ValueError('账号使用 3 至 40 位小写字母、数字、点、横线或下划线')
        encoded = password_hash(password)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.consume(db, invite, 'invite')
            try:
                db.execute('INSERT INTO users VALUES (?,?,?)', (secrets.token_hex(16), name, encoded))
            except sqlite3.IntegrityError:
                raise ValueError('账号不可用') from None

    def user(self, name):
        with self.connect() as db:
            return db.execute('SELECT * FROM users WHERE name=?', (name.strip().lower(),)).fetchone()

    def login(self, name, password):
        self.rate('login:'+digest(name.strip().lower()))
        row = self.user(name)
        # Same expensive KDF for missing accounts (valid-length input).
        encoded = row['password'] if row else '00'*16 + ':' + '00'*64
        if not password_matches(password, encoded) or row is None:
            raise ValueError('账号或密码错误')
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT password FROM users WHERE id=?', (row['id'],)).fetchone()
            if current['password'] != encoded:
                raise ValueError('密码已变化，请重新登录')
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), row['id'], time.time()+TTL))
        return token

    def owner(self, token):
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        with self.connect() as db:
            row = db.execute('SELECT owner FROM sessions WHERE hash=? AND expires>?',
                             (digest(token), time.time())).fetchone()
            return row['owner'] if row else None

    def valid(self, token):
        return self.owner(token) is not None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (digest(token),))

    def change_password(self, token, old, new):
        owner = self.owner(token)
        if not owner:
            raise ValueError('请重新登录')
        self.rate('password:'+owner)
        with self.connect() as db:
            row = db.execute('SELECT password FROM users WHERE id=?', (owner,)).fetchone()
        if not password_matches(old, row['password']):
            raise ValueError('当前密码错误')
        encoded = password_hash(new)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE users SET password=? WHERE id=? AND password=?',
                                 (encoded, owner, row['password'])).rowcount
            if not changed:
                raise ValueError('密码已变化，请重新登录')
            db.execute('DELETE FROM sessions WHERE owner=?', (owner,))
            db.execute('DELETE FROM grants WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_phones WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_activities WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_conversations WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_start WHERE owner=?', (owner,))

    def reset(self, code, password):
        encoded = password_hash(password)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = self.consume(db, code, 'reset')
            db.execute('UPDATE users SET password=? WHERE id=?', (encoded, owner))
            db.execute('DELETE FROM sessions WHERE owner=?', (owner,))
            db.execute('DELETE FROM grants WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_phones WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_activities WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_conversations WHERE owner=?', (owner,))
            db.execute('DELETE FROM push_start WHERE owner=?', (owner,))

    def bind(self, code, label, expected_name):
        if not label.strip() or len(label) > 80:
            raise ValueError('电脑名称须为 1 至 80 个字符')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owner = self.consume(db, code, 'bind')
            row = db.execute('SELECT name FROM users WHERE id=?', (owner,)).fetchone()
            if not row or row['name'] != expected_name:
                raise ValueError('账号不符，未绑定')
            # Never recycle a revoked route: stale frpc processes cannot hijack a new device.
            count = db.execute('SELECT count(*) FROM devices').fetchone()[0]
            if count >= 32:
                raise ValueError('设备名额已用完，请联系管理员')
            ident = secrets.token_hex(16)
            db.execute('INSERT INTO devices VALUES (?,?,?,?,?,?,?,0)',
                       (ident, owner, label.strip(), secrets.token_urlsafe(32),
                        secrets.token_urlsafe(32), 7101+count, 18101+count))
            return dict(db.execute('SELECT * FROM devices WHERE id=?', (ident,)).fetchone())

    def device(self, token, ident):
        owner = self.owner(token)
        if not owner:
            return None
        with self.connect() as db:
            row = db.execute('SELECT * FROM devices WHERE id=? AND owner=? AND revoked=0',
                             (ident, owner)).fetchone()
            return dict(row) if row else None

    def devices(self, token):
        with self.connect() as db:
            return [dict(x) for x in db.execute('SELECT id,label FROM devices WHERE owner=? AND revoked=0',
                                               (self.owner(token),))]

    def revoke(self, token, ident):
        with self.connect() as db:
            return db.execute('UPDATE devices SET revoked=1 WHERE id=? AND owner=? AND revoked=0',
                              (ident, self.owner(token))).rowcount

    def usage(self, ident, uploaded=0, downloaded=0, requests=0):
        day = time.strftime('%Y-%m-%d', time.gmtime())
        with self.connect() as db:
            db.execute('INSERT INTO usage VALUES (?,?,?,?,?) ON CONFLICT(device,day) DO UPDATE SET '
                       'requests=requests+excluded.requests, uploads=uploads+excluded.uploads, '
                       'downloads=downloads+excluded.downloads', (ident, day, requests, uploaded, downloaded))

    def usage_for(self, token):
        with self.connect() as db:
            return [dict(x) for x in db.execute('SELECT u.* FROM usage u JOIN devices d ON u.device=d.id '
                                               'WHERE d.owner=? ORDER BY day DESC LIMIT 100', (self.owner(token),))]
