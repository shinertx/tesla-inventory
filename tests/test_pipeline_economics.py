"""Projections must not invent income or publish private sourcing reports."""
import json
from types import SimpleNamespace

import pytest
from app.store import Store
from tools import pipeline_jobs as jobs


@pytest.mark.parametrize('spread,label', [(5000, '+$5,000'), (0, '+$0'), (-500, '-$500')])
def test_alert_labels_only_the_supported_price_gap(monkeypatch, spread, label):
    payloads = []
    class Reply:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def open_request(request, **kwargs):
        payloads.append(json.loads(request.data)); return Reply()
    monkeypatch.setattr(jobs.urllib.request, 'urlopen', open_request)
    assert jobs.send_deal_alert_email({'vin': 'fixture-vin', 'vehicle': 'Fixture Tesla',
        'modeled_gross_spread_dollars': spread, 'volts_4layer_profit_est': 7000}, sendgrid_key='test-only-key')
    sent = payloads[0]
    assert f'Modeled spread {label} before costs' in sent['subject']
    assert 'Profit' not in sent['subject']
    body = sent['content'][0]['value']
    assert '$7,000' not in body and '4-Layer' not in body and 'Reservation Request' not in body
    assert 'Collected platform revenue is not established' in body


@pytest.mark.parametrize('source,published,expected', [(3500000, 40000, 5000), (None, 40000, None), (0, 40000, None), (3500000, None, None)])
def test_matcher_uses_published_price_without_ancillary_income(tmp_path, monkeypatch, source, published, expected):
    db = tmp_path / 'orders.db'; store = Store(db)
    with store.connect() as conn:
        conn.execute("INSERT INTO orders (id,access_hash,request_key,request_hash,vin,customer,state,created_at,updated_at,action_due_at) VALUES ('fixture','hash','key','requesthash','fixture-vin','{}','requested',1000,1000,2000)")
    arb = tmp_path / 'arb.json'; inv = tmp_path / 'inv.json'
    arb.write_text(json.dumps({'items': [{'vin': 'fixture-vin', 'source_asking_cents': source,
        'proposed_retail_cents': 4500000, 'modeled_gross_spread_cents': 1000000}]}))
    inv.write_text(json.dumps({'items': [{'vin': 'fixture-vin', 'display_price': published}]}))
    monkeypatch.setattr(jobs, 'send_deal_alert_email', lambda *args, **kwargs: False)
    output = tmp_path / 'packets.json'
    jobs.job_match_customer_orders(orders_db=db, arb_path=arb, inv_path=inv, packets_out=output,
                                  status_file=tmp_path / 'status.json')
    packet = json.loads(output.read_text())['packets'][0]
    assert packet['modeled_gross_spread_dollars'] == expected
    assert packet['ancillary_income_assumed_dollars'] == 0
    assert packet['collected_revenue_established'] is False
    assert 'volts_4layer_profit_est' not in packet


def test_publisher_stages_media_and_never_the_private_report(tmp_path, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=' M media/01.json\n' if args[:2] == ['git', 'status'] else '', returncode=0)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    result = jobs.job_publish_and_index(repo_dir=tmp_path, ping_search_engines=False,
        git_push=True, status_file=tmp_path / 'status.json')
    staged = next(args for args in calls if args[:2] == ['git', 'add'])
    assert 'media' in staged and 'data/vehicle_photos.json' in staged
    assert not any(path.startswith('.data/') or 'TOP_ARBITRAGE_DEALS' in path for path in staged)
    assert result['git']['pushed'] is True


def test_publisher_preserves_unrelated_staged_private_file(tmp_path, monkeypatch):
    import subprocess
    real_run = subprocess.run
    def git(*args, check=True):
        return real_run(['git', *args], cwd=tmp_path, check=check, capture_output=True, text=True)
    git('init', '-q'); git('config', 'user.email', 'fixture@example.test'); git('config', 'user.name', 'Fixture')
    for name in ['inventory.json', 'llms.txt', 'llms-full.txt', 'index.html', 'sitemap.xml', 'robots.txt', 'data/vehicle_photos.json']:
        path = tmp_path / name; path.parent.mkdir(exist_ok=True); path.write_text('original')
    for name in ['deals', 'models', 'states', 'years', 'media']:
        folder = tmp_path / name; folder.mkdir(); (folder / 'fixture').write_text('original')
    git('add', '.'); git('commit', '-qm', 'Initial public fixtures')
    secret = tmp_path / '.data/private-report.md'; secret.parent.mkdir(); secret.write_text('PRIVATE FIXTURE')
    git('add', '.data/private-report.md')
    (tmp_path / 'inventory.json').write_text('updated public fixture')
    def run(args, **kwargs):
        if args[:2] == ['git', 'push']: return SimpleNamespace(returncode=0)
        return real_run(args, **kwargs)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    result = jobs.job_publish_and_index(repo_dir=tmp_path, ping_search_engines=False,
        git_push=True, status_file=tmp_path / '.data/status.json')
    assert result['git']['pushed'] is True
    assert git('show', 'HEAD:.data/private-report.md', check=False).returncode != 0
    assert '.data/private-report.md' in git('diff', '--cached', '--name-only').stdout
    assert git('show', 'HEAD:inventory.json').stdout == 'updated public fixture'


@pytest.mark.parametrize('source_rows', [[], [{'vin': 'one'}]])
def test_partial_source_does_not_replace_existing_catalog(tmp_path, monkeypatch, source_rows):
    source = tmp_path / 'source.json'; source.write_text(json.dumps({'items': source_rows}))
    inventory = tmp_path / 'inventory.json'; inventory.write_text(json.dumps({'items': [{'vin': str(i)} for i in range(10)]}))
    before = inventory.read_bytes()
    monkeypatch.setattr(jobs, 'build_catalog', lambda **kwargs: pytest.fail('Partial source must not overwrite published artifacts'))
    result = jobs.job_reprice_and_build(snapshot_path=source, output_dir=tmp_path, status_file=tmp_path / '.data/status.json')
    assert result['ok'] is False and result['published_unchanged'] is True
    assert inventory.read_bytes() == before


def test_discovery_stops_a_host_after_first_access_denial(tmp_path, monkeypatch):
    from curl_cffi import requests
    calls = []
    def denied(url, **kwargs):
        calls.append(url); return SimpleNamespace(status_code=403)
    monkeypatch.setattr(requests, 'get', denied)
    jobs.job_discover_vehicles(db_path=tmp_path / 'inventory.db', snapshot_path=tmp_path / 'source.json',
        partitions=[('cargurus', 'Model Y', 2024, 2), ('cargurus', 'Model 3', 2023, 2)],
        status_file=tmp_path / 'status.json')
    assert len(calls) == 1
