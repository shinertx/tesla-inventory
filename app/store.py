from contextlib import contextmanager
from pathlib import Path
import json, sqlite3, time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, access_hash TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
 request_hash TEXT NOT NULL, vin TEXT NOT NULL, customer TEXT NOT NULL,
 state TEXT NOT NULL, quote TEXT, quote_version INTEGER NOT NULL DEFAULT 0,
 checkout_id TEXT UNIQUE, payment_id TEXT UNIQUE, created_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL, action_due_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS holds (
 vin TEXT PRIMARY KEY, order_id TEXT UNIQUE NOT NULL, expires_at INTEGER,
 FOREIGN KEY(order_id) REFERENCES orders(id)
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, kind TEXT NOT NULL,
 detail TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stripe_events (id TEXT PRIMARY KEY, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY, order_id TEXT NOT NULL, kind TEXT NOT NULL,
 detail TEXT NOT NULL, created_at INTEGER NOT NULL, acknowledged_at INTEGER
);
CREATE TABLE IF NOT EXISTS source_holds (order_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL, reference TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY,order_id TEXT NOT NULL,kind TEXT NOT NULL,
 description TEXT NOT NULL,status TEXT NOT NULL,owner TEXT,evidence TEXT,created_at INTEGER NOT NULL,due_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT NOT NULL, window INTEGER NOT NULL,
 count INTEGER NOT NULL, PRIMARY KEY(bucket, window));
'''

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as c:
            c.executescript(SCHEMA)
        self.path.chmod(0o600)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        return c

    @contextmanager
    def transaction(self):
        c = self.connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def event(c, order_id, kind, detail=None, notify=False):
        raw = json.dumps(detail or {}, sort_keys=True)
        now = int(time.time())
        c.execute('INSERT INTO events(order_id,kind,detail,created_at) VALUES(?,?,?,?)', (order_id,kind,raw,now))
        if notify:
            c.execute('INSERT INTO outbox(order_id,kind,detail,created_at) VALUES(?,?,?,?)', (order_id,kind,raw,now))

    @staticmethod
    def expire(c, now):
        rows = c.execute('SELECT o.id,o.checkout_id FROM orders o JOIN holds h ON h.order_id=o.id '
                         'WHERE h.expires_at IS NOT NULL AND h.expires_at<=?', (now,)).fetchall()
        for r in rows:
            c.execute("UPDATE orders SET state='quote_expired',updated_at=? WHERE id=? AND state='checkout_pending'", (now,r['id']))
            Store.event(c,r['id'],'hold_expired',{'checkout_id':r['checkout_id']},True)
        c.execute('DELETE FROM holds WHERE expires_at IS NOT NULL AND expires_at<=?',(now,))

    def rate_limit(self, bucket, limit=10):
        now=int(time.time());window=now//3600
        with self.transaction() as c:
            c.execute('DELETE FROM rate_limits WHERE window<?',(window-24,))
            c.execute('INSERT INTO rate_limits VALUES(?,?,1) ON CONFLICT(bucket,window) DO UPDATE SET count=count+1',(bucket,window))
            count=c.execute('SELECT count FROM rate_limits WHERE bucket=? AND window=?',(bucket,window)).fetchone()[0]
        return count<=limit
