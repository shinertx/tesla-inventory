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
    assert result['published'] == 1 and result['sitemap_urls'] == 4
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
