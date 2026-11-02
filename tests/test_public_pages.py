"""Public page refresh preserves the published catalog and private boundaries."""
import copy
import json
import re
from tools.build import render_public_pages


def catalog():
    return {'meta': {'count': 1, 'built_at': '2026-11-01T00:00:00Z', 'media_version': 'fixture'}, 'items': [{
        'vin': '7SAYGDED1RF039277', 'year': 2024, 'model': 'Model Y', 'trim': 'Base',
        'state': 'TX', 'city': 'Houston', 'mileage': 42099, 'display_price': 34948,
        'reference_price': 33549, 'reference_sample': 21, 'savings_amount': 0,
        'drivetrain': 'RWD', 'factory': 'Fremont', 'reservable': False,
        'photo': 'https://example.test/vehicle.jpg', 'photo_count': 1,
        'source_dealer': 'PRIVATE SUPPLIER NAME', 'source_asking_cents': 1234567,
    }]}


def test_public_refresh_preserves_catalog_and_omits_private_fields(tmp_path):
    data = catalog(); before = copy.deepcopy(data)
    path = tmp_path / 'inventory.json'; path.write_text(json.dumps(data, indent=2)); raw = path.read_bytes()
    result = render_public_pages(data, tmp_path)
    assert data == before and path.read_bytes() == raw
    assert result['published'] == 1 and result['sitemap_urls'] == 6
    pages = list(tmp_path.rglob('*.html'))
    for page in pages:
        text = page.read_text()
        assert 'PRIVATE SUPPLIER NAME' not in text and '1234567' not in text
        assert 'name="volts-catalog-version"' in text
        assert 'rel="preload" href="inventory.json"' not in text
        assert 'id="request-back"' in text and 'id="vehicle-footer"' in text
    assert 'VIN-verified' not in (tmp_path / 'llms.txt').read_text()


def test_catalog_version_changes_without_repricing(tmp_path):
    data = catalog(); render_public_pages(data, tmp_path)
    def version():
        return re.search(r'name="volts-catalog-version" content="([a-f0-9]+)"', (tmp_path / 'index.html').read_text()).group(1)
    first = version(); data['items'][0]['photo_count'] = 2
    render_public_pages(data, tmp_path)
    assert version() != first
    assert data['items'][0]['display_price'] == 34948


def test_top_price_find_vehicle_pages_render_with_initial_vin(tmp_path):
    data = catalog()
    data['items'][0]['display_price'] = 30149
    data['items'][0]['reference_price'] = 33549
    data['items'][0]['savings_amount'] = 3400
    data['items'][0]['reference_sample'] = 21
    result = render_public_pages(data, tmp_path)
    assert result['vehicle_pages'] == 1
    assert result['sitemap_urls'] == 6
    v_page = tmp_path / 'v' / '7SAYGDED1RF039277.html'
    assert v_page.is_file()
    v_html = v_page.read_text()
    assert 'data-initial-vin="7SAYGDED1RF039277"' in v_html
    assert 'https://voltsandvins.com/v/7SAYGDED1RF039277.html' in v_html
    assert '<meta property="og:image" content="https://example.test/vehicle.jpg">' in v_html
    schema=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',v_html).group(1))
    listing=next(node for node in schema['@graph'] if node['@type']=='ItemList')['itemListElement'][0]['item']
    assert listing['url']=='https://voltsandvins.com/v/7SAYGDED1RF039277.html'
    assert 'offers' not in listing
    assert 'Save $3,400' in v_html
    assert 'Built in Fremont' in v_html
    assert 'PRIVATE SUPPLIER NAME' not in v_html
    assert 'https://voltsandvins.com/v/7SAYGDED1RF039277.html' in (tmp_path / 'sitemap.xml').read_text()



def test_all_listings_get_stable_pages_without_invented_savings(tmp_path):
    data=catalog(); data['items'][0].update(reference_price=None,reference_sample=0,savings_amount=0)
    render_public_pages(data,tmp_path)
    page=tmp_path/'v'/'7SAYGDED1RF039277.html'
    assert page.exists()
    text=page.read_text()
    assert 'Save $0' not in text and 'reliable peer price benchmark is not available' in text
    assert text.count('<h1>')==1
    assert 'Built in Fremont' in text and 'Vehicle location:' in text
    assert 'https://voltsandvins.com/v/7SAYGDED1RF039277.html' in (tmp_path/'sitemap.xml').read_text()
    data['items'][0].update(reference_price=40000,reference_sample=8,savings_amount=5052)
    render_public_pages(data,tmp_path)
    assert page.exists()  # A rank change cannot remove a published VIN page.


