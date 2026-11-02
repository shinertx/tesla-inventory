"""Explicit local-on-host installer. Default invocation is a read-only preflight.

No credential, provider, account, routing, worker, or activation changes are made.
Only --execute permits release creation, backups, the inventory env edit, and restart.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import pwd
import re
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.request
from purchase_release_common import (FIXTURE_VIN,META,PAGE_DIRS,ROOT_FILES,digest,parse_env,
    inventory_env,reject_links,safe_json,unpack_bundle,private_matches,catalog_module,refresh_private_history)
from install_purchase_proof import install as install_proof
from stock_wrapper_adapter import adapt


def run(*args):subprocess.run(args,check=True,stdout=subprocess.DEVNULL)


def read_json(url):
    with urllib.request.urlopen(url,timeout=20) as response:return json.load(response)


def guard_environment(env,role):
    if role=='production':
        for key in ('SANDBOX_MODE','CHECKOUT_ENABLED','BALANCE_CHECKOUT_ENABLED','PLATFORM_AGREEMENTS_VERIFIED'):
            if env.get(key)!='false':raise ValueError('A production activation gate is not explicitly false')
        if env.get('STRIPE_AUTHORIZATION_WRITES_VERIFIED','false')!='false':
            raise ValueError('Production authorization writes must remain unverified')
        if env.get('STRIPE_SECRET_KEY') and not env['STRIPE_SECRET_KEY'].startswith(('rk_live_','sk_live_')):
            raise ValueError('Production credential mode changed')
    elif env.get('SANDBOX_MODE')!='true' or not env.get('STRIPE_SECRET_KEY','').startswith('sk_test_'):
        raise ValueError('Sandbox must retain its existing Stripe TEST configuration')


def fixture_from(old,env):
    private=old/'.data/transaction_inventory.json'
    inventory=json.loads((private if private.is_file() else old/'inventory.json').read_text())
    fixtures=[row for row in inventory['items'] if row.get('vin')==FIXTURE_VIN]
    if len(fixtures)!=1:raise ValueError('Sandbox fixture is missing or duplicated')
    if not (old/'media/sandbox.svg').is_file():raise ValueError('Sandbox fixture image is missing')
    return fixtures[0]


def sandbox_frontend(index):
    source=index.read_text()
    source=re.sub(r'<meta\s+name="robots"[^>]*>', '<meta name="robots" content="noindex,nofollow">',source,count=1)
    if 'name="robots" content="noindex,nofollow"' not in source:
        source=source.replace('</head>','<meta name="robots" content="noindex,nofollow"></head>',1)
    source=re.sub(r'<link\s+rel="canonical"[^>]*>',
        '<link rel="canonical" href="https://hank.jockeyvc.com/volts-sandbox/">',source,count=1)
    banner='<aside role="note" style="padding:12px;background:#fff1b8;color:#241b00;text-align:center;font-weight:700">SYNTHETIC SANDBOX · STRIPE TEST PAYMENTS ONLY · NO VEHICLE FOR SALE</aside>'
    source,count=re.subn(r'(<body\b[^>]*>)',lambda m:m.group(1)+banner,source,count=1)
    if count!=1:raise ValueError('Sandbox frontend body is missing')
    index.write_text(source)


def replace_public_runtime(new,stage):
    for directory in ('app','tools','web','media',*PAGE_DIRS):
        target=new/directory
        if target.exists():shutil.rmtree(target)
    for path in new.iterdir():
        if path.is_file() and (path.name in ROOT_FILES or re.fullmatch(r'google[0-9a-z]+\.html',path.name)):
            path.unlink()
    for path in stage.rglob('*'):
        if not path.is_file() or path.name==META:continue
        destination=new/path.relative_to(stage);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,destination)


def check_no_approved_production_sellers(db):
    with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as conn:
        rows=conn.execute('SELECT profile FROM dealers').fetchall()
    if any(json.loads(row[0]).get('verified') for row in rows):
        raise ValueError('Production has an approved seller; this inactive-only installer cannot proceed')


def preserving_inventory(private,fixture,module):
    value=json.loads(json.dumps(private))
    if any(row.get('vin')==FIXTURE_VIN for row in value['items']):
        raise ValueError('Reviewed inventory contains a sandbox fixture')
    value['items'].append(fixture)
    if 'count' in value.get('meta',{}):value['meta']['count']=len(value['items'])
    if 'reservable_count' in value.get('meta',{}):
        value['meta']['reservable_count']=sum(row.get('reservable') is True for row in value['items'])
    public=module.public_catalog(value)
    for row in public['items']:row.pop('photos',None)
    return value,public


def verify_http(role,sha):
    port=18401 if role=='production' else 18400
    base=f'http://127.0.0.1:{port}'
    if read_json(base+'/healthz')!={'ok':True}:raise ValueError('Runtime health check failed')
    config=read_json(base+'/api/config')
    proof=read_json(base+('/deployment-proof' if role=='production' else '/sandbox-proof'))
    if proof.get('artifact_verification')!='match' or proof.get('backend_sha')!=sha or proof.get('catalog_sha')!=sha:
        raise ValueError('Runtime release proof does not match the reviewed SHA')
    if config.get('deposit_capture_method')!='manual':raise ValueError('New checkout is not a manual authorization')
    if role=='production':
        if any(config.get(key) for key in ('payments_enabled','ach_enabled','balance_checkout_enabled','authorization_writes_verified','sandbox_mode')):
            raise ValueError('Production payment gates changed')
    elif not config.get('sandbox_mode') or not config.get('test_mode'):
        raise ValueError('Sandbox TEST isolation failed')
    return {'health':True,'proof_match':True,'production_payments_disabled':not config.get('payments_enabled') if role=='production' else None,
            'sandbox_test_only':bool(config.get('sandbox_mode') and config.get('test_mode')) if role=='sandbox' else None}


def install(args):
    role=args.role;name='volts-api' if role=='production' else 'volts-sandbox'
    base=Path('/opt')/name;link=base/'current';old=link.resolve(strict=True)
    if str(old)!=args.expected_current:raise ValueError('Current release changed after review')
    if old.parent!=base/'releases' or not link.is_symlink():raise ValueError('Unexpected release layout')
    reject_links(old)
    ep=Path('/etc')/(name+'.env');original_env=ep.read_bytes();env=parse_env(original_env)
    guard_environment(env,role)
    entry='production_entry.py' if role=='production' else 'sandbox_entry.py'
    db=Path('/var/lib')/name/'orders.db'
    if env.get('ORDERS_DB')!=str(db):raise ValueError('Unexpected order database location')
    if role=='production':check_no_approved_production_sellers(db)
    source=Path(env['SOURCING_JSON']);source_sha=digest(source)
    old_entry=(old/entry).read_text();entry_result=old_entry
    if role=='production':
        if not args.stock_wrapper_adapter:raise ValueError('Review and explicitly select the stock-ID wrapper adapter')
        entry_result=adapt(old_entry)
    fixture=fixture_from(old,env) if role=='sandbox' else None
    with tempfile.TemporaryDirectory(prefix='volts-release-check-') as temp:
        stage=Path(temp);meta=unpack_bundle(args.bundle,stage,args.sha)
        if digest(args.private_inventory)!=meta['private_inventory_sha256']:
            raise ValueError('Private inventory upload does not match the reviewed bundle')
        private=private_matches(stage,args.private_inventory)
        if (stage/'requirements.txt').read_bytes()!=(old/'requirements.txt').read_bytes():
            raise ValueError('Dependency changes need a separate reviewed installation plan')
        target_env=inventory_env(original_env,base/'current/.data/transaction_inventory.json')
        plan={'role':role,'revision':args.sha,'runtime_files':len(meta['files']),
              'private_inventory_count':len(private['items']),'only_environment_change':'INVENTORY_JSON',
              'provider_calls':False,'activation_changes':False,'executed':False}
        if not args.execute:print(json.dumps(plan));return
        if os.geteuid()!=0:raise ValueError('Execution requires sudo; preflight remains read-only')
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        new=base/'releases'/(args.sha[:12]+'-purchase-flow-'+stamp)
        backup=Path('/var/backups/volts')/('purchase-flow-'+role+'-'+stamp)
        if new.exists() or backup.exists():raise ValueError('Release or backup destination already exists')
        backup.mkdir(parents=True,mode=0o700);backup.chmod(0o700)
        shutil.copy2(ep,backup/'environment.env');(backup/'environment.env').chmod(0o600)
        for filename in (entry,'runtime_proof.py','.deployment-manifest.json'):
            shutil.copy2(old/filename,backup/filename);(backup/filename).chmod(0o600)
        preserved={}
        for source_path in (Path('/etc/systemd/system')/(name+'.service'),
                Path('/etc/systemd/system/volts-order-matcher.service'),
                Path('/etc/systemd/system/volts-order-matcher.timer'),
                Path('/etc/systemd/system/volts-sandbox-refunds.service'),
                Path('/etc/systemd/system/volts-sandbox-refunds.timer'),
                Path('/etc/volts-order-matcher.env'),
                Path('/opt/volts-sandbox/refund_worker.py')):
            if source_path.is_file():
                preserved[str(source_path)]=digest(source_path)
                destination=backup/'preserved'/str(source_path).lstrip('/')
                destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                shutil.copy2(source_path,destination);destination.chmod(0o600)
        previous_manifest=json.loads((old/'.deployment-manifest.json').read_text())
        new.mkdir(mode=0o755);run('cp','-a','--',str(old)+'/.',str(new))
        private_history={path.relative_to(old).as_posix():digest(path)
            for path in (old/'.data').rglob('*') if path.is_file()
            and path.relative_to(old).as_posix()!='.data/transaction_inventory.json'}
        private_history=refresh_private_history(old,new,private_history)
        replace_public_runtime(new,stage)
        data=new/'.data';data.mkdir(mode=0o700,exist_ok=True)
        account=pwd.getpwnam('benjijmac');os.chown(data,account.pw_uid,account.pw_gid);data.chmod(0o700)
        private_target=data/'transaction_inventory.json'
        if role=='sandbox':
            module=catalog_module(new);private,public=preserving_inventory(private,fixture,module)
            safe_json(private_target,private);safe_json(new/'inventory.json',public,0o644)
            shutil.copy2(old/'media/sandbox.svg',new/'media/sandbox.svg')
            if fixture.get('photos'):
                stock=module.stock_id_for(FIXTURE_VIN);shard=new/'media'/(module.media_shard(stock)+'.json')
                galleries=json.loads(shard.read_text()) if shard.exists() else {}
                galleries[stock]=[module.public_photo(FIXTURE_VIN,p) for p in fixture['photos']]
                safe_json(shard,galleries,0o644)
            sandbox_frontend(new/'index.html')
        else:shutil.copyfile(args.private_inventory,private_target)
        private_target.chmod(0o600);os.chown(private_target,account.pw_uid,account.pw_gid)
        (new/entry).write_text(entry_result);(new/entry).chmod(0o644)
        context={**previous_manifest.get('public_context',{}),
            'manual_authorization_release':'implemented_not_live_enabled',
            'stock_identity_projection':True,'frontend_preserved':False}
        if role=='sandbox':
            context.pop('fixture_vin',None)
            context.update(sandbox=True,stripe_mode='test',synthetic_fixture_present=True,
                           catalog_overlay='preserved_original_synthetic_test_vehicle')
        else:context.update(charges_disabled=True,charges_enabled=False,mode='requests_only',synthetic_seller=False)
        install_proof(new,args.sha,context)
        reject_links(new);private_matches(new,private_target,allow_fixture=role=='sandbox')
        # Compile without importing the app or contacting a payment provider.
        run('/opt/volts-sandbox/venv/bin/python','-m','compileall','-q',str(new/'app'),str(new/'tools'),str(new/entry))
        if ep.read_bytes()!=original_env or digest(source)!=source_sha or link.resolve()!=old:
            raise ValueError('Runtime changed while staging; do not activate this release')
        private_history=refresh_private_history(old,new,private_history)
        service=name+'.service';run('systemctl','stop',service)
        try:
            with sqlite3.connect(db) as src,sqlite3.connect(backup/'orders.db') as dst:src.backup(dst)
            (backup/'orders.db').chmod(0o600)
            metadata={'role':role,'revision':args.sha,'previous_target':str(old),'new_target':str(new),
                'environment_sha256_before':hashlib.sha256(original_env).hexdigest(),
                'environment_sha256_after':hashlib.sha256(target_env).hexdigest(),
                'entry_sha256_before':hashlib.sha256(old_entry.encode()).hexdigest(),
                'entry_sha256_after':digest(new/entry),'source_sha256':source_sha,
                'database_path':str(db),'database_restore_automatic':False,
                'private_inventory_sha256':digest(private_target),'preserved_runtime_files':preserved,
                'preserved_private_history_at_cutover':private_history}
            safe_json(backup/'rollback.json',metadata)
            temporary_env=ep.with_suffix('.env.purchase-next');temporary_env.write_bytes(target_env);temporary_env.chmod(0o600)
            os.replace(temporary_env,ep)
            next_link=base/'current.purchase-next';next_link.symlink_to(new);os.replace(next_link,link)
        finally:run('systemctl','start',service)
        # A failed check leaves explicit backup metadata; do not silently restore financial history.
        import time
        last=None
        for attempt in range(15):
            try:checks=verify_http(role,args.sha);break
            except (OSError,ValueError) as exc:
                last=exc
                if attempt==14:raise ValueError('Health checks failed; use the reviewed rollback command') from exc
                time.sleep(4)
        if digest(Path(env['SOURCING_JSON']))!=source_sha:raise ValueError('Private sourcing changed')
        if parse_env(ep.read_bytes())!=parse_env(target_env):raise ValueError('Environment changed during restart')
        if any(digest(path)!=value for path,value in preserved.items()):
            raise ValueError('An unrelated worker or systemd file changed')
        print(json.dumps({**plan,'executed':True,'backup':str(backup),'release':str(new),'checks':checks}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--role',choices=('production','sandbox'),required=True)
    parser.add_argument('--sha',required=True);parser.add_argument('--bundle',required=True,type=Path)
    parser.add_argument('--private-inventory',required=True,type=Path)
    parser.add_argument('--expected-current',required=True)
    parser.add_argument('--stock-wrapper-adapter',action='store_true');parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();install(args)
