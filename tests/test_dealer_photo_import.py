"""Local bytes and mock sockets only; no dealer feed or external network."""
import io
import json
from pathlib import Path
import pytest
from PIL import Image
from tools import import_dealer_photos as importer
from tools.export_photo_recovery import project_photos, nonphoto_catalog

VIN = '7SAYGDED1RF039277'
OTHER = '5YJ3E1EA8SF921313'
HOST = 'photos.example.test'
URL = 'https://' + HOST + '/front.jpg'
REAR = 'https://' + HOST + '/rear.jpg'
CATALOG = {'meta': {'built_at': 'fixture-date'}, 'items': [{'vin': VIN, 'photo': URL, 'photo_count': 1, 'display_price': 30000, 'reservable': False}]}


def image(color='red', size=(120, 100)):
    out = io.BytesIO(); Image.new('RGB', size, color).save(out, format='JPEG'); return out.getvalue()


def run(feed=None, retained=None, fetch=None, **kwargs):
    return importer.review_feed(feed or {VIN: [REAR]}, CATALOG, retained or {},
        allowed_hosts={HOST}, authorization_reference='fixture-authorized-feed',
        fetch=fetch or (lambda *_: ('image/jpeg', image())), **kwargs)


def test_default_is_offline_and_does_not_claim_rights():
    delta, report = run(fetch=lambda *_: pytest.fail('network called'))
    assert delta == {} and report['accepted_photos'] == 0 and report['rights_verified'] is False
    assert report['receipts'][0]['result'] == 'verification_not_requested'


def test_csv_and_current_json_input(tmp_path):
    csv = tmp_path/'feed.csv'; csv.write_text('vin,url,title\n'+VIN+','+REAR+',Rear exterior\n')
    parsed = importer.read_feed(csv); assert parsed[VIN][0]['url'] == REAR
    js = tmp_path/'feed.json'; js.write_text(json.dumps({VIN: [URL, {'url': REAR, 'title': 'Rear'}]}))
    assert importer.read_feed(js)[VIN][0] == URL
    csv.write_text('url,title\n'+REAR+',Rear\n')
    with pytest.raises(ValueError): importer.read_feed(csv)
    js.write_text('[]')
    with pytest.raises(ValueError): importer.read_feed(js)


def test_append_preserves_gallery_and_all_nonphoto_fields():
    old = {'url': URL, 'title': 'Original primary', 'category': 'exterior'}
    calls = []
    def fetch(url, _):
        calls.append(url); return 'image/jpeg', image('red' if url == URL else 'blue')
    delta, report = run(retained={VIN: [old]}, fetch=fetch, verify=True)
    assert report['accepted_photos'] == 1 and calls == [URL, REAR]
    assert set(delta[VIN][0]) == {'url', 'title', 'category'}
    shards = {format(int(VIN[-3:]) % 128, '02x'): {VIN: [old]}}
    after, media, changed = project_photos(CATALOG, shards, delta)
    assert changed == [VIN] and after['items'][0]['photo'] == URL
    assert media[next(iter(shards))][VIN][0] == old
    assert after['items'][0]['photo_count'] == 2 and nonphoto_catalog(after) == nonphoto_catalog(CATALOG)


def test_deduplicates_urls_and_exact_content_against_retained():
    calls = []
    def fetch(url, _): calls.append(url); return 'image/jpeg', image()
    delta, report = run({VIN: [URL, REAR, REAR]}, retained={VIN: [URL]}, fetch=fetch, verify=True)
    assert delta == {} and calls == [URL, REAR]
    assert sorted(r['result'] for r in report['receipts']) == ['duplicate_content', 'duplicate_feed_url', 'duplicate_url']


def test_existing_unverified_media_blocks_new_additions():
    def fetch(url, _):
        if url == URL: raise importer.ImageRejected('http_status', 404)
        pytest.fail('New photo must not bypass retained content comparison')
    delta, report = run(retained={VIN: [URL]}, fetch=fetch, verify=True)
    assert delta == {} and report['receipts'][0]['http_status'] == 404


