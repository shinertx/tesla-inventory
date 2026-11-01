"""Exclude one VIN and remove its public listing/gallery without repricing inventory.

Source photo caches remain unchanged for review. Git retains
the removed public record. Reversing publication requires review and a new build.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from tools.inventory import valid_vin


def quarantine(catalog, shards, exclusions, vin, reason):
    if not valid_vin(vin):
        raise ValueError('A valid VIN is required')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A review reason is required')
    if not isinstance(exclusions, dict):
        raise ValueError('Exclusions must be a VIN-to-reason object')
    result, media, blocked = map(copy.deepcopy, (catalog, shards, exclusions))
    blocked[vin] = reason.strip()
    removed = [x for x in result['items'] if x['vin'] == vin]
    result['items'] = [x for x in result['items'] if x['vin'] != vin]
    for shard in media.values():
        shard.pop(vin, None)
    media_changed = media != shards
    if removed:
        result['meta']['count'] = len(result['items'])
        if 'reservable_count' in result['meta']:
            result['meta']['reservable_count'] = sum(bool(x.get('reservable')) for x in result['items'])
    if media_changed:
        result['meta']['media_version'] = hashlib.sha256(
            json.dumps(media, sort_keys=True, separators=(',', ':')).encode()
        ).hexdigest()[:12]
    # No source normalization, new snapshot time, or pricing calculation occurs.
    assert result['items'] == [x for x in catalog['items'] if x['vin'] != vin]
    return result, media, blocked, len(removed)


def _write_json(path, value, *, pretty=False):
    encoded = json.dumps(value, indent=2) + '\n' if pretty else json.dumps(value, separators=(',', ':'))
    temporary = path.with_name(path.name + '.quarantine-tmp')
    temporary.write_text(encoded)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--vin', required=True)
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    root = args.root
    inventory = root / 'inventory.json'
    exclusion_path = root / 'data/exclusions.json'
    catalog = json.loads(inventory.read_text())
    exclusions = json.loads(exclusion_path.read_text())
    shard_paths = {p.stem: p for p in (root / 'media').glob('*.json')}
    shards = {key: json.loads(path.read_text()) for key, path in shard_paths.items()}
    result, media, blocked, removed = quarantine(catalog, shards, exclusions, args.vin, args.reason)
    # Persist the rebuild gate first. Interrupted projection cannot reimport the VIN.
    if blocked != exclusions:
        _write_json(exclusion_path, blocked, pretty=True)
    for key in media:
        if media[key] != shards[key]:
            _write_json(shard_paths[key], media[key])
    if result != catalog:
        _write_json(inventory, result)
    print(json.dumps({'vin': args.vin, 'removed_listings': removed,
                      'published_count': len(result['items']), 'excluded': args.vin in blocked,
                      'remaining_fields_preserved': True,
                      'snapshot_time_preserved': result['meta'].get('built_at') == catalog['meta'].get('built_at'),
                      'changed_media_shards': [k for k in media if media[k] != shards[k]]}))


if __name__ == '__main__':
    main()
