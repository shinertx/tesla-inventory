"""Bounded, cached photo lookup against public source pages. No bulk requests."""
import json,time
from urllib.parse import urlsplit
from curl_cffi import requests
from tools.media import extract_gallery,photo_url

class VehicleMedia:
    def __init__(self,store,sourcing_path):
        self.store=store;self.path=sourcing_path;self.rows={};self.mtime=None

    def source(self,vin):
        if self.path.is_file() and self.path.stat().st_mtime!=self.mtime:
            self.rows={x['vin']:x for x in json.loads(self.path.read_text()).get('items',[])};self.mtime=self.path.stat().st_mtime
        return self.rows.get(vin,{})

    def gallery(self,vin,primary=''):
        now=int(time.time())
        with self.store.connect() as c:cached=c.execute('SELECT * FROM vehicle_media WHERE vin=?',(vin,)).fetchone()
        if cached and cached['expires_at']>now:return json.loads(cached['payload'])
        row=self.source(vin);photos=[]
        for x in row.get('photos',[]):
            if isinstance(x,dict) and photo_url(x.get('url')):photos.append(x)
        if not photos:
            url=row.get('source_url','');p=urlsplit(url)
            allowed=(p.scheme=='https' and not p.username and not p.password and
                ((p.hostname=='www.carvana.com' and re_path(p.path,r'/vehicle/\d+')) or
                 (p.hostname=='www.truecar.com' and re_path(p.path,r'/used-cars-for-sale/listing/[A-Z0-9]{17}/?'))))
            # CarGurus detail requests are blocked. Keep its known primary photo; do not retry blocked pages.
            if allowed:
                try:
                    response=requests.get(url,impersonate='chrome120',timeout=8,allow_redirects=False)
                    if response.status_code==200:photos=extract_gallery(response.text,vin)
                except Exception:pass
        if not photos:
            for url in [primary,row.get('photo_url','')]:
                if photo_url(url) and not any(x['url']==url for x in photos):photos.append({'url':url,'title':'Vehicle photo','category':'photos'})
        result={'vin':vin,'photos':photos,'count':len(photos)}
        ttl=86400 if len(photos)>1 else 900
        with self.store.transaction() as c:c.execute('INSERT INTO vehicle_media VALUES(?,?,?) ON CONFLICT(vin) DO UPDATE SET payload=excluded.payload,expires_at=excluded.expires_at',(vin,json.dumps(result),now+ttl))
        return result

def re_path(value,pattern):
    import re
    return bool(re.fullmatch(pattern,value))
