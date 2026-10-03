"""Local accounts with hashed passwords and server-side session ownership."""
import hashlib
import hmac
import json
import secrets
import time
import uuid


class Accounts:
    def __init__(self, engine):
        self.engine = engine
        with engine.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE, salt TEXT, password TEXT, profile TEXT);
            CREATE TABLE IF NOT EXISTS logins(token TEXT PRIMARY KEY, user TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS ownership(session TEXT PRIMARY KEY, user TEXT);
            CREATE TABLE IF NOT EXISTS favorites(user TEXT, product TEXT, PRIMARY KEY(user,product));
            ''')

    def user(self, token):
        with self.engine.connect() as db:
            row = db.execute('SELECT user FROM logins WHERE token=? AND expires>?', (token, time.time())).fetchone()
        return row[0] if row else None

    def authenticate(self, action, payload):
        email = str(payload.get('email', '')).strip().lower()
        password = payload.get('password', '')
        if '@' not in email or len(email) > 254 or not isinstance(password, str) or not 10 <= len(password) <= 1024:
            raise ValueError('Email hợp lệ và mật khẩu từ 10 ký tự là bắt buộc.')
        with self.engine.connect() as db:
            if action == 'register':
                if db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
                    raise ValueError('Email đã được đăng ký.')
                salt = secrets.token_hex(16)
                hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200000).hex()
                db.execute('INSERT INTO users VALUES (?,?,?,?,?)', (str(uuid.uuid4()), email, salt, hashed, '{}'))
            row = db.execute('SELECT id,salt,password FROM users WHERE email=?', (email,)).fetchone()
            if not row or not hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(row[1]), 200000).hex(), row[2]):
                raise ValueError('Email hoặc mật khẩu không đúng.')
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO logins VALUES (?,?,?)', (token, row[0], time.time()+86400))
        return {'token': token, 'session_id': self.new_session(row[0])}

    def new_session(self, user):
        session = str(uuid.uuid4())
        with self.engine.connect() as db:
            db.execute('INSERT INTO ownership VALUES (?,?)', (session, user))
        return session

    def allowed(self, session, user):
        with self.engine.connect() as db:
            row = db.execute('SELECT user FROM ownership WHERE session=?', (session,)).fetchone()
        return row is None if user is None else bool(row and row[0] == user)

    def profile(self, user, payload=None):
        with self.engine.connect() as db:
            if payload is not None:
                profile = {key: str(payload.get(key, ''))[:500] for key in ('name', 'preferences')}
                db.execute('UPDATE users SET profile=? WHERE id=?', (json.dumps(profile), user))
            row = db.execute('SELECT email,profile FROM users WHERE id=?', (user,)).fetchone()
            ids = [r[0] for r in db.execute('SELECT product FROM favorites WHERE user=?', (user,))]
            sessions = [r[0] for r in db.execute('SELECT session FROM ownership WHERE user=?', (user,))]
        products = []
        for pid in ids:
            try:
                products.append(self.engine.backend.format_product(self.engine.overlay(self.engine.product(pid)), 0))
            except ValueError:
                pass
        return {'email': row[0], 'profile': json.loads(row[1]), 'favorites': products, 'sessions': sessions}

    def favorite(self, user, payload):
        pid = payload.get('product_id')
        self.engine.product(pid)
        with self.engine.connect() as db:
            if payload.get('remove'):
                db.execute('DELETE FROM favorites WHERE user=? AND product=?', (user, pid))
            else:
                db.execute('INSERT OR IGNORE INTO favorites VALUES (?,?)', (user, pid))
        return self.profile(user)
