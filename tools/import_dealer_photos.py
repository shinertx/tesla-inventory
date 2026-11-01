"""Stage an authorized VIN gallery feed; never scrape or publish a catalog.

CSV columns: vin,url,title,category (last two optional). JSON: {VIN: [URL or photo]}.
Default is offline review with an empty delta. --verify explicitly permits bounded
image downloads from exact --allow-host names. An authorization reference records
operator input; neither that reference nor a host allowlist proves display rights.
"""
import argparse
import csv
import hashlib
import http.client
import io
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import time
import warnings
from urllib.parse import urlsplit

from PIL import Image
from tools.inventory import valid_vin
from tools.media import normalize_photos

MAX_BYTES = 5_000_000
MAX_PIXELS = 20_000_000
TIMEOUT = 10


class ImageRejected(ValueError):
    def __init__(self, reason, status=None):
        self.reason, self.status = reason, status
        super().__init__(reason)


def checked_url(url, allowed_hosts):
    if not isinstance(url, str) or len(url) > 4000 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ImageRejected('invalid_url')
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443) or p.fragment:
            raise ImageRejected('https_public_url_required')
        host = p.hostname.lower()
        if host not in allowed_hosts or host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ImageRejected('host_not_allowed')
        try:
            if not ipaddress.ip_address(host).is_global: raise ImageRejected('private_destination')
        except ValueError as exc:
            if isinstance(exc, ImageRejected): raise
        return p
    except ValueError as exc:
        if isinstance(exc, ImageRejected): raise
        raise ImageRejected('invalid_url') from None


class _DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
    def readable(self): return True
    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError()
        self.sock.settimeout(remaining)
        return self.sock.recv_into(buffer)


class _DeadlineSocket:
    def __init__(self, sock, deadline): self.sock, self.deadline = sock, deadline
    def makefile(self, mode): return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))
    def __getattr__(self, name): return getattr(self.sock, name)


def fetch_image(url, allowed_hosts):
    """Resolve only public addresses, pin TLS to that address, and never redirect."""
    p = checked_url(url, allowed_hosts)
    started = time.monotonic()
    try:
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
            raise ImageRejected('private_destination')
        deadline = started + TIMEOUT
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError()
        # No second DNS lookup: TLS verifies the original host against the pinned address.
        with socket.create_connection((addresses[0][4][0], 443), timeout=remaining) as tcp:
            tcp.settimeout(max(.001, deadline - time.monotonic()))
            with ssl.create_default_context().wrap_socket(tcp, server_hostname=p.hostname) as tls:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError()
                tls.settimeout(remaining)
                target = (p.path or '/') + ('?' + p.query if p.query else '')
                tls.sendall(('GET ' + target + ' HTTP/1.1\r\nHost: ' + p.hostname +
                    '\r\nAccept: image/jpeg,image/png,image/webp\r\nUser-Agent: VoltsVINsFeedReview/1.0\r\nConnection: close\r\n\r\n').encode('ascii'))
                response = http.client.HTTPResponse(_DeadlineSocket(tls, deadline))
                response.begin()
                if response.status != 200: raise ImageRejected('http_status', response.status)
                length = response.getheader('Content-Length')
                if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
                    raise ImageRejected('byte_limit')
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES: raise ImageRejected('byte_limit')
                return response.getheader('Content-Type', '').split(';')[0].lower(), body
    except ImageRejected: raise
    except (OSError, ValueError, http.client.HTTPException, UnicodeError):
        raise ImageRejected('network_error') from None


def image_evidence(content_type, body):
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BYTES:
        raise ImageRejected('byte_limit')
    if content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ImageRejected('not_image')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as image:
                width, height = image.size
                if min(width, height) < 100 or width * height > MAX_PIXELS or image.format not in {'JPEG', 'PNG', 'WEBP'} or getattr(image, 'is_animated', False):
                    raise ImageRejected('image_dimensions_or_format')
                image.verify()
            with Image.open(io.BytesIO(body)) as image: image.load()
    except ImageRejected: raise
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected('undecodable_image') from None
    return {'sha256': hashlib.sha256(body).hexdigest(), 'width': width, 'height': height, 'bytes': len(body)}


def read_feed(path):
    path = Path(path)
    if path.stat().st_size > 10_000_000: raise ValueError('Feed exceeds 10 MB')
    if path.suffix.lower() == '.csv':
        result = {}
        with path.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            if not {'vin', 'url'}.issubset(reader.fieldnames or []): raise ValueError('CSV requires vin,url columns')
            for row in reader: result.setdefault(row['vin'].strip(), []).append({k: row.get(k, '') for k in ('url', 'title', 'category')})
        return result
    result = json.loads(path.read_text())
    if not isinstance(result, dict) or any(not isinstance(x, list) for x in result.values()):
        raise ValueError('JSON requires VIN keys and photo lists')
    return result


