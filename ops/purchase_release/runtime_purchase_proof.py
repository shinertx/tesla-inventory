"""Public artifact proof. No environment variables, keys, or private paths are returned."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent


def file_fingerprint(path):
    """ctime detects same-size edits even when a writer restores mtime."""
    try:
        info = path.stat()
        return [info.st_dev, info.st_ino, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns, info.st_mode]
    except OSError:
        return None


def _sha256(path):
    try:
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def deployment_proof():
    try:
        manifest = json.loads((ROOT / '.deployment-manifest.json').read_text())
    except (OSError, ValueError):
        return {'artifact_verification': 'unavailable', 'backend_manifest_match': False,
                'inventory_manifest_match': False, 'backend_sha': None, 'catalog_sha': None}
    fingerprints = manifest.get('artifact_fingerprints', {})
    checked = {}

    def observed(name, expected_hash):
        # A release is immutable. Reuse its installed hash only while every
        # kernel fingerprint field matches. Changed files are hashed again.
        # Cache within this request only; overlapping manifests share files.
        if name not in checked:
            recorded = fingerprints.get(name, {})
            current = file_fingerprint(ROOT / name)
            if (current is not None and recorded.get('sha256') == expected_hash
                    and recorded.get('stat') == current):
                checked[name] = expected_hash
            else:
                checked[name] = _sha256(ROOT / name)
        return checked[name]

    expected = manifest['backend_modules']
    actual = {name: observed(name, value) for name, value in expected.items()}
    # Unexpected Python modules also invalidate the recorded source identity.
    actual_names = {str(p.relative_to(ROOT)) for directory in ('app', 'tools')
                    for p in (ROOT / directory).rglob('*.py')}
    tracked_names = {name for name in expected if name.startswith(('app/', 'tools/'))}
    backend_match = actual == expected and actual_names == tracked_names
    inventory_sha = observed('inventory.json', manifest['inventory_sha256'])
    inventory_match = inventory_sha == manifest['inventory_sha256']
    expected_catalog = manifest.get('catalog_files', {'inventory.json': manifest['inventory_sha256']})
    actual_catalog = {name: observed(name, value) for name, value in expected_catalog.items()}
    actual_media_names = {str(p.relative_to(ROOT)) for p in (ROOT / 'media').rglob('*') if p.is_file()}
    tracked_media_names = {name for name in expected_catalog if name.startswith('media/')}
    catalog_match = actual_catalog == expected_catalog and actual_media_names == tracked_media_names
    expected_public = manifest.get('public_artifacts', {})
    public_names={str(p.relative_to(ROOT)) for directory in ('web','media','v','browse','models','years','states','deals')
                  for p in (ROOT/directory).rglob('*') if p.is_file()}
    root_names={'index.html','404.html','inventory.json','sitemap.xml','robots.txt','llms.txt','llms-full.txt',
                'openapi.json','search-release.json','voltsandvins-indexnow-key.txt','CNAME','.nojekyll',
                'favicon.ico','favicon.svg','manifest.webmanifest'}
    public_names|={p.name for p in ROOT.iterdir() if p.is_file() and
                   (p.name in root_names or re.fullmatch(r'google[0-9a-z]+\.html',p.name))}
    public_names|={name for name in ('data/us_zip_centers.json','data/us_city_centers.json') if (ROOT/name).is_file()}
    public_match = (bool(expected_public) and public_names==set(expected_public)
                    and all(observed(name, value) == value for name, value in expected_public.items()))
    private_inventory_match = observed('.data/transaction_inventory.json', manifest.get('private_inventory_sha256')) == manifest.get('private_inventory_sha256')
    try:
        summary = manifest.get('inventory_summary')
        if inventory_match and isinstance(summary, dict):
            media_version = summary['media_version']
            inventory_count = summary['count']
        else:
            inventory = json.loads((ROOT / 'inventory.json').read_text())
            media_version = inventory.get('meta', {}).get('media_version')
            inventory_count = len(inventory.get('items', []))
    except (OSError, ValueError, TypeError):
        media_version, inventory_count = None, None
        inventory_match = False
        catalog_match = False
    aggregate = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()
    result = dict(manifest.get('public_context', {}))
    result.update(
        artifact_verification='match' if backend_match and catalog_match and public_match and private_inventory_match else 'mismatch',
        backend_sha=manifest['backend_revision'] if backend_match and public_match and private_inventory_match else None,
        catalog_sha=manifest['catalog_revision'] if catalog_match and public_match and private_inventory_match else None,
        expected_backend_revision=manifest['backend_revision'],
        expected_catalog_revision=manifest['catalog_revision'],
        backend_manifest_match=backend_match,
        public_artifact_manifest_match=public_match,
        private_inventory_manifest_match=private_inventory_match,
        private_inventory_sha256=manifest.get('private_inventory_sha256'),
        inventory_manifest_match=inventory_match,
        catalog_manifest_match=catalog_match,
        catalog_file_manifest_sha256=hashlib.sha256(json.dumps(actual_catalog, sort_keys=True).encode()).hexdigest(),
        backend_module_manifest_sha256=aggregate,
        inventory_sha256=inventory_sha,
        media_version=media_version,
        inventory_count=inventory_count,
    )
    if result.get('sandbox'):
        result['source_sha'] = result['backend_sha']
    return result
