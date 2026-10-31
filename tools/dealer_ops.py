#!/usr/bin/env python3
"""Authenticated dealership work queue. Never place secrets in command arguments."""
import argparse, json, os, urllib.request, urllib.error

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['orders','outbox','quote','transition','refund','ack','privacy-purge'])
    p.add_argument('--id');p.add_argument('--file');p.add_argument('--origin',default=os.getenv('PUBLIC_ORIGIN','http://127.0.0.1:8000'))
    args=p.parse_args();token=os.getenv('ADMIN_TOKEN','')
    if len(token)<32:p.error('Set ADMIN_TOKEN in the environment')
    if args.action in ('orders','outbox'):path=args.action;data=None
    elif args.action=='ack':path=f'outbox/{args.id}/ack';data=b'{}'
    elif args.action=='privacy-purge':path='privacy/purge';data=b'{}'
    else:
        if not args.id:p.error('--id is required')
        path=f'orders/{args.id}/{args.action}'
        data=open(args.file,'rb').read() if args.file else b'{}'
    req=urllib.request.Request(args.origin.rstrip('/')+'/api/admin/'+path,data=data,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:print(json.dumps(json.load(r),indent=2))
    except urllib.error.HTTPError as e:raise SystemExit(e.read().decode())
if __name__=='__main__':main()
