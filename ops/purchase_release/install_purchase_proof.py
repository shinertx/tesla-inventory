"""Extend the existing installer helper with public corpus and private-map integrity."""
from pathlib import Path
import json
from install_proof_manifest import install_proof
from purchase_release_common import digest,allowed,META
from runtime_purchase_proof import file_fingerprint


def install(release,sha,context):
    release=Path(release)
    runtime=Path(__file__).with_name('runtime_purchase_proof.py')
    result=install_proof(release,sha,sha,context,runtime)
    manifest_path=release/'.deployment-manifest.json';manifest=json.loads(manifest_path.read_text())
    # Both roles prove their frontend, including the intentionally transformed sandbox index.
    for path in (release/'web').rglob('*'):
        if path.is_file():manifest['backend_modules'][path.relative_to(release).as_posix()]=digest(path)
    manifest['backend_modules']['index.html']=digest(release/'index.html')
    manifest['public_artifacts']={path.relative_to(release).as_posix():digest(path)
        for path in sorted(release.rglob('*')) if path.is_file()
        and (allowed(path.relative_to(release).as_posix())
             or (context.get('sandbox') and path.relative_to(release).as_posix()=='media/sandbox.svg'))
        and path.relative_to(release).parts[0] not in ('app','tools')
        and path.name not in (META,'requirements.txt')}
    # The public proof returns only a match boolean and digest, never private rows or paths.
    manifest['private_inventory_sha256']=digest(release/'.data/transaction_inventory.json')
    # Establish trusted fingerprints once, before this release serves traffic.
    # Hashing is bracketed by stat reads so concurrent writes cannot receive a
    # fingerprint for older bytes. The runtime never uses a time-based cache.
    expected={**manifest['backend_modules'],**manifest['catalog_files'],
              **manifest['public_artifacts'],
              '.data/transaction_inventory.json':manifest['private_inventory_sha256']}
    fingerprints={}
    for name,expected_hash in expected.items():
        path=release/name;before=file_fingerprint(path);actual=digest(path)
        after=file_fingerprint(path)
        if before is None or before!=after or actual!=expected_hash:
            raise ValueError('An artifact changed while recording release fingerprints')
        fingerprints[name]={'sha256':actual,'stat':after}
    inventory_path=release/'inventory.json'
    before=file_fingerprint(inventory_path)
    inventory=json.loads(inventory_path.read_text())
    if before!=file_fingerprint(inventory_path) or before!=fingerprints['inventory.json']['stat']:
        raise ValueError('Inventory changed while recording its summary')
    manifest['artifact_fingerprints']=fingerprints
    manifest['inventory_summary']={'count':len(inventory.get('items',[])),
                                   'media_version':inventory.get('meta',{}).get('media_version')}
    manifest['manifest_version']=3
    manifest_path.write_text(json.dumps(manifest,sort_keys=True));manifest_path.chmod(0o644)
    return {**result,'public_artifact_count':len(manifest['public_artifacts'])}
