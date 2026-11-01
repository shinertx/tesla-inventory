"""Publish reviewed photo changes without recomputing vehicle prices or snapshot dates."""
import argparse,copy,hashlib,json
from pathlib import Path
from tools.inventory import valid_vin
from tools.media import normalize_photos

PHOTO_FIELDS=frozenset(('photo','photo_count','photos'))

def nonphoto_catalog(catalog):
    return {
        'meta':{k:v for k,v in catalog.get('meta',{}).items() if k!='media_version'},
        'items':[{k:v for k,v in item.items() if k not in PHOTO_FIELDS} for item in catalog['items']],
    }

def project_photos(catalog, shards, delta):
    known={item['vin'] for item in catalog['items']}
    if any(not valid_vin(vin) or vin not in known for vin in delta):
        raise ValueError('Photo delta contains an invalid or unpublished VIN')
    result=copy.deepcopy(catalog)
    projected=copy.deepcopy(shards)
    changed=[]
    for item in result['items']:
        vin=item['vin'];shard=format(int(vin[-3:])%128,'02x')
        published=shards.get(shard,{}).get(vin)
        if int(item.get('photo_count',0))>1 and not published:
            raise ValueError('Existing multi-photo gallery is missing; refusing to replace it')
        baseline=published if published is not None else item.get('photos') or [item.get('photo')]
        photos=normalize_photos(list(baseline)+delta.get(vin,[]))
        before=(item.get('photo'),item.get('photo_count'))
        item['photo']=photos[0]['url'] if photos else ''
        item['photo_count']=len(photos)
        if 'photos' in item:item['photos']=photos
        if before!=(item['photo'],item['photo_count']):changed.append(vin)
        if photos:projected.setdefault(shard,{})[vin]=photos
        elif shard in projected:projected[shard].pop(vin,None)
    projected={key:photos for key,photos in projected.items() if photos}
    version=hashlib.sha256(json.dumps(projected,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12]
    result.setdefault('meta',{})['media_version']=version
    if nonphoto_catalog(result)!=nonphoto_catalog(catalog):
        raise ValueError('Non-photo catalog fields changed; publication refused')
    return result,projected,changed

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--delta',type=Path)
    args=parser.parse_args()
    root=args.root;path=root/'inventory.json';media=root/'media'
    before=json.loads(path.read_text())
    shards={p.stem:json.loads(p.read_text()) for p in media.glob('*.json')}
    delta=json.loads((args.delta or root/'data/vehicle_photo_recovery_delta.json').read_text())
    after,projected,changed=project_photos(before,shards,delta)
    # No full inventory rebuild: preserve every price, availability flag, and timestamp.
    for key,photos in projected.items():
        destination=media/(key+'.json')
        encoded=json.dumps(photos,sort_keys=True,separators=(',',':'))
        if not destination.exists() or destination.read_text()!=encoded:destination.write_text(encoded)
    for old in media.glob('*.json'):
        if old.stem not in projected:old.unlink()
    path.write_text(json.dumps(after,separators=(',',':')))
    print(json.dumps({'changed_photo_vins':len(changed),'media_version':after['meta']['media_version'],
        'none':sum(not x['photo'] for x in after['items']),
        'single':sum(x['photo_count']==1 for x in after['items']),
        'multi':sum(x['photo_count']>1 for x in after['items']),
        'nonphoto_fields_preserved':nonphoto_catalog(before)==nonphoto_catalog(after)}))

if __name__=='__main__':main()
