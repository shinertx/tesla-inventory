from runtime_proof import deployment_proof
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from fastapi import Request

def _require_inactive_live_environment(environment):
    # This wrapper is for inactive preparation only. Activation needs a new review.
    required = {
        'SANDBOX_MODE': 'false',
        'CHECKOUT_ENABLED': 'false',
        'BALANCE_CHECKOUT_ENABLED': 'false',
        'PLATFORM_AGREEMENTS_VERIFIED': 'false',
    }
    for name, expected in required.items():
        if environment.get(name) != expected:
            raise RuntimeError('Inactive preparation requires explicit false flag: ' + name)
    prefixes = {
        'STRIPE_SECRET_KEY': ('rk_live_', 'sk_live_'),
        'STRIPE_PUBLISHABLE_KEY': ('pk_live_',),
        'STRIPE_WEBHOOK_SECRET': ('whsec_',),
    }
    for name, allowed in prefixes.items():
        value = environment.get(name, '')
        if value and (not isinstance(value, str) or not value.isascii()
                or not value.startswith(allowed)
                or not all(character.isalnum() or character == '_' for character in value)
                or any(value == prefix for prefix in allowed)):
            raise RuntimeError('Inactive LIVE credential format rejected: ' + name)
    if environment.get('STRIPE_SECRET_KEY'):
        if environment.get('STRIPE_PLATFORM_ACCOUNT') != 'acct_1RVzLDRt4eEy1s3E':
            raise RuntimeError('Inactive LIVE preparation requires the reviewed platform account pin')


_require_inactive_live_environment(os.environ)
from app.main import app

DB_PATH = os.environ.get('ORDERS_DB', '/var/lib/volts-api/orders.db')
JOBS_STATUS_PATH = Path('/var/lib/volts-api/jobs_status.json')


def _require_zero_approved_sellers(db_path):
    # Read only; do not fabricate seller approval or modify the existing database.
    location = Path(db_path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(location, uri=True) as connection:
        for (raw_profile,) in connection.execute('SELECT profile FROM dealers'):
            profile = json.loads(raw_profile)
            if not isinstance(profile, dict) or profile.get('verified'):
                raise RuntimeError('Inactive preparation requires zero approved sellers')


_require_zero_approved_sellers(DB_PATH)


def _init_visits_table() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS visitor_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, visitor_hash TEXT NOT NULL, event_type TEXT NOT NULL, path TEXT NOT NULL, vin TEXT, referrer TEXT, user_agent TEXT)'
        )
        conn.commit()


_init_visits_table()


@app.get('/deployment-proof')
def proof():
    return deployment_proof()


@app.post('/api/visit')
async def record_visit(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    ip = (request.headers.get('x-forwarded-for') or (request.client.host if request.client else '')).split(',')[0].strip()
    ua = (request.headers.get('user-agent') or '')[:240]
    visitor_hash = hashlib.sha256(f'{ip}|{ua}'.encode()).hexdigest()[:16]
    event_type = str(body.get('event') or 'page_view')[:40]
    path = str(body.get('path') or '/')[:200]
    vin = str(body.get('vin') or '')[:24] or None
    referrer = str(body.get('referrer') or '')[:240] or None
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'INSERT INTO visitor_events (ts, visitor_hash, event_type, path, vin, referrer, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (int(time.time()), visitor_hash, event_type, path, vin, referrer, ua),
        )
        conn.commit()
    return {'ok': True}