@pytest.mark.parametrize('status', [403, 429])
def test_host_stops_after_first_block_without_retry(status):
    calls = []
    def fetch(url, _): calls.append(url); raise importer.ImageRejected('http_status', status)
    delta, report = run({VIN: [URL, REAR]}, fetch=fetch, verify=True)
    assert delta == {} and calls == [URL] and report['blocked_hosts'] == [HOST]
    assert report['receipts'][1]['result'] == 'host_stopped'


@pytest.mark.parametrize('url', ['http://'+HOST+'/x.jpg', 'https://user:secret@'+HOST+'/x.jpg',
    'https://'+HOST+':444/x.jpg', 'https://127.0.0.1/x.jpg', 'https://localhost/x.jpg',
    'https://evil.example/x.jpg', 'https://'+HOST+'/x.jpg#fragment', 'https://'+HOST+'/x\r\ny.jpg'])
def test_rejects_unsafe_destinations_before_fetch(url):
    with pytest.raises(importer.ImageRejected): importer.checked_url(url, {HOST, '127.0.0.1', 'localhost'})


def test_rejects_dns_private_or_mixed_addresses_before_connection(monkeypatch):
    monkeypatch.setattr(importer.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('127.0.0.1', 443))])
    monkeypatch.setattr(importer.socket, 'create_connection', lambda *a, **k: pytest.fail('private connection'))
    with pytest.raises(importer.ImageRejected, match='private_destination'): importer.fetch_image(URL, {HOST})


@pytest.mark.parametrize('content_type,body', [('text/html', b'<html>not photo</html>'),
    ('image/jpeg', b'not jpeg'), ('image/jpeg', image(size=(20, 20))),
    ('image/jpeg', b'x' * (importer.MAX_BYTES + 1))])
def test_content_and_size_validation(content_type, body):
    with pytest.raises(importer.ImageRejected): importer.image_evidence(content_type, body)


def test_unknown_and_quarantined_vins_rejected_without_fetch():
    delta, report = run({VIN: [URL], OTHER: [URL], 'bad': [URL]}, verify=True,
        excluded_vins={VIN}, fetch=lambda *_: pytest.fail('network'))
    assert not delta and all(r['result'] == 'rejected_vin' for r in report['receipts'])


def test_no_redirect_follow_and_public_ip_pinned(monkeypatch):
    calls = []
    class FakeTLS:
        def __init__(self): self.raw = io.BytesIO(b'HTTP/1.1 302 Found\r\nLocation: https://127.0.0.1/private\r\nContent-Length: 0\r\n\r\n')
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): assert 0 < timeout <= importer.TIMEOUT
        def sendall(self, body): assert b'Host: photos.example.test' in body
        def recv_into(self, buffer):
            chunk = self.raw.read(len(buffer)); buffer[:len(chunk)] = chunk; return len(chunk)
    tls = FakeTLS()
    class Context:
        def wrap_socket(self, sock, server_hostname): assert server_hostname == HOST; return tls
    def connect(address, timeout): calls.append(address); return tls
    monkeypatch.setattr(importer.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('8.8.8.8', 443))])
    monkeypatch.setattr(importer.socket, 'create_connection', connect)
    monkeypatch.setattr(importer.ssl, 'create_default_context', lambda: Context())
    with pytest.raises(importer.ImageRejected) as caught: importer.fetch_image(URL, {HOST})
    assert caught.value.status == 302 and calls == [('8.8.8.8', 443)]


def test_deadline_reader_stops_after_total_timeout(monkeypatch):
    class Socket:
        def recv_into(self, buffer): pytest.fail('expired connection read')
    monkeypatch.setattr(importer.time, 'monotonic', lambda: 12)
    with pytest.raises(TimeoutError): importer._DeadlineReader(Socket(), 10).readinto(bytearray(10))


