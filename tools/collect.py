#!/usr/bin/env python3
"""Bounded source collection. Fail visibly; never claim complete national coverage."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
import argparse, json, re, sys
from curl_cffi import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inventory import ingest, export
LD_RE=re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',re.S|re.I)

class SourceError(RuntimeError):pass

def numeric(value):
    if isinstance(value,dict):value=value.get('value')
    if value is None:return None
    try:return int(float(str(value).replace(',','')))
    except (ValueError,TypeError):return None

def normalized(vin,model,year,trim,price,mileage,dealer,city,state,photo,url,risk=False):
    model=str(model or '').replace('Tesla ','').strip()
    if model not in ('Model 3','Model Y','Model S','Model X','Cybertruck'):return None
    price=numeric(price);mileage=numeric(mileage);year=numeric(year)
    if price is None or mileage is None or year is None:return None
    return dict(vin=vin,model=model,year=year,dealer_trim=trim or 'Trim unverified',asking_price=price,mileage=mileage,
        dealer_name=dealer or 'Source dealer unverified',city=city or '',state=state or 'US',
        photo_url=photo if isinstance(photo,str) else '',source_url=url if isinstance(url,str) else '',risk_flag=risk)

def parse_source(source,response,model=None,year=None):
    rows=[]
    if source=='autolist':
        data=response.json()
        if not isinstance(data,dict) or not isinstance(data.get('search_results'),list):raise SourceError('Autolist response shape changed')
        for x in data['search_results']:
            rows.append(normalized(x.get('vin'),x.get('model'),x.get('year'),x.get('trim'),x.get('price_unformatted'),x.get('mileage_unformatted'),x.get('dealer_name'),x.get('city'),x.get('state'),x.get('primary_photo_url'),urljoin('https://www.autolist.com',x.get('url') or x.get('listing_url') or ''),bool(x.get('salvage') or x.get('is_salvage'))))
    elif source=='cargurus':
        data=response.json()
        if not isinstance(data,list):raise SourceError('CarGurus response shape changed')
        for x in data:
            city=x.get('sellerCity') or '';state=x.get('sellerRegion')
            rows.append(normalized(x.get('vin'),x.get('modelName') or x.get('model') or model,x.get('carYear') or year,x.get('trimName'),x.get('price'),x.get('mileage'),x.get('serviceProviderName'),city.split(',')[0],state,(x.get('originalPictureData') or {}).get('url'),f"https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action#listing={x['id']}" if x.get('id') else '',bool(x.get('salvage'))))
    else:
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
            rows.append(normalized(x.get('vehicleIdentificationNumber'),x.get('model'),x.get('vehicleModelDate') or x.get('modelDate'),x.get('vehicleConfiguration') or x.get('description'),offer.get('price'),x.get('mileageFromOdometer'),'Carvana' if source=='carvana' else seller.get('name'),address.get('addressLocality'),address.get('addressRegion'),x.get('image'),offer.get('url') or x.get('url')))
        if not vehicles:raise SourceError(f'{source}: no vehicle records; inspect source before treating this as empty inventory')
    return [x for x in rows if x]

def source_url(source,model,year,page):
    if source=='autolist':
        return 'https://www.autolist.com/api/cwv/seo/listings?'+urlencode(dict(make='Tesla',model=model,year_min=year,year_max=year,latitude=39.8283,longitude=-98.5795,radius='all',page=page,limit=100,sort_filter='price:asc'))
    if source=='cargurus':
        entities={'Model 3':'d2475','Model Y':'d3044','Model S':'d2039','Model X':'d2132','Cybertruck':'d3353'}
        return 'https://www.cargurus.com/Cars/searchResults.action?'+urlencode({'zip':'78201','distance':50000,'entitySelectingHelper.selectedEntity':entities[model],'startYear':year,'endYear':year,'offset':(page-1)*48,'maxResults':48,'sortType':'PRICE','sortDir':'ASC'})
    if source=='carvana':return f'https://www.carvana.com/cars/tesla-{model.lower().replace(" ","-")}?page={page}'
    return 'https://www.truecar.com/used-cars-for-sale/listings/tesla/'+model.lower().replace(' ','-')+f'/?year_low={year}&year_high={year}&page={page}'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',choices=['autolist','cargurus','truecar','carvana'],required=True)
    parser.add_argument('--model',choices=['Model 3','Model Y','Model S','Model X','Cybertruck'],required=True);parser.add_argument('--year',type=int,required=True)
    parser.add_argument('--pages',type=int,default=1);parser.add_argument('--db',type=Path,default=ROOT/'.data/inventory.db');parser.add_argument('--output',type=Path,default=ROOT/'.data/source_snapshot.json')
    args=parser.parse_args()
    if not 1<=args.pages<=10:parser.error('Use 1–10 pages per bounded run')
    if not 2012<=args.year<=datetime.now(timezone.utc).year+1:parser.error('Unsupported model year')
    manifest={'source':args.source,'model':args.model,'year':args.year,'pages':[],'scope':'partial; not a national coverage claim'};all_rows=[]
    for page in range(1,args.pages+1):
        url=source_url(args.source,args.model,args.year,page)
        try:
            response=requests.get(url,impersonate='chrome120',timeout=15);response.raise_for_status()
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
