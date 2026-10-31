"""Extract VIN-bound vehicle photography. Never turn stock placeholders into vehicle evidence."""
import json,re
from urllib.parse import urlsplit


def photo_url(value):
    if not isinstance(value,str):return ''
    try:p=urlsplit(value)
    except ValueError:return ''
    if p.scheme!='https' or not p.hostname or p.username or p.password:return ''
    if any(x in p.path.lower() for x in ('_default.','stockimages/','generic-features/','placeholder','no-image')):return ''
    return value


def walk(value):
    if isinstance(value,dict):
        yield value
        for x in value.values():yield from walk(x)
    elif isinstance(value,list):
        for x in value:yield from walk(x)


def extract_gallery(html,vin):
    """Supports JSON-LD and Next.js Flight data, binding photos to the requested VIN."""
    objects=[]
    for attrs,body in re.findall(r'<script([^>]*)>(.*?)</script>',html,re.S|re.I):
        if 'application/ld+json' in attrs or 'application/json' in attrs:
            try:objects.append(json.loads(body))
            except (ValueError,TypeError):pass
        if 'self.__next_f.push(' in body:
            try:chunk=json.loads(body.split('self.__next_f.push(',1)[1].rsplit(')',1)[0])
            except (ValueError,IndexError):continue
            if len(chunk)>1 and isinstance(chunk[1],str):
                for line in chunk[1].splitlines():
                    try:objects.append(json.loads(line.partition(':')[2]))
                    except ValueError:pass
    photos=[];seen=set()
    def add(url,title,category):
        url=photo_url(url)
        if url and url not in seen:
            seen.add(url);photos.append({'url':url,'title':title,'category':category})
    for root in objects:
        for record in walk(root):
            if (record.get('vin') or record.get('vehicleIdentificationNumber'))!=vin:continue
            media=record.get('vexVdpImageData')
            if isinstance(media,dict):
                add((media.get('heroes') or {}).get('hero'),'Exterior overview','exterior')
                spins=media.get('spins') or []
                if spins:
                    for frame in spins[0].get('images',[]):add(frame.get('imageUrl'),'Exterior angle','exterior')
                for x in media.get('features',[]):add(x.get('imageUrl'),x.get('title') or 'Vehicle detail',x.get('location') or 'details')
                for x in media.get('imperfections',[]):add(x.get('imageUrl'),(x.get('zoneDescription','')+' — '+x.get('title','Condition detail')).strip(' —'),'condition')
            image=record.get('image') or record.get('images') or record.get('photos')
            if isinstance(image,str):add(image,'Vehicle photo','photos')
            elif isinstance(image,list):
                for x in image:
                    if isinstance(x,str):add(x,'Vehicle photo','photos')
                    elif isinstance(x,dict):add(x.get('contentUrl') or x.get('imageUrl') or x.get('url'),x.get('caption') or 'Vehicle photo','photos')
    return photos