def test_directory_reaches_every_page_and_paginates(tmp_path):
    from html.parser import HTMLParser
    from urllib.parse import urljoin,urlsplit
    import xml.etree.ElementTree as ET
    data=catalog(); row=data['items'][0]
    data['items']=[{**row,'vin':f'7SAYGDED1RF{i:06d}','state':'TX' if i%2 else 'WY','savings_amount':0} for i in range(201)]
    result=render_public_pages(data,tmp_path)
    assert result['vehicle_pages']==201 and result['browse_pages']==3
    ns={'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls={n.text for n in ET.parse(tmp_path/'sitemap.xml').findall('.//s:url/s:loc',ns)}
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.links=[]
        def handle_starttag(self,tag,attrs):
            if tag=='a':self.links += [v for k,v in attrs if k=='href']
    reached=set();queue=['https://voltsandvins.com/']
    while queue:
        url=queue.pop()
        if url in reached:continue
        reached.add(url);path=tmp_path/(urlsplit(url).path.lstrip('/') or 'index.html')
        if not path.is_file():continue
        parser=Links();parser.feed(path.read_text())
        queue.extend(target for href in parser.links if (target:=urljoin(url,href)) in urls and target not in reached)
    assert reached==urls
    second=(tmp_path/'browse'/'page-2.html').read_text()
    assert '<ol start="101">' in second
    assert 'aria-current="page">2</a>' in second
    assert 'rel="canonical" href="https://voltsandvins.com/browse/page-2.html"' in second


def test_expired_pages_leave_discovery_without_rewriting_inventory(tmp_path):
    from datetime import datetime,timezone
    data=catalog();raw=json.dumps(data)
    render_public_pages(data,tmp_path)
    data['items'][0]['expires_at']='2026-11-01T00:00:00Z'
    result=render_public_pages(data,tmp_path,now=datetime(2026,11,2,tzinfo=timezone.utc))
    assert result['vehicle_pages']==0 and not list((tmp_path/'v').glob('*.html'))
    assert data['items'][0]['display_price']==34948
    assert '7SAYGDED1RF039277' not in (tmp_path/'sitemap.xml').read_text()


def test_vehicle_schema_matches_visible_facts_and_escapes_markup(tmp_path):
    data=catalog();data['items'][0]['trim']='Base </script><script>alert(1)</script>'
    render_public_pages(data,tmp_path)
    text=(tmp_path/'v'/'7SAYGDED1RF039277.html').read_text()
    schema=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',text).group(1))
    assert schema['@graph'][0]['@type']=='Organization'
    assert all(x['@type']!='FAQPage' for x in schema['@graph'])
    car=next(x for x in schema['@graph'] if x['@type']=='ItemList')['itemListElement'][0]['item']
    assert car['driveWheelConfiguration']=='https://schema.org/RearWheelDriveConfiguration'
    assert car['url'].endswith('/v/7SAYGDED1RF039277.html')
    assert 'offers' not in car and '<script>alert(1)</script>' not in text


def test_release_fingerprint_changes_when_price_changes_without_url_change(tmp_path):
    data=catalog();render_public_pages(data,tmp_path)
    manifest=json.loads((tmp_path/'search-release.json').read_text());sitemap=(tmp_path/'sitemap.xml').read_bytes()
    data['items'][0]['display_price']+=100
    render_public_pages(data,tmp_path)
    updated=json.loads((tmp_path/'search-release.json').read_text())
    assert (tmp_path/'sitemap.xml').read_bytes()==sitemap
    assert manifest['artifact_digest']!=updated['artifact_digest']
    assert manifest['sitemap_sha256']==updated['sitemap_sha256']
    render_public_pages(data,tmp_path)
    assert json.loads((tmp_path/'search-release.json').read_text())==updated
