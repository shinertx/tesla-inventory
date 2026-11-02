"""Projections must not invent income or publish private sourcing reports."""
import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from app.store import Store
from tools import pipeline_jobs as jobs
from app.catalog import stock_id_for


def public_fixture(root):
    for name in ('index.html','inventory.json','sitemap.xml','robots.txt','web/app.js','web/pricing.js','web/styles.css','media/01.json'):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_text('fixture')


def selected_paths(args):
    name=next(x.split('=',1)[1] for x in args if x.startswith('--pathspec-from-file='))
    return set(Path(name).read_text().strip('\0').split('\0'))


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
    public_fixture(tmp_path);calls = [];staged_paths=[]
    def run(args, **kwargs):
        calls.append(args)
        if args[:2]==['git','add']:staged_paths.append(selected_paths(args))
        return SimpleNamespace(stdout=' M media/01.json\0 M data/vehicle_photos.json\0?? .data/private-report.md\0' if args[:2] == ['git', 'status'] else '', returncode=0)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    result = jobs.job_publish_and_index(repo_dir=tmp_path, ping_search_engines=False,
        git_push=True, status_file=tmp_path / 'status.json')
    staged = next(args for args in calls if args[:2] == ['git', 'add'])
    assert '--pathspec-file-nul' in staged
    assert staged_paths==[{'media/01.json'}]
    assert result['git']['pushed'] is True


def test_publisher_preserves_unrelated_staged_private_file(tmp_path, monkeypatch):
    import subprocess
    real_run = subprocess.run
    def git(*args, check=True):
        return real_run(['git', *args], cwd=tmp_path, check=check, capture_output=True, text=True)
    git('init', '-q'); git('config', 'user.email', 'fixture@example.test'); git('config', 'user.name', 'Fixture')
    public_fixture(tmp_path)
    for name in ['inventory.json', 'llms.txt', 'llms-full.txt', 'index.html', 'sitemap.xml', 'robots.txt', 'data/vehicle_photos.json']:
        path = tmp_path / name; path.parent.mkdir(exist_ok=True); path.write_text('original')
    for name in ['deals', 'models', 'states', 'years', 'media']:
        folder = tmp_path / name; folder.mkdir(exist_ok=True); (folder / 'fixture').write_text('original')
    git('add', '.'); git('commit', '-qm', 'Initial public fixtures')
    secret = tmp_path / '.data/private-report.md'; secret.parent.mkdir(); secret.write_text('PRIVATE FIXTURE')
    git('add', '.data/private-report.md')
    (tmp_path/'data/vehicle_photos.json').write_text('PRIVATE gallery refresh')
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
    assert git('show','HEAD:data/vehicle_photos.json').stdout=='original'
    assert (tmp_path/'data/vehicle_photos.json').read_text()=='PRIVATE gallery refresh'


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


def test_publisher_includes_generated_stock_browse_and_discovery_artifacts(tmp_path, monkeypatch):
    public_fixture(tmp_path);calls = [];scopes={}
    for name in ('v', 'browse'):
        (tmp_path / name).mkdir()
    (tmp_path/'v/VV-6C2CD3B68849.html').write_text('vehicle')
    (tmp_path/'browse/index.html').write_text('directory')
    for name in ('openapi.json', 'CNAME', 'voltsandvins-indexnow-key.txt', 'search-release.json'):
        (tmp_path / name).write_text('fixture')
    def run(args, **kwargs):
        calls.append(args)
        if args[1] in {'add','commit'}:scopes[args[1]]=selected_paths(args)
        names=['v/VV-6C2CD3B68849.html','browse/index.html','openapi.json','CNAME','voltsandvins-indexnow-key.txt','search-release.json']
        return SimpleNamespace(stdout=''.join(' M '+name+'\0'for name in names) if args[1]=='status' else '', returncode=0)
    monkeypatch.setattr(jobs.subprocess, 'run', run)
    jobs.job_publish_and_index(repo_dir=tmp_path, ping_search_engines=False,
        git_push=True, status_file=tmp_path / 'status.json')
    for operation in ('add', 'commit'):
        assert {'v/VV-6C2CD3B68849.html','browse/index.html','openapi.json','CNAME','voltsandvins-indexnow-key.txt','search-release.json'}<=scopes[operation]


