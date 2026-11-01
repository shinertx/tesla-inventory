from contextlib import contextmanager
from pathlib import Path
import json, sqlite3, time
from .models import canonical_reference

SCHEMA = '''
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, access_hash TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
 request_hash TEXT NOT NULL, vin TEXT NOT NULL, customer TEXT NOT NULL,
 state TEXT NOT NULL, quote TEXT, quote_version INTEGER NOT NULL DEFAULT 0,
 checkout_id TEXT UNIQUE, payment_id TEXT UNIQUE, created_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL, action_due_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS online_actions (order_id TEXT NOT NULL,kind TEXT NOT NULL,url TEXT NOT NULL,evidence_reference TEXT NOT NULL,PRIMARY KEY(order_id,kind));
CREATE TABLE IF NOT EXISTS vehicle_media (vin TEXT PRIMARY KEY,payload TEXT NOT NULL,expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS dealers (id TEXT PRIMARY KEY,profile TEXT NOT NULL,updated_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settlement_receipts (reference TEXT PRIMARY KEY,order_id TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS settlement_reversals (reference TEXT PRIMARY KEY,order_id TEXT NOT NULL,amount_cents INTEGER NOT NULL,created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settlements (order_id TEXT PRIMARY KEY,expected_spread_cents INTEGER NOT NULL,
 received_cents INTEGER NOT NULL,adjustment_cents INTEGER NOT NULL,actual_platform_cost_cents INTEGER NOT NULL,
 evidence TEXT NOT NULL,settled_at INTEGER NOT NULL);
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
CREATE TABLE IF NOT EXISTS case_request_keys (
 order_id TEXT NOT NULL, request_key TEXT NOT NULL, request_hash TEXT NOT NULL, case_id TEXT NOT NULL UNIQUE,
 PRIMARY KEY(order_id,request_key), FOREIGN KEY(case_id) REFERENCES cases(id)
);
CREATE TABLE IF NOT EXISTS rate_limits (bucket TEXT NOT NULL, window INTEGER NOT NULL,
 count INTEGER NOT NULL, PRIMARY KEY(bucket, window));
CREATE TABLE IF NOT EXISTS buyer_cash_entries (
 id TEXT PRIMARY KEY, reference TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('receipt','reversal')),
 order_id TEXT NOT NULL REFERENCES orders(id), quote_version INTEGER NOT NULL,
 dealer_id TEXT NOT NULL, seller_key TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 currency TEXT NOT NULL CHECK(currency='USD'),
 receipt_id TEXT REFERENCES buyer_cash_entries(id), evidence_reference TEXT NOT NULL,
 observed_at INTEGER NOT NULL, recorded_at INTEGER NOT NULL, payload_hash TEXT NOT NULL,
 CHECK((kind='receipt' AND receipt_id IS NULL) OR (kind='reversal' AND receipt_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS buyer_cash_order ON buyer_cash_entries(order_id);
CREATE INDEX IF NOT EXISTS buyer_cash_parent ON buyer_cash_entries(receipt_id);
CREATE TRIGGER IF NOT EXISTS buyer_cash_no_update BEFORE UPDATE ON buyer_cash_entries
 BEGIN SELECT RAISE(ABORT,'Buyer cash history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS buyer_cash_no_delete BEFORE DELETE ON buyer_cash_entries
 BEGIN SELECT RAISE(ABORT,'Buyer cash history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS buyer_cash_reversal_check BEFORE INSERT ON buyer_cash_entries WHEN NEW.kind='reversal'
 BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM buyer_cash_entries p WHERE p.id=NEW.receipt_id AND p.kind='receipt'
   AND p.order_id=NEW.order_id AND p.quote_version=NEW.quote_version AND p.dealer_id=NEW.dealer_id AND p.seller_key=NEW.seller_key)
   THEN RAISE(ABORT,'Reversal must match its original receipt') END;
 SELECT CASE WHEN NEW.amount_cents>(SELECT amount_cents FROM buyer_cash_entries WHERE id=NEW.receipt_id)
   -(SELECT COALESCE(SUM(amount_cents),0) FROM buyer_cash_entries WHERE receipt_id=NEW.receipt_id AND kind='reversal')
   THEN RAISE(ABORT,'Reversal exceeds original receipt') END;
 END;
CREATE TABLE IF NOT EXISTS lender_funding_observations (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('funding','correction')), prior_reference TEXT REFERENCES lender_funding_observations(reference),
 legacy_prior_event_id INTEGER REFERENCES events(id),
 order_id TEXT NOT NULL REFERENCES orders(id), quote_version INTEGER NOT NULL,
 dealer_id TEXT NOT NULL, seller_key TEXT NOT NULL, provider TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>=0), currency TEXT NOT NULL CHECK(currency='USD'),
 evidence_reference TEXT NOT NULL, observed_at INTEGER NOT NULL, payload_hash TEXT NOT NULL,
 CHECK(kind='correction' OR amount_cents>0)
);
CREATE INDEX IF NOT EXISTS lender_funding_order ON lender_funding_observations(order_id,seq);
CREATE TRIGGER IF NOT EXISTS lender_funding_no_update BEFORE UPDATE ON lender_funding_observations
 BEGIN SELECT RAISE(ABORT,'Lender funding history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS lender_funding_no_delete BEFORE DELETE ON lender_funding_observations
 BEGIN SELECT RAISE(ABORT,'Lender funding history is append-only'); END;
'''

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as c:
            c.executescript(SCHEMA)
            columns={r[1] for r in c.execute('PRAGMA table_info(orders)')}
            for name,definition in [
                ('workflow_model',"TEXT NOT NULL DEFAULT 'legacy_resale'"),
                ('dealer_id','TEXT'),
                ('payment_account','TEXT'),
                ('dealer_profile','TEXT'),
                ('balance_checkout_id','TEXT'),
                ('balance_payment_id','TEXT'),
                ('balance_payment_state',"TEXT NOT NULL DEFAULT 'unpaid'"),
                ('payment_preference',"TEXT NOT NULL DEFAULT 'cash'"),
                ('financing_state',"TEXT NOT NULL DEFAULT 'not_requested'"),
                ('financing_detail','TEXT'),
                ('transport_state',"TEXT NOT NULL DEFAULT 'unquoted'"),
                ('transport_detail','TEXT'),
                ('refund_id','TEXT'),
                ('price_commitment','TEXT'),
            ]:
                if name not in columns:c.execute(f'ALTER TABLE orders ADD COLUMN {name} {definition}')
            legacy=c.execute("SELECT id,state,quote FROM orders WHERE workflow_model='legacy_resale' AND quote IS NOT NULL AND state NOT IN ('model_review','cancelled','refunded')").fetchall()
            for row in legacy:
                c.execute("UPDATE orders SET state='model_review' WHERE id=?",(row['id'],))
                self.event(c,row['id'],'legacy_resale_requires_review',{'previous_state':row['state']},True)
            c.commit()
        self.path.chmod(0o600)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.create_function('canonical_reference',1,canonical_reference,deterministic=True)
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