@app.get('/api/visits/summary')
def visits_summary():
    owner_hashes = ('aa907a0cb71d3e5b', '6d072ff733541c5b')
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute('SELECT visitor_hash, event_type, vin, user_agent FROM visitor_events').fetchall()
    owner_events = 0
    bot_hashes = set()
    ext_hashes = set()
    ext_vin_views = {}
    all_vin_views = {}
    for vhash, etype, vin, ua in rows:
        ua_l = (ua or '').lower()
        is_bot = any(k in ua_l for k in ('curl', 'headless', 'dataprovider', 'bot', 'spider', 'crawl'))
        if vin:
            all_vin_views[vin] = all_vin_views.get(vin, 0) + 1
        if vhash in owner_hashes:
            owner_events += 1
        elif is_bot:
            bot_hashes.add(vhash)
        else:
            ext_hashes.add(vhash)
            if vin:
                ext_vin_views[vin] = ext_vin_views.get(vin, 0) + 1
    return {
        'total_events': len(rows),
        'owner_test_events': owner_events,
        'crawler_and_ci_visitors': len(bot_hashes),
        'external_browser_visitors': len(ext_hashes),
        'external_vin_views': [{'vin': k, 'views': v} for k, v in sorted(ext_vin_views.items(), key=lambda x: -x[1])[:10]],
        'all_top_vins': [{'vin': k, 'views': v} for k, v in sorted(all_vin_views.items(), key=lambda x: -x[1])[:10]],
    }


@app.get('/api/jobs/status')
def jobs_status():
    data = {}
    if JOBS_STATUS_PATH.exists():
        try:
            data = json.loads(JOBS_STATUS_PATH.read_text())
        except Exception:
            data = {}
    return {
        'ok': True,
        'timers': ['volts-order-matcher.timer (60s)', 'volts-sandbox-refunds.timer (60s)', 'github-actions/refresh-catalog.yml (2h)'],
        'pipeline': data,
    }


@app.get('/api/search')
def ai_inventory_search(
    model: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    max_price: int | None = None,
    max_mileage: int | None = None,
    state: str | None = None,
    drivetrain: str | None = None,
    only_price_finds: bool = False,
    sort: str = 'savings',
    limit: int = 10,
):
    inv_file = Path('/opt/volts-api/current/inventory.json')
    items = json.loads(inv_file.read_text()).get('items', []) if inv_file.exists() else []
    results = []
    for x in items:
        if model and model.lower() not in str(x.get('model', '')).lower():
            continue
        if year_min and (x.get('year') or 0) < year_min:
            continue
        if year_max and (x.get('year') or 0) > year_max:
            continue
        if max_price and (x.get('display_price') or 999999) > max_price:
            continue
        if max_mileage and (x.get('mileage') or 999999) > max_mileage:
            continue
        if state and str(x.get('state', '')).upper() != state.strip().upper():
            continue
        if drivetrain and str(x.get('drivetrain', '')).upper() != drivetrain.strip().upper():
            continue
        if only_price_finds and (x.get('savings_amount') or 0) < 500:
            continue
        results.append(x)
    if sort == 'price_asc':
        results.sort(key=lambda r: (r.get('display_price') or 999999, r.get('mileage') or 999999))
    elif sort == 'mileage_asc':
        results.sort(key=lambda r: (r.get('mileage') or 999999, r.get('display_price') or 999999))
    else:
        results.sort(key=lambda r: (-(r.get('savings_amount') or 0), r.get('display_price') or 999999))
    cap = max(1, min(limit, 50))
    return {
        'total_matches': len(results),
        'returned': min(len(results), cap),
        'items': [
            {
                'vin': r.get('vin'),
                'year': r.get('year'),
                'model': r.get('model'),
                'trim': r.get('trim'),
                'drivetrain': r.get('drivetrain'),
                'factory': r.get('factory'),
                'mileage': r.get('mileage'),
                'display_price': r.get('display_price'),
                'peer_benchmark_price': r.get('reference_price'),
                'peer_sample_count': r.get('reference_sample'),
                'buyer_savings_below_benchmark': r.get('savings_amount', 0),
                'city': r.get('city'),
                'state': r.get('state'),
                'photo': r.get('photo'),
                'checkout_url': f"https://voltsandvins.com/?vin={r.get('vin')}",
            }
            for r in results[:cap]
        ],
    }
