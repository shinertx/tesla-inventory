#!/usr/bin/env python3
"""Bounded source collection. Fail visibly; never claim complete national coverage."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, quote
import argparse, json, os, re, sys
from curl_cffi import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inventory import ingest, export
from tools.media import photo_url
from app.catalog import title_risk_reasons
LD_RE=re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',re.S|re.I)

class SourceError(RuntimeError):pass

def numeric(value):
    if isinstance(value,dict):value=value.get('value')
    if value is None:return None
    try:return int(float(str(value).replace(',','')))
    except (ValueError,TypeError):return None

def normalized(vin,model,year,trim,price,mileage,dealer,city,state,photo,url,risk=False,title_evidence=None):
    model=str(model or '').replace('Tesla ','').strip()
    if model not in ('Model 3','Model Y','Model S','Model X','Cybertruck'):return None
    if 'tesla.com' in str(url or '').lower():return None
    seller_kind=str((title_evidence or {}).get('sellerType') or (title_evidence or {}).get('seller_type') or '').strip().lower()
    if seller_kind in ('private','private_party','fsbo','owner','individual'):return None
    if re.search(r'\b(private seller|private party|for sale by owner|fsbo|by owner)\b',str(dealer or ''),re.I):return None
    price=numeric(price);mileage=numeric(mileage);year=numeric(year)
    if price is None or mileage is None or year is None:return None
    values=photo if isinstance(photo,list) else [photo]
    photos=[]
    for value in values:
        media_url=photo_url(value if isinstance(value,str) else (value.get('contentUrl') or value.get('url')) if isinstance(value,dict) else '')
        if media_url:photos.append({'url':media_url,'title':'Vehicle photo','category':'photos'})
    reasons=title_risk_reasons(title_evidence or {})
    return dict(vin=vin,model=model,year=year,dealer_trim=trim or 'Trim unverified',asking_price=price,mileage=mileage,
        dealer_name=dealer or 'Source dealer unverified',city=city or '',state=state or 'US',
        photo_url=photos[0]['url'] if photos else '',photos=photos,source_url=url if isinstance(url,str) else '',
        risk_flag=bool(risk or reasons),title_risk_reasons=reasons)

def parse_source(source,response,model=None,year=None):
    rows=[]
    if source=='autolist':
        data=response.json()
        items=data.get('records') if isinstance(data,dict) and isinstance(data.get('records'),list) else data.get('search_results') if isinstance(data,dict) else None
        if not isinstance(items,list):raise SourceError('Autolist response shape changed')
        for x in items:
            vin=x.get('vin')
            photos=x.get('photo_urls') if isinstance(x.get('photo_urls'),list) and x.get('photo_urls') else x.get('primary_photo_url')
            link=x.get('url') or x.get('listing_url') or (f'/api/vehicles/{vin}' if vin else '')
            rows.append(normalized(vin,x.get('model') or x.get('model_name'),x.get('year'),x.get('trim'),x.get('price_unformatted') if x.get('price_unformatted') is not None else x.get('price'),x.get('mileage_unformatted') if x.get('mileage_unformatted') is not None else x.get('mileage'),x.get('dealer_name'),x.get('city'),x.get('state'),photos,urljoin('https://www.autolist.com',link),title_evidence=x))
    elif source=='cargurus':
        data=response.json()
        if data is None:return []
        if not isinstance(data,list):raise SourceError('CarGurus response shape changed')
        for x in data:
            city=x.get('sellerCity') or '';state=x.get('sellerRegion')
            m_val=x.get('modelName') or x.get('model') or (None if model=='All' else model)
            rows.append(normalized(x.get('vin'),m_val,x.get('carYear') or year,x.get('trimName'),x.get('price'),x.get('mileage'),x.get('serviceProviderName'),city.split(',')[0],state,(x.get('originalPictureData') or {}).get('url'),f"https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action#listing={x['id']}" if x.get('id') else '',title_evidence=x))
    elif source=='carmax':
        items=None
        try:
            data=response.json()
            if isinstance(data,dict) and isinstance(data.get('items'),list):items=data['items']
        except Exception:
            data=None
        if items is None:
            m_cars=re.search(r'const\s+cars\s*=\s*(\[.*?\]);\s*\r?\n',response.text,re.S)
            if m_cars:
                try:items=json.loads(m_cars.group(1))
                except json.JSONDecodeError:items=None
        if not isinstance(items,list):raise SourceError('CarMax response shape changed')
        for x in items:
            if str(x.get('make') or '').strip().lower()!='tesla':continue
            if x.get('isSaleable') is False or x.get('isReserved') is True:continue
            stock_no=x.get('stockNumber')
            m_val=x.get('model') or (None if model=='All' else model)
            trim_val=' '.join(p for p in (x.get('series'),x.get('trim')) if p).strip() or x.get('trim') or x.get('series')
            photo=x.get('heroImageUrl') or (f'https://img2.carmax.com/assets/{stock_no}/hero.jpg?width=800' if stock_no else '')
            link=f'https://www.carmax.com/car/{stock_no}' if stock_no else ''
            dealer_label=f"CarMax {x.get('storeName') or ''}".strip()
            rows.append(normalized(x.get('vin'),m_val,x.get('year') or year,trim_val,x.get('basePrice'),x.get('mileage'),dealer_label,x.get('storeCity'),x.get('stateAbbreviation'),photo,link,title_evidence=x))
    elif source=='marketcheck':
        data=response.json()
        items=data.get('listings') if isinstance(data,dict) else None
        if not isinstance(items,list):raise SourceError('MarketCheck response shape changed')
        for x in items:
            b=x.get('build') or {}
            make_val=str(b.get('make') or x.get('make') or '').strip().lower()
            if make_val!='tesla':continue
            dlr=x.get('dealer') or {}
            media=x.get('media') or {}
            photos=media.get('photo_links') or media.get('photo_url') or x.get('photo_links')
            vdp_url=x.get('vdp_url') or (f"https://www.marketcheck.com/listing/{x['id']}" if x.get('id') else '')
            ev={**x,'seller_type':dlr.get('seller_type') or x.get('seller_type') or x.get('inventory_type') or 'dealer'}
            is_clean=x.get('clean_title')
            if is_clean is False:ev['salvage']=True
            m_val=b.get('model') or x.get('model') or (None if model=='All' else model)
            rows.append(normalized(x.get('vin'),m_val,b.get('year') or x.get('year') or year,b.get('trim') or x.get('trim'),x.get('price'),x.get('miles') if x.get('miles') is not None else x.get('mileage'),dlr.get('name'),dlr.get('city'),dlr.get('state'),photos,vdp_url,risk=(is_clean is False),title_evidence=ev))
    else:
        nd_match=re.search(r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',response.text,re.S|re.I) if source=='truecar' else None
        if nd_match:
            try:apollo=((json.loads(nd_match.group(1)).get('props') or {}).get('pageProps') or {}).get('__APOLLO_STATE__') or {}
            except json.JSONDecodeError:apollo={}
            csls=[v for k,v in apollo.items() if k.startswith('ConsumerSummaryListing:') and isinstance(v,dict)]
            if csls:
                for csl in csls:
                    veh=csl.get('vehicle') or {};det=veh.get('details') or {};style=veh.get('style') or {}
                    dlr_ref=(csl.get('dealership') or {}).get('__ref') or '';dlr=apollo.get(dlr_ref) if dlr_ref else (csl.get('dealership') or {})
                    geo=((dlr.get('location') or {}).get('geolocation') or {}) if isinstance(dlr,dict) else {}
                    cond=csl.get('conditionHistory') or {}
                    if isinstance(cond,dict) and '__ref' in cond:cond=apollo.get(cond['__ref']) or {}
                    is_clean=cond.get('isCleanTitle') if isinstance(cond,dict) else None
                    vin=veh.get('vin') or det.get('vin')
                    m_name=((veh.get('model') or {}).get('name')) or (None if model=='All' else model)
                    yr=veh.get('year') or year
                    trim_name=style.get('name') or style.get('trimName')
                    list_price=(csl.get('pricing') or {}).get('listPrice')
                    miles=veh.get('mileage') if veh.get('mileage') is not None else det.get('mileage')
                    dealer_name=dlr.get('name') if isinstance(dlr,dict) else None
                    city=det.get('dealerCity') or geo.get('city') or ''
                    state=det.get('dealerState') or geo.get('state') or 'US'
                    imgs=[e['node']['url'] for k,v in csl.items() if k.startswith('galleryImages') and isinstance(v,dict) for e in (v.get('edges') or []) if isinstance(e,dict) and isinstance(e.get('node'),dict) and e['node'].get('url')]
                    ev={'salvage':True} if is_clean is False else {}
                    rows.append(normalized(vin,m_name,yr,trim_name,list_price,miles,dealer_name,city,state,imgs,f'https://www.truecar.com/used-cars-for-sale/listing/{vin}/' if vin else '',risk=(is_clean is False),title_evidence=ev))
                return [x for x in rows if x]
        blocks=LD_RE.findall(response.text)
        if not blocks:raise SourceError(f'{source}: structured listing data missing')
        vehicles=[]
        def walk(value):
            if isinstance(value,list):
                for x in value:walk(x)
            elif isinstance(value,dict):
                if value.get('@type') in ('Vehicle','Car'):vehicles.append(value)
                for x in value.values():
                    if isinstance(x,(dict,list)):walk(x)
        for raw in blocks:
            try:walk(json.loads(raw))
            except json.JSONDecodeError:raise SourceError(f'{source}: malformed structured listing data')
        for x in vehicles:
            offer=x.get('offers') or {};offer=offer[0] if isinstance(offer,list) and offer else offer
            seller=offer.get('seller') or {};seller={'name':seller} if isinstance(seller,str) else seller
            address=seller.get('address') or {}
            rows.append(normalized(x.get('vehicleIdentificationNumber'),x.get('model'),x.get('vehicleModelDate') or x.get('modelDate'),x.get('vehicleConfiguration') or x.get('description'),offer.get('price'),x.get('mileageFromOdometer'),'Carvana' if source=='carvana' else seller.get('name'),address.get('addressLocality'),address.get('addressRegion'),x.get('image'),offer.get('url') or x.get('url'),title_evidence=x))
        if not vehicles:raise SourceError(f'{source}: no vehicle records; inspect source before treating this as empty inventory')
    return [x for x in rows if x]

def source_url(source,model,year,page,min_price=None,zip_code='78201',distance=50000,sort_type='PRICE',sort_dir='ASC'):
    if source=='autolist':
        return 'https://www.autolist.com/api/v2/search?'+urlencode(dict(make='Tesla',model=model,year_min=year,year_max=year,latitude=39.8283,longitude=-98.5795,radius='all',page=page,limit=100,sort_filter='price:asc'))
    if source=='cargurus':
        entities={'Model 3':'d2475','Model Y':'d3044','Model S':'d2039','Model X':'d2132','Cybertruck':'d3353','All':'m112'}
        params={'zip':zip_code,'distance':distance,'entitySelectingHelper.selectedEntity':entities.get(model,'m112'),'offset':(page-1)*48,'maxResults':48,'sortType':sort_type,'sortDir':sort_dir,'hideFrameDamage':'true','hideSalvage':'true','hideLemon':'true','hideTheft':'true','sellerType':'DEALER'}
        if year:params['startYear']=year;params['endYear']=year
        if min_price is not None:params['minPrice']=int(min_price)
        return 'https://www.cargurus.com/Cars/searchResults.action?'+urlencode(params)
    if source=='carmax':
        uri='/cars/tesla' if model in (None,'All') else f"/cars/tesla/{model.lower().replace(' ','-')}"
        return f'https://www.carmax.com/cars/api/search/run?uri={quote(uri,safe="")}&skip={(page-1)*96}&take=96&zipCode=78701&radius=radius-nationwide&shipping=-1&sort=20'
    if source=='marketcheck':
        params={'api_key':(os.getenv('MARKETCHECK_API_KEY') or '').strip(),'make':'Tesla','car_type':'used','seller_type':'dealer','clean_title':'true','rows':50,'start':(page-1)*50}
        if model and model!='All':params['model']=model
        if year:params['year']=year
        return 'https://mc-api.marketcheck.com/v2/search/car/active?'+urlencode(params)
    if source=='carvana':return f'https://www.carvana.com/cars/tesla?page={page}' if model=='All' else f'https://www.carvana.com/cars/tesla-{model.lower().replace(" ","-")}?page={page}'
    slug='' if model=='All' else model.lower().replace(' ','-')+'/'
    yr_q=f'&year_low={year}&year_high={year}' if year else ''
    return f'https://www.truecar.com/used-cars-for-sale/listings/tesla/{slug}location-austin-tx/?searchRadius=5000&excludeExpandedDelivery=false&salvage=false&lemon=false&frameDamage=false&theftRecovered=false{yr_q}&page={page}'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',choices=['autolist','cargurus','truecar','carvana','carmax','marketcheck'],required=True)
    parser.add_argument('--model',choices=['Model 3','Model Y','Model S','Model X','Cybertruck','All'],required=True);parser.add_argument('--year',type=int,default=0)
    parser.add_argument('--pages',type=int,default=1);parser.add_argument('--db',type=Path,default=ROOT/'.data/inventory.db');parser.add_argument('--output',type=Path,default=ROOT/'.data/source_snapshot.json')
    args=parser.parse_args()
    if not 1<=args.pages<=25:parser.error('Use 1–25 pages per bounded run')
    if args.year and not 2012<=args.year<=datetime.now(timezone.utc).year+1:parser.error('Unsupported model year')
    if args.source=='marketcheck' and not (os.getenv('MARKETCHECK_API_KEY') or '').strip():
        raise SystemExit('MARKETCHECK_API_KEY is not set')
    manifest={'source':args.source,'model':args.model,'year':args.year,'pages':[],'scope':'partial; not a national coverage claim'};all_rows=[]
    carmax_session=None
    for page in range(1,args.pages+1):
        url=source_url(args.source,args.model,args.year,page)
        try:
            if args.source=='carmax':
                if carmax_session is None:
                    carmax_session=requests.Session(impersonate='chrome120')
                    carmax_session.get('https://www.carmax.com/cars/tesla',timeout=15)
                response=carmax_session.get(url,headers={'Referer':'https://www.carmax.com/cars/tesla','Accept':'application/json'},timeout=15)
            else:
                response=requests.get(url,impersonate='chrome120',timeout=15)
            response.raise_for_status()
            rows=parse_source(args.source,response,args.model,args.year)
            # Model/year are source-query filters; preserve them if response omits redundant fields.
            for row in rows:
                if not row['source_url'] or row['source_url'].rstrip('/') in ('https://www.autolist.com','https://www.truecar.com'):raise SourceError('Missing vehicle-specific source link')
            all_rows.extend(rows);manifest['pages'].append({'url':url,'count':len(rows),'ok':True})
        except Exception as exc:
            manifest['pages'].append({'url':url,'ok':False,'error':type(exc).__name__+': '+str(exc)[:200]})
            print(json.dumps(manifest));raise SystemExit('Collection failed; existing snapshot was preserved')
    if not all_rows:raise SystemExit('No usable records; existing snapshot was preserved')
    now=datetime.now(timezone.utc).isoformat()
    manifest['accepted']=ingest(args.db,all_rows,args.source,now,complete=False)
    export(args.db,args.output);print(json.dumps(manifest))

if __name__=='__main__':main()
