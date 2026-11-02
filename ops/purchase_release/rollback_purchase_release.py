"""Restore the previous release and env. Never overwrite financial or tracking history."""
from pathlib import Path
import argparse
import hashlib
import json
import os
from purchase_release_common import digest
from install_purchase_release import run


def rollback(backup,execute=False):
    backup=Path(backup).resolve()
    if backup.parent!=Path('/var/backups/volts'):raise ValueError('Unexpected backup location')
    meta=json.loads((backup/'rollback.json').read_text());role=meta['role']
    if role not in ('production','sandbox'):raise ValueError('Unexpected deployment role')
    name='volts-api' if role=='production' else 'volts-sandbox';base=Path('/opt')/name
    old=Path(meta['previous_target']);new=Path(meta['new_target']);link=base/'current'
    if old.parent!=base/'releases' or new.parent!=base/'releases' or not old.is_dir():
        raise ValueError('Unexpected rollback target')
    if link.resolve()!=new:raise ValueError('A later release is already active; do not overwrite it')
    env=Path('/etc')/(name+'.env');restore=backup/'environment.env'
    if digest(env)!=meta['environment_sha256_after'] or digest(restore)!=meta['environment_sha256_before']:
        raise ValueError('Environment changed after deployment; review before rolling back')
    if not execute:
        print(json.dumps({'role':role,'rollback_ready':True,'database_restore':False,'executed':False}));return
    if os.geteuid()!=0:raise ValueError('Execution requires sudo')
    run('systemctl','stop',name+'.service')
    try:
        temporary=env.with_suffix('.env.rollback-next');temporary.write_bytes(restore.read_bytes());temporary.chmod(0o600)
        os.replace(temporary,env)
        next_link=base/'current.rollback-next';next_link.symlink_to(old);os.replace(next_link,link)
    finally:run('systemctl','start',name+'.service')
    print(json.dumps({'role':role,'previous_release_restored':True,'database_restore':False,'executed':True}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--backup',required=True,type=Path)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args();rollback(args.backup,args.execute)
