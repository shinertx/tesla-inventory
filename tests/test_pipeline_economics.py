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


def test_publisher_includes_generated_vin_browse_and_discovery_artifacts(tmp_path, monkeypatch):
    calls = []
    for name in ('v', 'browse'):
        (tmp_path / name).mkdir()
    for name in ('openapi.json', 'CNAME', 'voltsandvins-indexnow-key.txt', 'search-release.json'):
        (tmp_path / name).write_text('fixture')
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=' M v/fixture/index.html\n', returncode=0)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    jobs.job_publish_and_index(repo_dir=tmp_path, ping_search_engines=False,
        git_push=True, status_file=tmp_path / 'status.json')
    for operation in ('status', 'add', 'commit'):
        command = next(args for args in calls if args[:2] == ['git', operation])
        assert {'v', 'browse', 'openapi.json', 'CNAME', 'voltsandvins-indexnow-key.txt', 'search-release.json'} <= set(command)


@pytest.mark.parametrize('deployed', [True, False])
def test_publisher_waits_for_exact_public_sitemap_after_push(tmp_path, monkeypatch, deployed):
    import io
    sitemap = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://voltsandvins.com/v/fixture/</loc></url></urlset>'
    (tmp_path / 'sitemap.xml').write_bytes(sitemap)
    (tmp_path / 'search-release.json').write_bytes(b'current release')
    operations = []
    def run(args, **kwargs):
        operations.append(args[1])
        return SimpleNamespace(stdout=' M sitemap.xml\n' if args[1] == 'status' else '', returncode=0)
    def fetch(url, timeout):
        assert timeout == 10
        if url.endswith('/sitemap.xml'):
            assert operations[-1] == 'push'
            operations.append('public_sitemap')
            return io.BytesIO(sitemap if deployed else b'prior deployment')
        assert url.endswith('/search-release.json') and operations[-1] == 'public_sitemap'
        operations.append('public_release')
        return io.BytesIO(b'current release')
    def ping(*, urls):
        assert operations[-1] == 'public_release'
        assert urls == ['https://voltsandvins.com/v/fixture/']
        operations.append('indexnow')
        return {'accepted': True, 'submitted': 1}
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    monkeypatch.setattr(jobs.urllib.request, 'urlopen', fetch)
    monkeypatch.setattr(jobs, 'ping_indexnow', ping)
    result = jobs.job_publish_and_index(repo_dir=tmp_path, git_push=True, status_file=tmp_path / 'status.json')
    assert operations.count('public_sitemap') == 1
    if deployed:
        assert result['indexnow']['submitted'] == 1
    else:
        assert result['indexnow'] == {'deferred': True, 'reason': 'public_sitemap_not_deployed'}
        assert 'indexnow' not in operations


def test_publisher_retains_indexnow_partial_batch_receipt(tmp_path, monkeypatch):
    import io
    from tools.indexnow import IndexNowSubmissionError
    sitemap = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'
    (tmp_path / 'sitemap.xml').write_bytes(sitemap)
    (tmp_path / 'search-release.json').write_bytes(b'current release')
    monkeypatch.setattr(jobs.urllib.request, 'urlopen', lambda url, **kw: io.BytesIO(sitemap if url.endswith('/sitemap.xml') else b'current release'))
    partial = {'submitted': 10000, 'accepted': False, 'batches': [{'status': 200}, {'status': 429}]}
    def ping(**kwargs):
        raise IndexNowSubmissionError('second batch failed', partial)
    monkeypatch.setattr(jobs, 'ping_indexnow', ping)
    result = jobs.job_publish_and_index(repo_dir=tmp_path, status_file=tmp_path / 'status.json')
    assert result['indexnow'] == {**partial, 'error': 'second batch failed'}


def test_publisher_defers_indexing_after_failed_push(tmp_path, monkeypatch):
    (tmp_path / 'sitemap.xml').write_text('fixture')
    (tmp_path / 'search-release.json').write_bytes(b'current release')
    def run(args, **kwargs):
        if args[1] == 'push':
            raise RuntimeError('push failed')
        return SimpleNamespace(stdout=' M sitemap.xml\n', returncode=0)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    monkeypatch.setattr(jobs.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('No fetch after failed push'))
    result = jobs.job_publish_and_index(repo_dir=tmp_path, git_push=True, status_file=tmp_path / 'status.json')
    assert result['indexnow']['reason'] == 'git_publish_failed'


def test_publisher_defers_once_when_public_sitemap_unavailable(tmp_path, monkeypatch):
    (tmp_path / 'sitemap.xml').write_text('fixture')
    (tmp_path / 'search-release.json').write_bytes(b'current release')
    calls = []
    def fetch(*args, **kwargs):
        calls.append(args)
        raise OSError('temporary public fetch failure')
    monkeypatch.setattr(jobs.urllib.request, 'urlopen', fetch)
    monkeypatch.setattr(jobs, 'ping_indexnow', lambda **kwargs: pytest.fail('Undeployed URLs must not be submitted'))
    result = jobs.job_publish_and_index(repo_dir=tmp_path, status_file=tmp_path / 'status.json')
    assert len(calls) == 1
    assert result['indexnow']['deferred'] is True
    assert result['indexnow']['reason'] == 'public_release_check_failed'


def test_unchanged_sitemap_cannot_hide_stale_public_release(tmp_path, monkeypatch):
    import io
    sitemap = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>'
    (tmp_path / 'sitemap.xml').write_bytes(sitemap)
    (tmp_path / 'search-release.json').write_bytes(b'{"asset_digest":"new-price-or-js"}')
    calls = []
    def fetch(url, **kwargs):
        calls.append(url)
        return io.BytesIO(sitemap if url.endswith('/sitemap.xml') else b'{"asset_digest":"old-price-or-js"}')
    monkeypatch.setattr(jobs.urllib.request, 'urlopen', fetch)
    monkeypatch.setattr(jobs, 'ping_indexnow', lambda **kw: pytest.fail('Stale release must not be submitted'))
    result = jobs.job_publish_and_index(repo_dir=tmp_path, status_file=tmp_path / 'status.json')
    assert len(calls) == 2
    assert result['indexnow'] == {'deferred': True, 'reason': 'public_release_manifest_not_deployed'}


def test_missing_local_release_manifest_never_falls_back_to_sitemap(tmp_path, monkeypatch):
    (tmp_path / 'sitemap.xml').write_text('fixture')
    monkeypatch.setattr(jobs.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('Missing manifest must defer locally'))
    monkeypatch.setattr(jobs, 'ping_indexnow', lambda **kw: pytest.fail('Missing manifest must not submit'))
    result = jobs.job_publish_and_index(repo_dir=tmp_path, status_file=tmp_path / 'status.json')
    assert result['indexnow'] == {'deferred': True, 'reason': 'local_release_manifest_missing'}