def test_no_url_rewriting_or_silent_malformed_entries():
    url = 'https://static.cargurus.com/vehicle.jpg?width=320'
    delta, report = importer.review_feed({VIN: [url, {}, None]}, CATALOG, {},
        allowed_hosts={'static.cargurus.com'}, authorization_reference='fixture', verify=True,
        fetch=lambda *_: pytest.fail('Invalid or rewritten URLs must not fetch'))
    assert delta == {} and report['input_photo_entries'] == 3
    assert len(report['receipts']) == 3
    assert all(row['result'] == 'invalid_or_rewritten_photo_url' for row in report['receipts'])


def test_outputs_exclusive_private_and_catalog_untouched(tmp_path):
    import os
    private = tmp_path/'.data/source_snapshot.json'; private.parent.mkdir(); private.write_text('private source')
    catalog = tmp_path/'inventory.json'; catalog.write_text('catalog')
    outputs = [importer.REVIEW_DIRECTORY/'delta.json', importer.REVIEW_DIRECTORY/'report.json']
    importer.write_review_outputs(tmp_path, outputs, [{}, {'ok': True}])
    assert (tmp_path/outputs[0]).read_text() == '{}\n'
    assert os.stat(tmp_path/outputs[0]).st_mode & 0o777 == 0o600
    assert os.stat(tmp_path/importer.REVIEW_DIRECTORY).st_mode & 0o777 == 0o700
    with pytest.raises(ValueError, match='already exist'):
        importer.write_review_outputs(tmp_path, outputs, [{'overwrite': True}, {}])
    assert (tmp_path/outputs[0]).read_text() == '{}\n'
    assert private.read_text() == 'private source' and catalog.read_text() == 'catalog'


@pytest.mark.parametrize('target', ['data/exclusions.json', '.data/source_snapshot.json', 'inventory.json', 'media/00.json', '../outside.json'])
def test_output_cannot_overwrite_protected_inputs(tmp_path, target):
    protected = tmp_path/target; protected.parent.mkdir(parents=True, exist_ok=True); protected.write_text('original')
    with pytest.raises(ValueError):
        importer.write_review_outputs(tmp_path, [target, importer.REVIEW_DIRECTORY/'other.json'], [{}, {}])
    assert protected.read_text() == 'original'
    assert not (tmp_path/importer.REVIEW_DIRECTORY/'other.json').exists()


def test_absolute_outside_root_output_rejected(tmp_path):
    with pytest.raises(ValueError):
        importer.write_review_outputs(tmp_path, [tmp_path.parent/'outside-photo-review.json', importer.REVIEW_DIRECTORY/'report.json'], [{}, {}])


@pytest.mark.parametrize('link_kind', ['symlink', 'hardlink'])
def test_existing_links_cannot_overwrite_other_private_file(tmp_path, link_kind):
    import os
    source = tmp_path/'.data/source_snapshot.json'; source.parent.mkdir(); source.write_text('private preserved')
    directory = tmp_path/importer.REVIEW_DIRECTORY; directory.mkdir(mode=0o700)
    link = directory/'delta.json'
    if link_kind == 'symlink': link.symlink_to(source)
    else: os.link(source, link)
    with pytest.raises(ValueError, match='already exist'):
        importer.write_review_outputs(tmp_path, [link, directory/'report.json'], [{}, {}])
    assert source.read_text() == 'private preserved'
    assert not (directory/'report.json').exists()


def test_symlink_review_directory_rejected(tmp_path):
    directory = tmp_path/'.data'; directory.mkdir()
    other = tmp_path/'other-private'; other.mkdir()
    (directory/'dealer-photo-reviews').symlink_to(other, target_is_directory=True)
    with pytest.raises(OSError):
        importer.write_review_outputs(tmp_path, [importer.REVIEW_DIRECTORY/'delta.json', importer.REVIEW_DIRECTORY/'report.json'], [{}, {}])
    assert not list(other.iterdir())
