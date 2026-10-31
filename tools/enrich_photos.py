"""Collect every exposed VIN-bound image. Run network backfills on the approved remote worker.

403/429 stops that source host. No retries, challenge bypass, guessed images, or URL expansion.
A dealer photo feed can fill blocked sources using --feed JSON keyed by VIN.
"""
import argparse,json,re,time
from pathlib import Path
from urllib.parse import urlsplit
from curl_cffi import requests
from tools.media import extract_gallery,normalize_photos


def collect(source,output,report,feed=None,pause=.5):
    rows=json.loads(Path(source).read_text())['items']
    output=Path(output);report=Path(report)
    galleries=json.loads(output.read_text()) if output.exists() else {}
    supplied=json.loads(Path(feed).read_text()) if feed else {}
    blocked=set();stats={'total':len(rows),'multiple':0,'single':0,'missing':0,'blocked_hosts':[],'http':{},'fetched':0}
    for index,row in enumerate(rows):
        vin=row['vin'];photos=normalize_photos(supplied.get(vin,[])+galleries.get(vin,[])+row.get('photos',[]))
        url=row.get('source_url','');p=urlsplit(url)
        allowed=p.scheme=='https' and not p.username and not p.password and (
            p.hostname=='www.carvana.com' and re.fullmatch(r'/vehicle/\d+',p.path) or
            p.hostname=='www.truecar.com' and re.fullmatch(r'/used-cars-for-sale/listing/[A-Z0-9]{17}/?',p.path) or
            p.hostname=='www.autolist.com' and re.fullmatch(r'/api/vehicles/[A-Z0-9]{17}',p.path))
        if len(photos)<2 and allowed and p.hostname not in blocked:
            try:
                r=requests.get(url,impersonate='chrome120',timeout=12,allow_redirects=False)
                stats['fetched']+=1;key=str(r.status_code);stats['http'][key]=stats['http'].get(key,0)+1
                if r.status_code in (403,429):blocked.add(p.hostname)
                if r.status_code==200:photos=normalize_photos(extract_gallery(r.text,vin)+photos)
            except Exception:stats['http']['network_error']=stats['http'].get('network_error',0)+1
            time.sleep(pause)
        if not photos:photos=normalize_photos([row.get('photo_url','')])
        if photos:galleries[vin]=photos
        stats['multiple' if len(photos)>1 else 'single' if photos else 'missing']+=1
        if index%2500==0:
            output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(galleries,separators=(',',':')))
            print(json.dumps({'processed':index+1,**stats}),flush=True)
    stats['blocked_hosts']=sorted(blocked)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(galleries,separators=(',',':')))
    report.write_text(json.dumps(stats,indent=2));print(json.dumps(stats),flush=True)
    return stats

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--feed',type=Path);args=p.parse_args();collect(args.source,args.output,args.report,args.feed)
