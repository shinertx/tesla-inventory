"""Explicit public projection. Supplier commercial data never belongs in customer JSON."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def catalog_exclusions(inventory_path):
    """Read each time so a running API observes new review exclusions."""
    parent = Path(inventory_path).parent
    if parent.name == '.data':
        parent = parent.parent
    path = parent / 'data' / 'exclusions.json'
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}  # Explicit fixture roots need not contain a production exclusion file.
    except (OSError, ValueError) as exc:
        raise ValueError('Catalog review exclusions are unavailable') from exc
    if not isinstance(data, dict) or any(
        not isinstance(vin, str) or not isinstance(reason, str) or not reason.strip()
        for vin, reason in data.items()
    ):
        raise ValueError('Catalog review exclusions are invalid')
    return data


STOCK_ID_PATTERN = re.compile(r'^VV-[0-9A-F]{12}$')
VIN_PATTERN = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')


def stock_id_for(vin):
    """Stable public identity. Never use a VIN substring as the customer stock ID."""
    if not isinstance(vin, str) or not VIN_PATTERN.fullmatch(vin):
        raise ValueError('A complete canonical VIN is required')
    return 'VV-' + hashlib.sha256(('volts-and-vins:' + vin).encode()).hexdigest()[:12].upper()


def media_shard(stock_id):
    if not isinstance(stock_id, str) or not STOCK_ID_PATTERN.fullmatch(stock_id):
        raise ValueError('A valid public stock ID is required')
    return format(int(stock_id[-3:], 16) % 128, '02x')


def masked_vin_for(vin):
    if not isinstance(vin, str) or not VIN_PATTERN.fullmatch(vin):
        raise ValueError('A complete canonical VIN is required')
    return vin[:8] + '\u2022' * 9


def public_photo_url(vin, url):
    """Hide third-party dealer/marketplace photo URLs while preserving private source identity."""
    if not isinstance(url, str) or not url:
        return url
    if url.startswith('https://api.voltsandvins.com/api/vehicles/'):
        return url
    decoded=url
    for _ in range(3):
        updated=unquote(decoded)
        if updated==decoded:break
        decoded=updated
    host=(urlsplit(url).hostname or '').lower().rstrip('.')
    external_source=bool(host and host!='example.test' and not host.endswith(('.example.test','voltsandvins.com')))
    if isinstance(vin,str) and (vin.lower() in decoded.lower() or external_source):
        image_id=hashlib.sha256(url.encode()).hexdigest()[:20]
        return f'https://api.voltsandvins.com/api/vehicles/{stock_id_for(vin)}/images/{image_id}'
    return url


def public_photo(vin, photo):
    """Publish only safe photo fields, with source identities removed from labels."""
    if not isinstance(photo,dict):photo={'url':photo}
    def label(key,fallback):
        value=photo.get(key)
        if not isinstance(value,str):return fallback
        return re.sub(re.escape(vin),masked_vin_for(vin),value,flags=re.I)
    return {'url':public_photo_url(vin,photo.get('url','')),
            'title':label('title','Vehicle photo'),'category':label('category','photos')}


_RISK_FLAGS = {
    'riskflag': 'reported_condition_risk', 'salvage': 'salvage', 'issalvage': 'salvage',
    'salvagetitle': 'salvage', 'hassalvagetitle': 'salvage', 'salvagehistory': 'salvage',
    'rebuilt': 'rebuilt', 'isrebuilt': 'rebuilt', 'rebuilttitle': 'rebuilt',
    'reconstructed': 'rebuilt', 'isreconstructed': 'rebuilt',
    'lemon': 'lemon', 'islemon': 'lemon', 'lemontitle': 'lemon',
    'manufacturerbuyback': 'lemon', 'ismanufacturerbuyback': 'lemon', 'buyback': 'lemon',
    'flood': 'flood', 'isflood': 'flood', 'flooddamage': 'flood', 'hasflooddamage': 'flood',
    'waterdamage': 'flood', 'iswaterdamaged': 'flood',
    'framedamage': 'structural_damage', 'hasframedamage': 'structural_damage',
    'structuraldamage': 'structural_damage', 'isstructurallydamaged': 'structural_damage',
    'salvagesource': 'salvage', 'hasthefthistory': 'theft', 'isthefthistory': 'theft',
}
_TITLE_FIELDS = {'titlestatus', 'titletype', 'titlebrand', 'titlebrands', 'brandedtitle',
                 'vehicletitlestatus', 'vehicletitle', 'sourcetitlestatus'}
_HISTORY_FIELDS = {'history', 'vehiclehistory', 'titlehistory', 'conditionhistory'}
_RISK_WORDS = re.compile(r'\b(salvage|rebuilt|reconstructed|lemon|manufacturer[ -]?buyback|flood|water[ -]?damage|frame[ -]?damage|structural[ -]?damage)\b', re.I)
_FALSE_VALUES = {'', '0', 'false', 'no', 'none', 'null', 'unknown', 'unverified',
                 'not reported', 'not_reported', 'not applicable', 'n/a', 'clean', 'clear'}
_TITLE_BRAND_CODES={'flooddamage':{'flood'},'manufacturerbuyback':{'lemon'},
                    'lemonlawbuyback':{'lemon'},'salvagerebuilt':{'salvage','rebuilt'}}


def _key(value):
    return re.sub('[^a-z0-9]', '', str(value).lower())


def title_risk_reasons(record):
    """Find explicit branded-title evidence, without treating unknown history as clean."""
    reasons = set()

    def flagged(value):
        if value is None or value is False:
            return False
        if isinstance(value, str):
            return value.strip().lower() not in _FALSE_VALUES
        return bool(value)

    def brands(value):
        if isinstance(value, (list, tuple)):
            for entry in value:
                brands(entry)
        elif isinstance(value, dict):
            for key, entry in value.items():
                if _key(key) in {'brand', 'name', 'value', 'label', 'status', 'description'}:
                    brands(entry)
            walk(value)
        elif isinstance(value, str):
            reasons.update(_TITLE_BRAND_CODES.get(_key(value),set()))
            # Providers also concatenate known title brands or return camelCase enums.
            text=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',value)
            text = re.sub(r'[_/]+', ' ', text)
            for match in _RISK_WORDS.finditer(text):
                prefix = text[max(0, match.start() - 15):match.start()].lower()
                if re.search(r'\b(?:no|not|without)\s+(?:a\s+)?$', prefix):
                    continue
                brand = match.group().lower().replace('-', ' ')
                if brand in ('reconstructed',):
                    brand = 'rebuilt'
                elif 'buyback' in brand:
                    brand = 'lemon'
                elif 'water' in brand:
                    brand = 'flood'
                elif 'frame' in brand or 'structural' in brand:
                    brand = 'structural_damage'
                reasons.add(brand)

    def walk(value):
        if not isinstance(value, dict):
            return
        for key, entry in value.items():
            key = _key(key)
            if key in _RISK_FLAGS and flagged(entry):
                reasons.add(_RISK_FLAGS[key])
            elif key in _TITLE_FIELDS:
                brands(entry)
            elif key in _HISTORY_FIELDS:
                if isinstance(entry, dict):
                    walk(entry)
                elif isinstance(entry, (list, tuple)):
                    for item in entry:
                        walk(item) if isinstance(item, dict) else brands(item)
                else:
                    brands(entry)
            elif key == 'title' and isinstance(entry, str) and (
                len(entry.split()) <= 3 or re.search(r'\btitle\b', entry, re.I)
            ):
                brands(entry)

    walk(record)
    return sorted(reasons)


PUBLIC_FIELDS={'curated','drivetrain','drivetrain_basis','trim_family','factory','factory_basis','location_center','pricing_basis','photo_count','photos','stock_id','stock_number','masked_vin','model','year','trim','mileage','display_price','pricing_status',
 'city','state','photo','fulfillment','source_observed_at','benchmark_date','expires_at','reservable','availability','title_status',
 'hardware','inspection_status','reference_price','reference_sample','savings_amount'}
PUBLIC_META={'media_version','built_at','count','reservable_count','mode','partner_onboarding_status','availability_note'}

def public_catalog(data):
    items=[]
    for row in data.get('items',[]):
        if title_risk_reasons(row):
            continue
        item={k:v for k,v in row.items() if k in PUBLIC_FIELDS}
        vin=row.get('vin')
        if vin:
            stock=stock_id_for(vin)
            item.update(stock_id=stock,stock_number=stock,masked_vin=masked_vin_for(vin))
            if 'photo' in item:item['photo']=public_photo_url(vin,item['photo'])
            if 'photos' in item:
                item['photos']=[public_photo(vin,photo) for photo in item['photos']]
            for key,value in list(item.items()):
                if isinstance(value,str) and not value.startswith(('https://','http://')):
                    item[key]=re.sub(re.escape(vin),item['masked_vin'],value,flags=re.I)
        elif not STOCK_ID_PATTERN.fullmatch(str(item.get('stock_id',''))):
            raise ValueError('Public catalog row has no valid vehicle identity')
        else:
            item['stock_number']=item['stock_id']
        item['title_status']='clean_verified' if row.get('reservable') is True and row.get('title_status')=='clean_verified' else 'unverified'
        items.append(item)
    meta={k:v for k,v in data.get('meta',{}).items() if k in PUBLIC_META}
    if 'count' in meta:meta['count']=len(items)
    if 'reservable_count' in meta:meta['reservable_count']=sum(x.get('reservable') is True for x in items)
    return {'meta':meta,'items':items}