@pytest.mark.parametrize('deployed', [True, False])
def test_publisher_waits_for_exact_public_sitemap_after_push(tmp_path, monkeypatch, deployed):
    import io
    public_fixture(tmp_path)
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
    public_fixture(tmp_path)
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


@pytest.mark.parametrize('published', [True, False])
def test_matcher_joins_stock_only_public_price_and_preserves_alert_history(tmp_path,monkeypatch,published):
    vin='7SAYGDED1RF039277';stock_id=stock_id_for(vin)
    database=tmp_path/'orders.db';store=Store(database)
    with store.connect() as conn:
        conn.execute("INSERT INTO orders(id,access_hash,request_key,request_hash,vin,customer,state,created_at,updated_at,action_due_at) VALUES('fixture','h','k','rh',?,'{}','requested',1,1,2)",(vin,))
        conn.execute('CREATE TABLE order_alerts_sent(order_id TEXT PRIMARY KEY,recipient TEXT NOT NULL,sent_at INTEGER NOT NULL)')
        conn.execute("INSERT INTO order_alerts_sent VALUES('fixture','existing-recipient@example.test',123)")
    private=tmp_path/'.data';private.mkdir()
    transaction=private/'transaction_inventory.json'
    transaction.write_text(json.dumps({'items':[{'vin':vin,'display_price':27000}]}))
    (tmp_path/'inventory.json').write_text(json.dumps({'items':[{'stock_id':stock_id,'year':2024,
        'model':'Model Y','trim':'AWD','display_price':40000,'savings_amount':800}] if published else []}))
    arb=private/'arb.json';arb.write_text(json.dumps({'items':[{'vin':vin,'source_asking_cents':3500000}]}))
    monkeypatch.setattr(jobs,'send_deal_alert_email',lambda *a,**kw:pytest.fail('Existing alert must not be resent'))
    packets=private/'packets.json'
    result=jobs.job_match_customer_orders(orders_db=database,inv_path=transaction,arb_path=arb,
        packets_out=packets,status_file=private/'status.json',alert_email='ben@jockeyvc.com')
    packet=json.loads(packets.read_text())['packets'][0]
    assert packet['vin']==vin and packet['modeled_gross_spread_dollars']==(5000 if published else None)
    assert packet['volts_retail_price']==(40000 if published else None)
    assert result['emails_sent_this_run']==0
    with store.connect() as conn:
        assert tuple(conn.execute('SELECT * FROM order_alerts_sent').fetchone())==('fixture','existing-recipient@example.test',123)


def test_stock_only_inventory_without_private_baseline_cannot_trigger_rebuild(tmp_path,monkeypatch):
    vin='7SAYGDED1RF039277'
    source=tmp_path/'source.json';source.write_text(json.dumps({'items':[{'vin':vin}]}))
    inventory=tmp_path/'inventory.json';inventory.write_text(json.dumps({'items':[{'stock_id':stock_id_for(vin)}]}))
    before=inventory.read_bytes()
    monkeypatch.setattr(jobs,'build_catalog',lambda **kw:pytest.fail('Missing identity must stop rebuild'))
    result=jobs.job_reprice_and_build(snapshot_path=source,output_dir=tmp_path,status_file=tmp_path/'.data/status.json')
    assert result['reason']=='private_transaction_inventory_required' and inventory.read_bytes()==before


def test_media_enrichment_seeds_original_private_arrays_and_keeps_cache_private(tmp_path):
    vin='7SAYGDED1RF039277';private=tmp_path/'.data';private.mkdir()
    originals=[{'url':'https://photos.example.test/'+vin+'/front.jpg','title':'Front','category':'photos'},
               {'url':'https://photos.example.test/rear.jpg','title':'Rear','category':'photos'}]
    transaction=private/'transaction_inventory.json';transaction.write_text(json.dumps({'items':[{'vin':vin,'photos':originals}]}))
    snapshot=private/'source_snapshot.json';snapshot.write_text(json.dumps({'items':[{'vin':vin,'photos':[]}]}))
    gallery=private/'vehicle_photos.json'
    result=jobs.job_enrich_media(snapshot_path=snapshot,gallery_path=gallery,status_file=private/'status.json')
    assert result['multi_photo_vins']==1 and json.loads(gallery.read_text())=={vin:originals}
    assert gallery.stat().st_mode & 0o777==0o600
    assert not (tmp_path/'data/vehicle_photos.json').exists()


