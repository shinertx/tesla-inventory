"""Read-only on-host checks. This does not create orders or contact providers."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import pwd
import sqlite3
from purchase_release_common import digest,parse_env,private_matches,reject_links,VIN,FIXTURE_VIN
from install_purchase_release import guard_environment,verify_http,read_json


def verify(role,sha,backup=None):
    name='volts-api' if role=='production' else 'volts-sandbox';base=Path('/opt')/name
    release=(base/'current').resolve(strict=True);reject_links(release)
    raw=(Path('/etc')/(name+'.env')).read_bytes();env=parse_env(raw);guard_environment(env,role)
    if env.get('INVENTORY_JSON')!=str(base/'current/.data/transaction_inventory.json'):
        raise ValueError('Private inventory environment is not the stable current path')
    inventory=release/'.data/transaction_inventory.json';stat=inventory.stat()
    if stat.st_mode&0o777!=0o600 or stat.st_uid!=pwd.getpwnam('benjijmac').pw_uid:
        raise ValueError('Private inventory permissions are incorrect')
    data=private_matches(release,inventory,allow_fixture=role=='sandbox')
    if role=='sandbox' and sum(row.get('vin')==FIXTURE_VIN for row in data['items'])!=1:
        raise ValueError('Sandbox fixture was not preserved exactly once')
    checks=verify_http(role,sha)
    port=18401 if role=='production' else 18400;base_url=f'http://127.0.0.1:{port}'
    public=read_json(base_url+'/inventory.json')
    if VIN.search(json.dumps(public)):raise ValueError('Public inventory exposes a VIN')
    if role=='production':
        search=read_json(base_url+'/api/search?limit=2')
        summary=read_json(base_url+'/api/visits/summary')
        if VIN.search(json.dumps(search)) or VIN.search(json.dumps(summary)):
            raise ValueError('A public wrapper route exposes historical identities')
        if any(not item.get('stock_id') or '?id=' not in item.get('checkout_url','') for item in search.get('items',[])):
            raise ValueError('Search links do not use public stock identities')
    history=None
    if backup:
        backup=Path(backup).resolve();meta=json.loads((backup/'rollback.json').read_text())
        if meta['role']!=role or meta['revision']!=sha or meta['new_target']!=str(release):
            raise ValueError('Backup metadata does not describe this release')
        original=(backup/'environment.env').read_bytes()
        before=parse_env(original);after=parse_env(raw)
        if {k:v for k,v in before.items() if k!='INVENTORY_JSON'}!={k:v for k,v in after.items() if k!='INVENTORY_JSON'}:
            raise ValueError('An unrelated environment setting changed')
        if digest(Path(env['SOURCING_JSON']))!=meta['source_sha256']:
            raise ValueError('Private sourcing data changed')
        if any(digest(path)!=value for path,value in meta.get('preserved_runtime_files',{}).items()):
            raise ValueError('Worker or systemd configuration changed')
        # The same durable DB remains in place. Verify existing order and tracking identities.
        # Mutable states may legitimately change because the existing workers remain active.
        tables=('orders','visitor_events','dealers','order_alerts_sent')
        checked=0
        with sqlite3.connect('file:'+str(backup/'orders.db')+'?mode=ro',uri=True) as old, \
             sqlite3.connect('file:'+str(Path(env['ORDERS_DB']))+'?mode=ro',uri=True) as current:
            names={row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables:
                if table not in names:continue
                column='order_id' if table=='order_alerts_sent' else 'id'
                prior={row[0] for row in old.execute('SELECT '+column+' FROM '+table)}
                actual={row[0] for row in current.execute('SELECT '+column+' FROM '+table)}
                if not prior<=actual:raise ValueError('An existing durable history identity disappeared')
                if table=='order_alerts_sent':
                    old_rows=set(old.execute('SELECT order_id,recipient,sent_at FROM order_alerts_sent'))
                    new_rows=set(current.execute('SELECT order_id,recipient,sent_at FROM order_alerts_sent'))
                    if not old_rows<=new_rows:raise ValueError('An existing alert receipt changed')
                checked+=1
        history={'existing_history_identity_sets_preserved':True,'tables_checked':checked}
    print(json.dumps({'role':role,'revision':sha,'checks':checks,'private_inventory_permissions':True,
                      'private_public_binding':True,'public_identity_projection':True,'history':history}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--role',choices=('production','sandbox'),required=True)
    parser.add_argument('--sha',required=True);parser.add_argument('--backup',type=Path)
    args=parser.parse_args();verify(args.role,args.sha,args.backup)
