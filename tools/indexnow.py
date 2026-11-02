#!/usr/bin/env python3
"""Notify IndexNow of public URL changes. HTTP acceptance does not prove indexing."""
import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
KEY = '7f9a2d4c8e1b6a3f5c0d9e8b7a6f5e4d'
HOST = 'voltsandvins.com'
MAX_URLS = 10_000


class IndexNowSubmissionError(RuntimeError):
    """A failed batch, retaining prior HTTP acceptance results for reconciliation."""
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def load_sitemap_urls(sitemap_path=ROOT / 'sitemap.xml'):
    tree = ET.parse(sitemap_path)
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    return [el.text.strip() for el in tree.findall('.//s:loc', ns) if el.text]


def _validated_urls(urls):
    urls = load_sitemap_urls() if urls is None else urls
    if isinstance(urls, (str, bytes)):
        raise ValueError('IndexNow URLs must be a collection of absolute HTTPS URLs')
    normalized = set()
    for value in urls:
        if not isinstance(value, str) or not value or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in value) or '\\' in value:
            raise ValueError('IndexNow URL contains invalid whitespace or characters')
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme == 'https' and parsed.hostname == HOST
                and parsed.username is None and parsed.password is None and parsed.port in (None, 443)
                and not parsed.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(f'IndexNow URLs must use HTTPS on {HOST}, without credentials, fragments, or alternate ports')
        normalized.add(urlunsplit(('https', HOST, parsed.path or '/', parsed.query, '')))
    return sorted(normalized)


def build_indexnow_payload(urls=None):
    urls = _validated_urls(urls)
    if len(urls)>MAX_URLS:
        raise ValueError('An IndexNow payload cannot exceed 10,000 URLs; use ping_indexnow for batching')
    return {'host':HOST, 'key':KEY,
        'keyLocation':f'https://{HOST}/voltsandvins-indexnow-key.txt', 'urlList':urls}


def ping_indexnow(urls=None, endpoint='https://api.indexnow.org/indexnow'):
    urls = _validated_urls(urls)  # Validate the entire input before any submission.
    result = {'status':None, 'submitted':0, 'host':HOST, 'total_urls':len(urls),
              'accepted':False, 'batches':[]}
    if not urls:
        return {**result, 'skipped':True}
    for offset in range(0, len(urls), MAX_URLS):
        chunk = urls[offset:offset+MAX_URLS]
        req = urllib.request.Request(endpoint, data=json.dumps(build_indexnow_payload(chunk)).encode('utf-8'),
            headers={'Content-Type':'application/json; charset=utf-8'}, method='POST')
        batch = {'batch':len(result['batches'])+1, 'url_count':len(chunk), 'status':None, 'accepted':False}
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                batch['status'] = resp.status
        except urllib.error.HTTPError as exc:
            batch['status'] = exc.code
            exc.close()
        except (urllib.error.URLError, OSError) as exc:
            batch['error'] = str(exc)
        batch['accepted'] = batch['status'] in (200, 202)
        if batch['accepted']:
            batch['receipt'] = 'key_validation_pending' if batch['status']==202 else 'received'
            result['submitted'] += len(chunk)
        result['batches'].append(batch)
        result['status'] = batch['status']
        if not batch['accepted']:
            reason = f"HTTP {batch['status']}" if batch['status'] is not None else 'transport error'
            raise IndexNowSubmissionError(
                f"IndexNow batch {batch['batch']} failed ({reason}); {result['submitted']} of {len(urls)} URLs accepted before failure",
                result)
    result['accepted'] = True
    return result


if __name__ == '__main__':
    print(json.dumps(ping_indexnow()))
