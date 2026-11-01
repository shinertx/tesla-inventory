"""Strict vehicle identity and source observations. Never repair an identity by checksum."""
from datetime import datetime, timezone
from pathlib import Path
import json, sqlite3
VALUES={**{str(i):i for i in range(10)},**dict(zip('ABCDEFGH',range(1,9))),
    **dict(zip('JKLMN',range(1,6))),'P':7,'R':9,**dict(zip('STUVWXYZ',range(2,10)))}
WEIGHTS=(8,7,6,5,4,3,2,10,0,9,8,7,6,5,4,3,2)

def valid_vin(vin):
    if not isinstance(vin,str) or len(vin)!=17 or vin[:3] not in ('5YJ','7SA','7G2'):return False
    if any(c not in VALUES for c in vin):return False
    check=sum(VALUES[c]*w for c,w in zip(vin,WEIGHTS))%11
    return vin[8]==('X' if check==10 else str(check))

def ingest(db_path,rows,source,observed_at,complete=False):
    """Only call with timestamps captured by successful source fetches, never snapshot imports."""
    parsed=datetime.fromisoformat(observed_at)
    if parsed.tzinfo is None:raise ValueError('Source observation needs a timezone')
    if abs((datetime.now(timezone.utc)-parsed).total_seconds())>3600:raise ValueError('Use the snapshot importer for historical records')
    path=Path(db_path);path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path)
    c.executescript('''CREATE TABLE IF NOT EXISTS listings(vin TEXT,source TEXT,payload TEXT,observed_at TEXT,active INTEGER,PRIMARY KEY(vin,source));
    CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,vin TEXT,source TEXT,payload TEXT,observed_at TEXT);
    CREATE TABLE IF NOT EXISTS quarantine(id INTEGER PRIMARY KEY,source TEXT,payload TEXT,reason TEXT,observed_at TEXT);''')
    accepted=0
    with c:
        # Complete may only be set after every expected source partition succeeds.
        if complete:c.execute('UPDATE listings SET active=0 WHERE source=?',(source,))
        for row in rows:
            raw=json.dumps(row,sort_keys=True);vin=row.get('vin','')
            if not valid_vin(vin):
                c.execute('INSERT INTO quarantine(source,payload,reason,observed_at) VALUES(?,?,?,?)',(source,raw,'VIN invalid; human resolution required',observed_at));continue
            record={**row,'source':source,'observed_at':observed_at}
            payload=json.dumps(record,sort_keys=True)
            c.execute('INSERT INTO listings VALUES(?,?,?,?,1) ON CONFLICT(vin,source) DO UPDATE SET payload=excluded.payload,observed_at=excluded.observed_at,active=1',(vin,source,payload,observed_at))
            c.execute('INSERT INTO observations(vin,source,payload,observed_at) VALUES(?,?,?,?)',(vin,source,raw,observed_at));accepted+=1
    c.close();return accepted

def export(db_path,destination):
    c=sqlite3.connect(db_path)
    # Prefer the most recent actual observation for a VIN, not the lowest historical price.
    rows=c.execute('SELECT payload FROM listings WHERE active=1 ORDER BY observed_at DESC,source').fetchall();seen=set();items=[]
    # A bounded partial refresh must not discard unrelated source candidates.
    target=Path(destination)
    prior=json.loads(target.read_text()).get('items',[]) if target.exists() else []
    inactive={(r[0],r[1]) for r in c.execute('SELECT vin,source FROM listings WHERE active=0')}
    retained={x['vin']:x for x in prior if (x.get('vin'),x.get('source')) not in inactive}
    for (raw,) in rows:
        row=json.loads(raw)
        if row['vin'] not in seen:seen.add(row['vin']);retained[row['vin']]=row
    Path(destination).write_text(json.dumps({'provenance':'Timestamped source observations; exclusive availability remains unverified.','items':list(retained.values())},separators=(',',':')))
    c.close()
