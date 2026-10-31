#!/usr/bin/env python3
"""Submit all sitemap.xml URLs to IndexNow (Bing, DuckDuckGo, Yahoo, ChatGPT Search)."""
import json, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
KEY = '7f9a2d4c8e1b6a3f5c0d9e8b7a6f5e4d'

def load_sitemap_urls(sitemap_path=ROOT / 'sitemap.xml'):
    tree = ET.parse(sitemap_path)
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    return [el.text.strip() for el in tree.findall('.//s:loc', ns) if el.text]

def build_indexnow_payload(urls=None):
    urls = urls if urls is not None else load_sitemap_urls()
    host = urlsplit(urls[0]).hostname if urls else 'voltsandvins.com'
    return {
        'host': host,
        'key': KEY,
        'keyLocation': f'https://{host}/voltsandvins-indexnow-key.txt',
        'urlList': urls,
    }

def ping_indexnow(urls=None, endpoint='https://api.indexnow.org/indexnow'):
    payload = build_indexnow_payload(urls)
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return {'status': resp.status, 'submitted': len(payload['urlList']), 'host': payload['host']}

if __name__ == '__main__':
    print(json.dumps(ping_indexnow()))