def test_build_uses_private_original_gallery_and_leaves_source_clock_unchanged(tmp_path,monkeypatch):
    vin='7SAYGDED1RF039277';private=tmp_path/'.data';private.mkdir()
    originals=[{'url':'https://photos.example.test/'+vin+'/front.jpg','title':'Front','category':'photos'}]
    transaction=private/'transaction_inventory.json';transaction.write_text(json.dumps({'items':[{'vin':vin,'photos':originals}]}))
    source=private/'source.json';source.write_text(json.dumps({'items':[{'vin':vin,'observed_at':'2026-11-01T00:00:00Z'}]}))
    before=source.read_bytes()
    (tmp_path/'inventory.json').write_text(json.dumps({'items':[{'stock_id':stock_id_for(vin),'display_price':40000}]}))
    calls=[]
    def build(**kwargs):calls.append(kwargs);return {'items':[{'vin':vin}]}
    monkeypatch.setattr(jobs,'build_catalog',build)
    monkeypatch.setattr(jobs,'write_markdown_report',lambda *a,**kw:None)
    monkeypatch.setattr(jobs,'load_top_deals',lambda **kw:[])
    result=jobs.job_reprice_and_build(snapshot_path=source,output_dir=tmp_path,status_file=private/'status.json')
    assert result['ok'] and calls[0]['gallery_source']==private/'vehicle_photos.json'
    assert json.loads(calls[0]['gallery_source'].read_text())=={vin:originals}
    assert source.read_bytes()==before


def test_private_deal_reports_join_public_stock_id_and_use_published_price(tmp_path):
    from tools.top_arbitrage_deals import load_top_deals,write_markdown_report
    vin='7SAYGDED1RF039277';private=tmp_path/'.data';private.mkdir()
    (tmp_path/'inventory.json').write_text(json.dumps({'items':[{'stock_id':stock_id_for(vin),'year':2024,
        'model':'Model Y','trim':'AWD','mileage':30000,'display_price':40000}]}))
    (private/'arbitrage_opportunities.json').write_text(json.dumps({'items':[{'vin':vin,
        'source_asking_cents':3500000,'proposed_retail_cents':4500000}]}))
    deals=load_top_deals(min_spread_dollars=3500,catalog_root=tmp_path)
    assert deals[0]['vin']==vin and deals[0]['modeled_gross_spread_dollars']==5000
    report=private/'report.md';write_markdown_report(report,3500,catalog_root=tmp_path)
    assert vin in report.read_text() and report.stat().st_mode & 0o777==0o600


def test_publisher_stages_removed_public_pages_but_never_operational_data(tmp_path,monkeypatch):
    public_fixture(tmp_path);staged=[]
    removed='v/7SAYGDED1RF039277.html'
    def run(args,**kwargs):
        if args[1]=='add':staged.extend(selected_paths(args))
        return SimpleNamespace(stdout=' D '+removed+'\0 D docs/private.md\0 M data/vehicle_photos.json\0' if args[1]=='status' else '',returncode=0)
    monkeypatch.setattr(jobs.subprocess,'run',run)
    result=jobs.job_publish_and_index(repo_dir=tmp_path,git_push=True,ping_search_engines=False,status_file=tmp_path/'.data/status.json')
    assert result['git']['pushed'] and staged==[removed]


def test_publisher_does_not_reintroduce_legacy_vin_urls_to_search(tmp_path,monkeypatch):
    import io
    sitemap=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://voltsandvins.com/v/7SAYGDED1RF039277.html</loc></url></urlset>'
    (tmp_path/'sitemap.xml').write_bytes(sitemap);(tmp_path/'search-release.json').write_bytes(b'current')
    monkeypatch.setattr(jobs.urllib.request,'urlopen',lambda u,**kw:io.BytesIO(sitemap if u.endswith('sitemap.xml') else b'current'))
    monkeypatch.setattr(jobs,'ping_indexnow',lambda **kw:pytest.fail('Full VIN URLs cannot be submitted'))
    result=jobs.job_publish_and_index(repo_dir=tmp_path,status_file=tmp_path/'.data/status.json')
    assert result['indexnow']['reason']=='public_vin_urls_require_migration'
