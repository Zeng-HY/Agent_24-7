"""Additive 0.27 identity schema; legacy users/devices remain readable."""
import hmac
import re
import secrets
import time
from relay_accounts import TTL, Accounts, digest, password_hash, password_matches

PIN_TRIES = 5  # wrong codes before a code is spent and a new one must be sent


class Code(str):
    """An emailed link code, with the six digits that may be typed in its place."""
    pin = ''


class Limited(ValueError):
    def __init__(self, seconds):
        self.seconds = max(1, int(seconds)+1)
        super().__init__(f'请在 {self.seconds} 秒后重试')


class Identity(Accounts):
    def __init__(self, path, account_limit=20, device_limit=3):
        super().__init__(path)
        if account_limit<1 or device_limit<1:raise ValueError('Account and device limits must be positive')
        self.account_limit, self.device_limit = account_limit, device_limit
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS account_emails(owner TEXT UNIQUE, email TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS email_grants(hash TEXT PRIMARY KEY, kind TEXT, email TEXT,
                owner TEXT, password TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS device_channels(id TEXT PRIMARY KEY, key_hash TEXT UNIQUE,
                enabled INTEGER DEFAULT 1, seen REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS device_authorizations(id TEXT PRIMARY KEY, key_hash TEXT UNIQUE,
                label TEXT, device TEXT, expires REAL, approved INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS email_pins(link TEXT PRIMARY KEY, email TEXT, kind TEXT, pin TEXT,
                tries INTEGER DEFAULT 0);
            ''')

    def rate(self, bucket, limit=10, window=300):
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE time<?', (now-86400,))
            row = db.execute('SELECT count(*), min(time) FROM attempts WHERE bucket=? AND time>?',
                             (bucket,now-window)).fetchone()
            if row[0] >= limit:
                raise Limited(row[1]+window-now)
            db.execute('INSERT INTO attempts VALUES (?,?)',(bucket,now))

    def user(self, name):
        with self.connect() as db:
            return db.execute('SELECT u.* FROM users u LEFT JOIN account_emails e ON e.owner=u.id '
                'WHERE u.name=? OR e.email=?',(name.strip().lower(),name.strip().lower())).fetchone()

    @staticmethod
    def email(value):
        value = value.strip().lower()
        if len(value)>254 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',value):
            raise ValueError('请输入有效的邮箱地址')
        return value

    def email_grant(self, kind, email, password='', token='', old=''):
        email = self.email(email)
        self.rate('mail:'+digest(email),5,3600)
        owner = ''
        encoded = ''
        if kind == 'signup':
            encoded = password_hash(password)
        elif kind == 'link':
            owner = self.owner(token)
            with self.connect() as db:
                row = db.execute('SELECT password FROM users WHERE id=?',(owner,)).fetchone()
            if not row or not password_matches(old,row['password']):
                raise ValueError('当前密码错误')
        elif kind != 'reset':
            raise ValueError('无效请求')
        with self.connect() as db:
            known = db.execute('SELECT 1 FROM account_emails WHERE email=?',(email,)).fetchone()
            full = db.execute('SELECT count(*) FROM users').fetchone()[0] >= self.account_limit
        # full: said for any address, so whether one is taken stays unsaid; nothing to send: the budget all share is
        # kept (a run of 忘记密码 for made-up addresses used to spend it and stop sign-up for an hour)
        if kind == 'signup' and full: raise ValueError('当前注册名额已满')
        if (kind == 'reset') != bool(known): return None
        self.rate('mail-global',120,3600)
        code = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT owner FROM account_emails WHERE email=?',(email,)).fetchone()
            if kind == 'reset':
                if not existing: return None
                owner = existing['owner']
            elif existing:
                return None
            if kind == 'signup' and db.execute('SELECT count(*) FROM users').fetchone()[0] >= self.account_limit:
                raise ValueError('当前注册名额已满')
            db.execute('DELETE FROM email_grants WHERE email=? AND kind=?',(email,kind))
            db.execute('DELETE FROM email_grants WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO email_grants VALUES (?,?,?,?,?,?)',
                       (digest(code),kind,email,owner,encoded,time.time()+1800))
            return self.pin(db,code,email,kind)

    @staticmethod
    def pin(db, code, email, kind):
        db.execute('DELETE FROM email_pins WHERE (email=? AND kind=?) OR link NOT IN (SELECT hash FROM email_grants)',(email,kind))
        code=Code(code);code.pin=f'{secrets.randbelow(10**6):06d}'
        db.execute('INSERT INTO email_pins VALUES (?,?,?,?,0)',(digest(code),email,kind,digest(email+':'+code.pin)))
        return code

    def consume_email(self, code, new_password=None):
        encoded = password_hash(new_password) if new_password is not None else None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM email_grants WHERE hash=? AND expires>?',
                           (digest(code),time.time())).fetchone()
            if not row: raise ValueError('链接已失效，请重新发送')
            return self.spend(db,row,encoded)

    def consume_pin(self, email, kind, pin, new_password=None):
        """The six digits from the email, typed on the page that asked for them: the account it is for (signed in
        there by the caller). A wrong code counts; after PIN_TRIES the code is spent."""
        email=self.email(email)
        self.rate('pin:'+digest(email),10,900)
        encoded = password_hash(new_password) if new_password is not None else None
        pin=str(pin).strip()
        error=None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT g.*,p.pin,p.tries FROM email_pins p JOIN email_grants g ON g.hash=p.link '
                           'WHERE p.email=? AND p.kind=? AND g.expires>?',(email,kind,time.time())).fetchone()
            if not row: error='验证码已失效，请重新发送'
            elif not (re.fullmatch(r'[0-9]{6}',pin) and hmac.compare_digest(row['pin'],digest(email+':'+pin))):
                if row['tries']+1>=PIN_TRIES:
                    db.execute('DELETE FROM email_grants WHERE hash=?',(row['hash'],))
                    db.execute('DELETE FROM email_pins WHERE link=?',(row['hash'],))
                    error='验证码已失效，请重新发送'
                else:
                    db.execute('UPDATE email_pins SET tries=tries+1 WHERE link=?',(row['hash'],))
                    error='验证码不对'
            else: owner=self.spend(db,row,encoded)
        if error: raise ValueError(error)  # after the count above is saved
        return owner

    def spend(self, db, row, encoded):
        if row['kind']=='reset':
            if encoded is None: raise ValueError('请设置新密码')
            db.execute('UPDATE users SET password=? WHERE id=?',(encoded,row['owner']))
            db.execute('DELETE FROM sessions WHERE owner=?',(row['owner'],))
            db.execute('DELETE FROM grants WHERE owner=?',(row['owner'],))
            db.execute('DELETE FROM email_grants WHERE owner=?',(row['owner'],))
        else:
            if encoded is not None: raise ValueError('无效请求')
            if db.execute('SELECT 1 FROM account_emails WHERE email=?',(row['email'],)).fetchone():
                raise ValueError('邮箱已关联账号，请登录')
            owner=row['owner']
            if row['kind']=='signup':
                if db.execute('SELECT count(*) FROM users').fetchone()[0]>=self.account_limit:
                    raise ValueError('当前注册名额已满')
                owner=secrets.token_hex(16)
                db.execute('INSERT INTO users VALUES (?,?,?)',(owner,'u_'+owner,row['password']))
            db.execute('DELETE FROM account_emails WHERE owner=?',(owner,))
            db.execute('INSERT INTO account_emails VALUES (?,?)',(owner,row['email']))
        db.execute('DELETE FROM email_grants WHERE hash=?',(row['hash'],))
        db.execute('DELETE FROM email_pins WHERE link=?',(row['hash'],))
        return row['owner'] if row['kind']!='signup' else owner

    def start_session(self, owner):
        """A session for an account whose email was just proven on this page (its six digits)."""
        token=secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?)',(digest(token),owner,time.time()+TTL))
        return token

    def resend_signup(self,email):
        email=self.email(email)
        self.rate('mail:'+digest(email),5,3600)
        with self.connect() as db:  # no sign-up waiting: nothing is sent, the shared budget is kept
            if not db.execute('SELECT 1 FROM email_grants WHERE kind=? AND email=? AND expires>?',('signup',email,time.time())).fetchone():return None
        self.rate('mail-global',120,3600)
        code=secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM email_grants WHERE kind=? AND email=? AND expires>?',
                           ('signup',email,time.time())).fetchone()
            if not row:return None
            db.execute('DELETE FROM email_grants WHERE hash=?',(row['hash'],))
            db.execute('INSERT INTO email_grants VALUES (?,?,?,?,?,?)',
                       (digest(code),'signup',email,'',row['password'],time.time()+1800))
            return self.pin(db,code,email,'signup')

    def reset_compatible(self,code,password):
        with self.connect() as db:
            email_code=db.execute('SELECT 1 FROM email_grants WHERE hash=? AND kind=? AND expires>?',(digest(code),'reset',time.time())).fetchone()
            legacy_code=db.execute('SELECT 1 FROM grants WHERE hash=? AND kind=? AND expires>?',(digest(code),'reset',time.time())).fetchone()
        if not email_code and not legacy_code:raise ValueError('链接已失效，请重新发送')
        if email_code:self.consume_email(code,password)
        else:super().reset(code,password)

    def start_authorization(self, key, label):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',key): raise ValueError('无效设备凭据')
        if not isinstance(label,str) or not 1<=len(label.strip())<=80: raise ValueError('请输入电脑名称')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM device_authorizations WHERE approved=0 AND expires<=?',(time.time(),))
            row=db.execute('SELECT * FROM device_authorizations WHERE key_hash=?',(digest(key),)).fetchone()
            if row and (row['approved'] or row['expires']>time.time()): return row['id']
            db.execute('DELETE FROM device_authorizations WHERE key_hash=?',(digest(key),))
            ident=secrets.token_hex(16)
            db.execute('INSERT INTO device_authorizations VALUES (?,?,?,?,?,0)',
                       (ident,digest(key),label.strip(),'',time.time()+900))
            return ident

    def authorization(self, ident, key=None):
        with self.connect() as db:
            row=db.execute('SELECT * FROM device_authorizations WHERE id=?',(ident,)).fetchone()
            if not row or (not row['approved'] and row['expires']<=time.time()):
                raise ValueError('绑定请求已过期，请重新登录')
            if key is not None and row['key_hash'] != digest(key): raise ValueError('无效设备凭据')
            return dict(row)

    def approve(self, token, ident, existing=''):
        owner=self.owner(token)
        if not owner: raise ValueError('请先登录')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM device_authorizations WHERE id=? AND expires>?',
                           (ident,time.time())).fetchone()
            if not row: raise ValueError('绑定请求已过期')
            if row['approved']:
                owned=db.execute('SELECT id FROM devices WHERE id=? AND owner=? AND revoked=0',(row['device'],owner)).fetchone()
                if not owned: raise ValueError('绑定请求不可用')
                return owned['id']
            if existing:
                if not db.execute('SELECT 1 FROM devices WHERE id=? AND owner=? AND revoked=0',(existing,owner)).fetchone():
                    raise ValueError('电脑不可用')
                device=existing
            else:
                if db.execute('SELECT count(*) FROM devices WHERE owner=? AND revoked=0',(owner,)).fetchone()[0]>=self.device_limit:
                    raise ValueError('已达到电脑数量上限')
                device=secrets.token_hex(16)
                db.execute('INSERT INTO devices VALUES (?,?,?,?,?,?,?,0)',(device,owner,row['label'],'','',None,None))
            db.execute('INSERT INTO device_channels(id,key_hash,enabled) VALUES (?,?,1) '
                       'ON CONFLICT(id) DO UPDATE SET key_hash=excluded.key_hash,enabled=1',(device,row['key_hash']))
            db.execute('UPDATE device_authorizations SET device=?,approved=1 WHERE id=?',(device,ident))
            return device

    def channel_device(self, key):
        with self.connect() as db:
            row=db.execute('SELECT d.id FROM devices d JOIN device_channels c ON d.id=c.id '
                           'WHERE c.key_hash=? AND c.enabled=1 AND d.revoked=0',(digest(key),)).fetchone()
            return row['id'] if row else None

    def rename(self, token, ident, label):
        if not 1<=len(label.strip())<=80: raise ValueError('请输入电脑名称')
        with self.connect() as db:
            if not db.execute('UPDATE devices SET label=? WHERE id=? AND owner=? AND revoked=0',
                              (label.strip(),ident,self.owner(token))).rowcount: raise ValueError('电脑不可用')

    def profile(self, token):
        with self.connect() as db:
            row=db.execute('SELECT email FROM account_emails WHERE owner=?',(self.owner(token),)).fetchone()
            return row['email'] if row else ''
