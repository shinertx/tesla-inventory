#!/usr/bin/env python3
"""Scan vehicle photos via OCR + edge-banner analysis on VM to exclude dealer-branded slides and dead 403 URLs while preserving Tesla touchscreen equipment photos."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHONE_RE = re.compile(r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b')
URL_RE = re.compile(r'\b[a-z0-9-]{3,}\.(?:com|net|auto|cars|motors|dealer)\b', re.I)
DEALER_BANNER_RE = re.compile(
    r'\b(?:call\s+now|call\s+today|call\s+us|text\s+us|se\s+habla|we\s+finance|bad\s+credit|no\s+credit|'
    r'buy\s+here\s+pay\s+here|autonation|echopark|carvana|carmax|lithia|penske|sonic\s+automotive|'
    r'hendrick|group\s+1|auto\s+sales|motorsports|auto\s+group|dealership|warranty\s+forever|'
    r'free\s+carfax|carfax\s+1-owner|www\.)\b',
    re.I,
)
TESLA_SCREEN_ALLOW_RE = re.compile(
    r'\b(?:full\s+self[- ]driving|autopilot|pedals\s*&\s*steering|charging|software|additional\s+vehicle|'
    r'amd\s+ryzen|intel\s+atom|audio\s+system|trips|locks|lights|display|navigation)\b',
    re.I,
)


def classify_photo_bytes(body: bytes) -> tuple[bool, str]:
    """Return (exclude, reason). Never exclude Tesla center-screen software/FSD photos."""
    from PIL import Image, ImageStat
    import pytesseract

    img = Image.open(io.BytesIO(body)).convert('RGB')
    w, h = img.size
    if w < 160 or h < 120:
        return True, 'tiny_placeholder'

    # Check full text on resized frame for speed, plus top/bottom 18% banner strips.
    scale = min(1.0, 960.0 / max(w, h))
    small = img.resize((max(1, int(w * scale)), max(1, int(h * scale)))) if scale < 1.0 else img
    text_full = pytesseract.image_to_string(small, config='--psm 6') or ''
    if TESLA_SCREEN_ALLOW_RE.search(text_full):
        return False, 'tesla_screen_preserved'

    if PHONE_RE.search(text_full):
        return True, 'dealer_phone_detected'
    url_match = URL_RE.search(text_full)
    if url_match and 'tesla.com' not in url_match.group(0).lower():
        return True, 'dealer_url_detected'
    if DEALER_BANNER_RE.search(text_full):
        return True, 'dealer_banner_text'

    # Check solid top/bottom overlay bar with dense text
    top_strip = small.crop((0, 0, small.width, max(1, int(small.height * 0.14))))
    bot_strip = small.crop((0, int(small.height * 0.86), small.width, small.height))
    for label, strip in (('top', top_strip), ('bottom', bot_strip)):
        stat = ImageStat.Stat(strip)
        avg_std = sum(stat.stddev) / 3.0
        strip_text = (pytesseract.image_to_string(strip, config='--psm 7') or '').strip()
        alpha_chars = sum(c.isalnum() for c in strip_text)
        if alpha_chars >= 10 and avg_std < 52.0:
            return True, f'{label}_dealer_overlay_bar'

    return False, 'clean'


def scan_url(url: str, timeout: int = 10) -> tuple[str, bool, str]:
    from curl_cffi import requests

    try:
        resp = requests.get(url, impersonate='chrome120', timeout=timeout)
        if resp.status_code in (403, 404, 410):
            return url, True, f'http_{resp.status_code}_dead_photo'
        if resp.status_code != 200 or not (resp.headers.get('Content-Type') or '').lower().startswith('image/'):
            return url, False, f'skip_status_{resp.status_code}'
        exclude, reason = classify_photo_bytes(resp.content)
        return url, exclude, reason
    except Exception as exc:
        return url, False, f'err:{type(exc).__name__}'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=600, help='Max unique candidate URLs to scan per pass')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--curated-only', action='store_true', default=True)
    args = parser.parse_args()

    exclusions_path = ROOT / 'data/photo_exclusions.json'
    existing = set(json.loads(exclusions_path.read_text())) if exclusions_path.exists() else set()
    state_path = ROOT / '.data/ocr_scanned_urls.json'
    scanned = set(json.loads(state_path.read_text())) if state_path.exists() else set()

    priv_path = ROOT / '.data/transaction_inventory.json'
    rows = json.loads(priv_path.read_text()).get('items', []) if priv_path.exists() else []
    candidates: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if args.curated_only and row.get('curated') is False:
            continue
        urls = [row.get('photo')] + [
            (p.get('url') if isinstance(p, dict) else p) for p in (row.get('photos') or [])[:3]
        ]
        # Also inspect the final slide in multi-photo galleries (common dealer promo graphic)
        photos_list = row.get('photos') or []
        if len(photos_list) > 3:
            last = photos_list[-1]
            urls.append(last.get('url') if isinstance(last, dict) else last)
        for u in urls:
            if isinstance(u, str) and u.startswith('https://') and u not in existing and u not in scanned and u not in seen:
                seen.add(u)
                candidates.append(u)
                if len(candidates) >= args.limit:
                    break
        if len(candidates) >= args.limit:
            break

    reasons_count: dict[str, int] = {}
    newly_excluded: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(scan_url, u): u for u in candidates}
        for fut in as_completed(futures):
            url, exclude, reason = fut.result()
            scanned.add(url)
            reasons_count[reason] = reasons_count.get(reason, 0) + 1
            if exclude:
                existing.add(url)
                newly_excluded.append(url)

    exclusions_path.write_text(json.dumps(sorted(existing), indent=2) + '\n')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(scanned)))
    print(json.dumps({
        'scanned_now': len(candidates),
        'newly_excluded': len(newly_excluded),
        'total_photo_exclusions': len(existing),
        'reasons': reasons_count,
    }))


if __name__ == '__main__':
    main()