def review_feed(feed, catalog, retained, *, allowed_hosts, authorization_reference, verify=False, fetch=fetch_image, excluded_vins=()):
    if not isinstance(authorization_reference, str) or not authorization_reference.strip():
        raise ValueError('An operator-supplied authorization reference is required')
    hosts = {h.lower() for h in allowed_hosts}
    if not hosts or any('/' in h or ':' in h or '*' in h or not h for h in hosts):
        raise ValueError('Supply explicit HTTPS host names')
    known = {x['vin'] for x in catalog['items']}; excluded = set(excluded_vins)
    delta, receipts, blocked, cache = {}, [], set(), {}
    def check(url):
        p = checked_url(url, hosts)
        if p.hostname in blocked: raise ImageRejected('host_stopped')
        if url not in cache:
            try:
                content_type, body = fetch(url, hosts)
                cache[url] = image_evidence(content_type, body)
            except ImageRejected as exc:
                if exc.status in (403, 429): blocked.add(p.hostname)
                cache[url] = exc
        if isinstance(cache[url], ImageRejected): raise cache[url]
        return cache[url]
    for vin, supplied in feed.items():
        if not valid_vin(vin) or vin not in known or vin in excluded:
            receipts.append({'vin': vin, 'result': 'rejected_vin'}); continue
        old = normalize_photos(retained.get(vin, [])); old_urls = {p['url'] for p in old}
        candidates, supplied_urls = [], set()
        for value in supplied:
            supplied_url = value if isinstance(value, str) else value.get('url') if isinstance(value, dict) else None
            normalized = normalize_photos([value])
            if not normalized or normalized[0]['url'] != supplied_url:
                receipts.append({'vin': vin, 'result': 'invalid_or_rewritten_photo_url'}); continue
            if supplied_url in supplied_urls:
                receipts.append({'vin': vin, 'url': supplied_url, 'result': 'duplicate_feed_url'}); continue
            supplied_urls.add(supplied_url); candidates.append(normalized[0])
        for candidate in candidates:
            url = candidate['url']; row = {'vin': vin, 'url': url}
            if url in old_urls:
                receipts.append({**row, 'result': 'duplicate_url'}); continue
            try:
                checked_url(url, hosts)
                if not verify: raise ImageRejected('verification_not_requested')
                # Fail closed if retained media cannot be checked for byte duplicates.
                hashes = {check(p['url'])['sha256'] for p in old}
                evidence = check(url)
                if evidence['sha256'] in hashes:
                    receipts.append({**row, 'result': 'duplicate_content'}); continue
                delta.setdefault(vin, []).append(candidate); old.append(candidate); old_urls.add(url)
                receipts.append({**row, 'result': 'accepted', **evidence})
            except ImageRejected as exc:
                receipts.append({**row, 'result': exc.reason, **({'http_status': exc.status} if exc.status else {})})
    return delta, {'authorization_reference': authorization_reference, 'rights_verified': False,
        'authorization_notice': 'Operator-supplied reference; host allowlisting does not establish display rights.',
        'verification_requested': verify, 'accepted_vins': len(delta), 'accepted_photos': sum(map(len, delta.values())),
        'blocked_hosts': sorted(blocked), 'receipts': receipts, 'catalog_written': False,
        'input_photo_entries': sum(len(values) for values in feed.values()),
        'dedupe_scope': 'Exact URL and exact bytes only; distinct-angle review is still required.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--allow-host', action='append', required=True)
    parser.add_argument('--authorization-reference', required=True)
    parser.add_argument('--verify', action='store_true', help='Allow bounded image downloads; default makes no network calls')
    parser.add_argument('--delta-out', type=Path, default=Path('.data/dealer-photo-delta.json'))
    parser.add_argument('--report-out', type=Path, default=Path('.data/dealer-photo-review.json'))
    args = parser.parse_args(); root = args.root.resolve(); catalog_path = root / 'inventory.json'; media = root / 'media'
    outputs = [args.delta_out.resolve(), args.report_out.resolve()]
    if len(set(outputs)) != 2 or any(p in {catalog_path.resolve(), args.feed.resolve()} or media.resolve() in p.parents for p in outputs):
        parser.error('Outputs must be separate review files, not feed/catalog/media inputs')
    catalog = json.loads(catalog_path.read_text()); retained = {}
    for p in media.glob('*.json'): retained.update(json.loads(p.read_text()))
    for row in catalog['items']:
        retained.setdefault(row['vin'], row.get('photos') or ([row['photo']] if row.get('photo') else []))
    exclusions_path = root / 'data/exclusions.json'
    exclusions = json.loads(exclusions_path.read_text()) if exclusions_path.exists() else {}
    delta, report = review_feed(read_feed(args.feed), catalog, retained, allowed_hosts=args.allow_host,
        authorization_reference=args.authorization_reference, verify=args.verify, excluded_vins=exclusions)
    for path, value in zip(outputs, (delta, report)):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2)+'\n')
    print(json.dumps({'accepted_vins': report['accepted_vins'], 'accepted_photos': report['accepted_photos'], 'network_enabled': args.verify}))


if __name__ == '__main__': main()
