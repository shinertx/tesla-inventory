# Purchase release tools

These maintained tools package, install, verify, and roll back the existing Volts API services.
They use the existing JENNi/Jockey server. They create no accounts and do not activate payments.

Run commands from the repository root. Use a complete reviewed Git commit SHA.

## Offline safety checks

```sh
python3 -m unittest discover -s ops/purchase_release -p test_purchase_release.py -q
```

Tests use temporary repositories and databases. They do not use credentials, providers, network requests, or systemd.
The production wrapper files are reviewed fixtures. Do not run them as deployment commands.

## Package

The private catalog must exist inside the checkout and remain untracked. Preserve its original source photographs and VIN identities.

```sh
mkdir -p .data/releases
chmod 700 .data .data/releases
python3 ops/purchase_release/pack_purchase_release.py \
  --repo . \
  --sha FULL_REVIEWED_40_CHARACTER_SHA \
  --private-inventory .data/transaction_inventory.json \
  --output .data/releases/purchase-FULL_REVIEWED_40_CHARACTER_SHA.tar.gz
```

The archive contains only committed runtime and customer files. It excludes private inventory, databases, credentials, and operational documents.
The separate private inventory must produce exactly the public catalog in that commit.
Packaging rejects links, traversal, duplicate archive paths, and public full VINs.

## Install on the existing server

1. Check free disk space before unpacking or creating release copies.
2. Read both active release symlink targets.
3. Upload the reviewed bundle and these helper modules into an owner-only staging directory.
4. Upload private inventory separately with mode `0600`.
5. Preserve the staging directory with mode `0700`.
6. Run the installer without `--execute` to inspect its preflight.
7. Run the same command with `--execute` for an already authorized deployment.
8. Deploy and verify the TEST sandbox before changing production runtime code.

Example server-side preflight:

```sh
sudo python3 STAGING/install_purchase_release.py \
  --role sandbox \
  --sha FULL_REVIEWED_40_CHARACTER_SHA \
  --bundle STAGING/purchase-FULL_REVIEWED_40_CHARACTER_SHA.tar.gz \
  --private-inventory STAGING/transaction_inventory.json \
  --expected-current EXACT_CURRENT_SANDBOX_RELEASE_PATH
```

Production requires `--role production` and `--stock-wrapper-adapter`. Review its exact pinned wrapper first.
Upload all helper dependencies together. The installer imports the common, wrapper, and proof modules from its staging directory.

The installer clones the current release and preserves private history. It backs up SQLite through SQLite's backup API.
Only `INVENTORY_JSON` can change in the environment. Credentials, account bindings, workers, timers, and financial gates remain unchanged.
Production installation requires inactive collection gates and zero approved sellers. It is not a live-payment activation tool.

Only top-level `updated_at` heartbeat drift is allowed in `.data/deal_packets.json`.
The installer copies the latest active bytes into staging. Every business field and row must remain identical.
Other private-history changes stop deployment. Transaction inventory binding remains strict.

The sandbox preserves its existing synthetic fixture, approved TEST seller, TEST key, and database history.
Synthetic data never enters production. Startup checks allow the existing server time to load its catalog.

## Verify and roll back

Use the exact backup path returned by the installer.

```sh
sudo python3 STAGING/verify_purchase_release.py \
  --role sandbox \
  --sha FULL_REVIEWED_40_CHARACTER_SHA \
  --backup EXACT_BACKUP_PATH

sudo python3 STAGING/rollback_purchase_release.py --backup EXACT_BACKUP_PATH
```

Verification is read-only. It checks health, source proof, private/public binding, permissions, gates, and retained history identities.
The installed proof reuses trusted hashes only while host-local file fingerprints match. Changed or unexpected artifacts invalidate proof.

Rollback defaults to preflight. Add `--execute` only for an authorized rollback after checking the current target.
Rollback restores the prior code target and environment. It never restores an older order database automatically.

Documentation-only commits do not require an API restart. Compare packaged runtime files before deploying again.
See the root README and deposit launch document for actual activation requirements.
