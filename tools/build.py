#!/usr/bin/env python3
"""Build static discovery pages from a dated, attributed snapshot. No network calls."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse, collections, html, json, sys, re, os, hashlib
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.inventory import valid_vin
from app.catalog import (public_catalog, public_photo, catalog_exclusions, stock_id_for, media_shard,
                         masked_vin_for, title_risk_reasons)
from tools.media import photo_url,normalize_photos
from tools.features import vehicle_features
from tools.pricing import PricingPolicy,propose_price,mileage_reference
BASE=os.getenv('PUBLIC_BASE_URL','https://voltsandvins.com').rstrip('/')
INDEXNOW_KEY='7f9a2d4c8e1b6a3f5c0d9e8b7a6f5e4d'
PRICING_POLICY=PricingPolicy(
    buyer_savings_cents=int(os.getenv('BUYER_SAVINGS_CENTS','150000')),
    minimum_contribution_cents=int(os.getenv('MIN_CONTRIBUTION_CENTS','100000')),
    platform_cost_floor_cents=int(os.getenv('PLATFORM_COST_FLOOR_CENTS','130000')),
    minimum_buyer_savings_cents=int(os.getenv('MIN_BUYER_SAVINGS_CENTS','50000')),
    buyer_surplus_share=float(os.getenv('BUYER_SURPLUS_SHARE','0.5')),
)

def schema_script(page_url, page_name, subset, description='', breadcrumb_name=None):
    graph=[
        {'@type':'Organization','@id':BASE+'/#organization','name':'Volts & VINs','url':BASE,
         'description':'Online used-Tesla marketplace with VIN-decoded specs and mileage-adjusted peer price benchmarks.'},
        {'@type':'WebSite','@id':BASE+'/#website','url':BASE,'name':'Volts & VINs','publisher':{'@id':BASE+'/#organization'},
         'potentialAction':{'@type':'SearchAction','target':BASE+'/?q={search_term_string}','query-input':'required name=search_term_string'}},
        {'@type':'CollectionPage','name':page_name,
         'description':description or f'VIN-decoded catalog and mileage-adjusted peer price comparisons across {len(subset):,} used Tesla listings on Volts & VINs.',
         'url':page_url,'creator':{'@id':BASE+'/#organization'},'isAccessibleForFree':True,
         'keywords':['Used Tesla','Tesla Model Y','Tesla Model 3','Tesla Cybertruck','Tesla Model S','Tesla Model X','Used Tesla Price Benchmark','Tesla VIN Lookup']},
        {'@type':'ItemList','name':page_name,'url':page_url,'numberOfItems':len(subset),'itemListElement':[
            {'@type':'ListItem','position':i+1,'item':{
                '@type':'Car','name':f"{x['year']} Tesla {x['model']} {x['trim']}",
                'brand':{'@type':'Brand','name':'Tesla'},'model':x['model'],'vehicleModelDate':str(x['year']),
                'vehicleConfiguration':x['trim'],'fuelType':'Electricity',
                'sku':x['stock_id'],'itemCondition':'https://schema.org/UsedCondition',
                'mileageFromOdometer':{'@type':'QuantitativeValue','value':x['mileage'],'unitCode':'SMI'},
                **({'driveWheelConfiguration':'https://schema.org/'+{'AWD':'AllWheelDriveConfiguration','RWD':'RearWheelDriveConfiguration'}[x['drivetrain']]} if x.get('drivetrain') in ('AWD','RWD') else {}),
                **({'image':x['photo']} if x.get('photo') else {}),
                **({'offers':{'@type':'Offer','priceCurrency':'USD','price':x['display_price'],'availability':'https://schema.org/InStock','url':f"{BASE}/v/{x['stock_id']}.html"}} if x.get('display_price') else {}),
                'url':f"{BASE}/v/{x['stock_id']}.html"
            }} for i,x in enumerate(subset[:24])
        ]}
    ]
    if breadcrumb_name and page_url!=BASE+'/':
        graph.append({'@type':'BreadcrumbList','itemListElement':[
            {'@type':'ListItem','position':1,'name':'Volts & VINs','item':BASE+'/'},
            {'@type':'ListItem','position':2,'name':breadcrumb_name,'item':page_url}
        ]})
    # Mark up visible catalog facts, without hidden FAQs or an unverified dealer identity.
    return '<script type="application/ld+json">'+json.dumps({'@context':'https://schema.org','@graph':graph},separators=(',',':')).replace('<','\\u003c')+'</script>'


def safe_url(value):
    try:
        parsed=urlsplit(value or '')
        return value if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password else ''
    except ValueError:return ''

def customer_trim(value,model):
    text=str(value or 'Trim unverified')
    text=re.sub(r'\$\s*[\d,]+(?:\.\d{2})?','',text)
    text=re.sub(r'\bwith\s+[\d,]+\s+miles.*','',text,flags=re.I)
    text=re.sub(r'^(?:Used\s+)?20\d\d\s+Tesla\s+'+re.escape(model)+r'\s*','',text,flags=re.I)
    text=re.sub(r'https?://\S+','',text)
    return ' '.join(text.split()).strip(' -•|')[:100] or 'Trim unverified'

def timestamp(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except (ValueError,AttributeError,TypeError):return None

_GALLERY_CACHE={}
def _load_galleries(gallery_file):
    if not gallery_file.exists():return {}
    stat=gallery_file.stat()
    key=(str(gallery_file),stat.st_mtime_ns,stat.st_size)
    if _GALLERY_CACHE.get('key')!=key:
        _GALLERY_CACHE['key']=key
        _GALLERY_CACHE['data']=json.loads(gallery_file.read_text())
    return _GALLERY_CACHE['data']

def build(source=None,output=ROOT,now=None,gallery_source=None):
    output=Path(output);now=now or datetime.now(timezone.utc)
    source=Path(source or ROOT/'.data/source_snapshot.json')
    galleries=_load_galleries(Path(gallery_source) if gallery_source else ROOT/'data/vehicle_photos.json')
    city_file=ROOT/'data/us_city_centers.json'
    city_centers=json.loads(city_file.read_text()) if city_file.exists() else {}
    raw=json.loads(source.read_text());items=[];seen=set();excluded=collections.Counter();supplier_rows={};source_prices={}
    blocked=json.loads((ROOT/'data/exclusions.json').read_text())
    for x in raw['items']:
        vin=x.get('vin','')
        if not valid_vin(vin) or vin in seen:excluded['invalid_or_duplicate_vin']+=1;continue
        seen.add(vin)
        if title_risk_reasons(x) or vin in blocked:excluded['title_or_condition_risk']+=1;continue
        age=timestamp(x.get('observed_at') or x.get('imported_at'))
        if not age or age<now-timedelta(days=7):excluded['expired_snapshot']+=1;continue
        price=x.get('asking_price');mileage=x.get('mileage')
        if not isinstance(price,int) or price<10000 or not isinstance(mileage,int) or mileage<0:
            excluded['invalid_price_or_mileage']+=1;continue
        url=safe_url(x.get('source_url'))
        if not url:excluded['missing_source']+=1;continue
        supplier_rows[vin]=x;source_prices[vin]=price
        observed=timestamp(x.get('observed_at'))
        # A live source observation is still not an exclusive dealer hold.
        source_recent=bool(observed and observed>=now-timedelta(hours=48))
        hold_until=x.get('seller_hold_until')
        hold_ts=hold_until if isinstance(hold_until,int) else (int(timestamp(hold_until).timestamp()) if timestamp(hold_until) else 0)
        hold_active=hold_ts>int(now.timestamp())+1800
        reservable=bool(x.get('agreed_dealer_net_cents') and x.get('supplier_commitment_reference') and x.get('configuration_evidence_reference') and x.get('title_history_reference') and hold_active and x.get('title_status')=='clean_verified')
        photos=normalize_photos(galleries.get(vin,[]) or x.get('photos',[]))
        items.append({'vin':vin,'model':x['model'],'year':x['year'],
            'trim':customer_trim(x.get('dealer_trim'),x['model']),'mileage':mileage,'display_price':price,
            'stock_number':stock_id_for(vin),'pricing_status':'estimate','city':x.get('city') or '',
            'state':x.get('state') or 'US','photo':photos[0]['url'] if photos else photo_url(x.get('photo_url')),'photos':photos,
            'fulfillment':'dealer_owned','source_observed_at':x.get('observed_at'),'benchmark_date':(age or now).date().isoformat(),
            'expires_at':(age+timedelta(days=7)).isoformat(),'reservable':reservable,
            'availability':'seller_approved' if reservable else ('source_observed' if source_recent else 'unverified'),
            'title_status':'clean_verified' if reservable else 'unverified',
            'inspection_status':'verified' if (reservable and x.get('inspection_reference')) else 'not_verified','reference_price':None,'reference_sample':0,'savings_amount':0,
            'location_center':city_centers.get(str(x.get('city') or '').casefold().replace(' ','')+'|'+str(x.get('state') or '')),**vehicle_features(x)})
    groups=collections.defaultdict(list)
    for x in items:
        band=next((b for b in (15000,30000,50000,75000) if x['mileage']<=b),999999)
        supplier=supplier_rows[x['vin']]
        pricing_trim=customer_trim(supplier.get('verified_trim'),x['model']) if supplier.get('configuration_evidence_reference') else x['trim']
        key=(x['model'],x['year'],pricing_trim.casefold(),x.get('drivetrain') or 'unknown',band)
        groups[key].append(x)
    opportunities=[]
    for group in groups.values():
        peers=[{'vin':x['vin'],'mileage':x['mileage'],'asking_cents':source_prices[x['vin']]*100} for x in group]
        for x in group:
            reference,sample=mileage_reference(x,peers,PRICING_POLICY)
            supplier=supplier_rows[x['vin']]
            net=supplier.get('agreed_dealer_net_cents')
            committed=bool(net and supplier.get('supplier_commitment_reference'))
            net=int(net) if committed else source_prices[x['vin']]*100
            costs=supplier.get('platform_cost_cents')
            proposal=propose_price(net,reference,sample,costs,PRICING_POLICY)
            hints=[]
            drive=(supplier.get('decoded_drive_hint') or '').lower()
            trim=(supplier.get('decoded_trim_hint') or '').lower()
            listed=x['trim'].lower()
            if 'awd' in drive and any(k in listed for k in ('rwd','rear wheel','rear-wheel')):hints.append('drivetrain_mismatch_review')
            if 'performance' in trim and 'performance' not in listed:hints.append('performance_trim_review')
            if listed in ('standard','base','trim unverified'):hints.append('configuration_review')
            if proposal['requires_market_review']:hints.append('large_gap_comparison_review')
            if not reference:hints.append('insufficient_comparables')
            if not supplier.get('configuration_evidence_reference'):hints.append('equipment_evidence_required')
            verified_commit=bool(committed and supplier.get('configuration_evidence_reference'))
            needs_review=bool((proposal['requires_market_review'] or 'drivetrain_mismatch_review' in hints or 'performance_trim_review' in hints) and not verified_commit)
            x['display_price']=(source_prices[x['vin']]*100 if needs_review else proposal['proposed_retail_cents'])/100
            x['pricing_basis']='source_asking_pending_review' if needs_review else proposal['pricing_basis']
            public_reference=reference if not needs_review else None
            x['reference_price']=public_reference/100 if public_reference else None
            x['reference_sample']=sample if public_reference else 0
            x['savings_amount']=max(0,int(round(x['reference_price']-x['display_price']))) if x['reference_price'] and x['reference_price']>x['display_price'] else 0
            opportunities.append({'vin':x['vin'],'model':x['model'],'year':x['year'],'trim':x['trim'],
                'source_dealer':supplier.get('dealer_name'),'source_url':supplier.get('source_url'),
                'source_asking_cents':source_prices[x['vin']]*100,'dealer_net_cents':net,
                'dealer_net_basis':'agreed_commitment' if committed else 'unconfirmed_source_asking',
                'configuration_verified':bool(supplier.get('configuration_evidence_reference')),
                'review_flags':hints,**proposal})
    opportunities.sort(key=lambda x:(x['modeled_contribution_cents'] if x['modeled_contribution_cents'] is not None else x['modeled_gross_spread_cents']),reverse=True)
    private=output/'.data';private.mkdir(parents=True,exist_ok=True,mode=0o700)
    (private/'arbitrage_opportunities.json').write_text(json.dumps({'basis':'Proposals; asking-price comparisons do not prove achievable sales or collected profit.','items':opportunities},separators=(',',':')))
    items.sort(key=lambda x:(x['display_price'],x['vin']))
    payload={'meta':{'built_at':now.isoformat(),'count':len(items),'reservable_count':sum(1 for x in items if x.get('reservable')),'mode':'dealer_fulfillment',
        'partner_onboarding_status':'pending','excluded':dict(excluded),'availability_note':'Listings require seller, title, condition, and price verification.'},'items':items}
    output.mkdir(parents=True,exist_ok=True)
    migrated=migrate_public_catalog(payload,output,shards={},render=True,excluded=excluded)
    return migrated['private']


def migrate_public_catalog(catalog,output=ROOT,*,shards=None,render=False,excluded=None):
    """Move public VIN identities to stock IDs without repricing or collecting sources.

    Existing gallery arrays are preserved. The VIN-keyed transaction inventory stays
    private so checkout never needs to recover an identity from public data.
    """
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    private_dir=output/'.data';private_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    private_path=private_dir/'transaction_inventory.json'
    prior={}
    if private_path.is_file():
        prior={stock_id_for(x['vin']):x for x in json.loads(private_path.read_text()).get('items',[])}
    if shards is None:
        shards={p.stem:json.loads(p.read_text()) for p in (output/'media').glob('*.json')}
    gallery_lookup={key:photos for values in shards.values() for key,photos in values.items()}
    blocked=catalog_exclusions(output/'inventory.json')
    private_items=[];published_shards={};seen=set();filtered=0
    for original in catalog.get('items',[]):
        row=dict(original)
        if not row.get('vin'):
            old=prior.get(row.get('stock_id'))
            if not old:raise ValueError('Private transaction identity is required for catalog migration')
            row={**old,**row,'vin':old['vin']}
            # A repeated public refresh must not replace an original source URL with its relay URL.
            if str(row.get('photo','')).startswith('https://api.voltsandvins.com/api/vehicles/'):
                originals=[old.get('photo')]+[p.get('url') for p in old.get('photos',[]) if isinstance(p,dict)]
                original=next((u for u in originals if public_photo(old['vin'],{'url':u})['url']==row['photo']),None)
                if not original:raise ValueError('Private source image is required for catalog migration')
                row['photo']=original
            row['photos']=old.get('photos',[])
        vin=row['vin'];stock=stock_id_for(vin)
        if stock in seen:raise ValueError('Duplicate public stock identity')
        seen.add(stock)
        if vin in blocked or title_risk_reasons(row):filtered+=1;continue
        photos=normalize_photos(row.get('photos') or gallery_lookup.get(stock) or gallery_lookup.get(vin) or [])
        if not photos and int(row.get('photo_count') or 0)>1:
            raise ValueError('Existing vehicle gallery is missing; migration stopped')
        masked=masked_vin_for(vin)
        row.update(stock_id=stock,stock_number=stock,masked_vin=masked,photos=photos,
                   photo_count=len(photos) or int(bool(row.get('photo'))))
        private_items.append(row)
        if photos:published_shards.setdefault(media_shard(stock),{})[stock]=[public_photo(vin,photo) for photo in photos]
    meta={**catalog.get('meta',{}),'count':len(private_items),
          'reservable_count':sum(x.get('reservable') is True for x in private_items)}
    meta['media_version']=hashlib.sha256(json.dumps(published_shards,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12]
    private={'meta':meta,'items':private_items}
    # The .data directory is ignored by Git and omitted from public deployment.
    private_path.write_text(json.dumps(private,separators=(',',':')))
    private_path.chmod(0o600)
    public=public_catalog(private)
    for item in public['items']:item.pop('photos',None)
    media_dir=output/'media';media_dir.mkdir(exist_ok=True)
    for old in media_dir.glob('*.json'):
        if old.stem not in published_shards:old.unlink()
    for shard,values in published_shards.items():
        (media_dir/(shard+'.json')).write_text(json.dumps(values,sort_keys=True,separators=(',',':')))
    (output/'inventory.json').write_text(json.dumps(public,separators=(',',':')))
    if render:render_public_pages(public,output,excluded=excluded)
    return {'private':private,'public':public,'shards':published_shards,'excluded_count':filtered}

def render_public_pages(catalog,output=ROOT,*,excluded=None,now=None):
    """Refresh discovery pages from published data without repricing or fetching sources."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    catalog=public_catalog(catalog)
    now=now or datetime.now(timezone.utc)
    items=[x for x in catalog['items'] if not x.get('expires_at') or (timestamp(x['expires_at']) and timestamp(x['expires_at'])>now)]
    template=(ROOT/'web/index.html').read_text()
    for asset in ('app.js','pricing.js','legacy-redirect.js','styles.css'):
        version=hashlib.sha256((ROOT/'web'/asset).read_bytes()).hexdigest()[:12]
        template=template.replace('web/'+asset,'web/'+asset+'?v='+version)
    catalog_version=hashlib.sha256(json.dumps(catalog,separators=(',',':')).encode()).hexdigest()[:12]
    template=template.replace('<!-- CATALOG_VERSION -->',f'<meta name="volts-catalog-version" content="{catalog_version}">')
    # Each published VIN has one stable static page, independent of its savings rank.
    entries=[BASE+'/']
    categories=[('models',m.lower().replace(' ','-'),f'Used Tesla {m}',f'model:{m}',[x for x in items if x['model']==m]) for m in sorted({x['model'] for x in items})]
    categories += [('years',str(y),f'{y} Tesla',f'year:{y}',[x for x in items if x['year']==y]) for y in sorted({x['year'] for x in items})]
    categories += [('states',s.lower(),f'Used Tesla {s}',f'state:{s}',[x for x in items if x['state']==s]) for s in sorted({x['state'] for x in items}) if s!='US']
    deal_specs=[
        ('price-finds','Used Tesla Price Finds Below Market Benchmark','discover:finds;sort:savings',sorted([x for x in items if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5],key=lambda x:(-x.get('savings_amount',0),x['display_price']))),
        ('under-25000','Used Teslas Under $25,000','discover:under25;price:25000',[x for x in items if x['display_price']<=25000]),
        ('under-30000','Used Teslas Under $30,000','discover:under30;price:30000',[x for x in items if x['display_price']<=30000]),
        ('under-35000','Used Teslas Under $35,000','price:35000',[x for x in items if x['display_price']<=35000]),
        ('low-mileage','Low-Mileage Used Teslas Under 30,000 Miles','discover:lowmiles;mileage:30000',[x for x in items if 0<x['mileage']<=30000]),
        ('awd','Used All-Wheel Drive (AWD) Teslas','drivetrain:AWD',[x for x in items if x.get('drivetrain')=='AWD']),
        ('rwd','Used Rear-Wheel Drive (RWD) Teslas','drivetrain:RWD',[x for x in items if x.get('drivetrain')=='RWD']),
        ('long-range','Used Tesla Long Range','trim-family:Long Range',[x for x in items if x.get('trim_family')=='Long Range']),
        ('performance','Used Tesla Performance','trim-family:Performance',[x for x in items if x.get('trim_family')=='Performance']),
        ('plaid','Used Tesla Plaid','trim-family:Plaid',[x for x in items if x.get('trim_family')=='Plaid']),
        ('standard-range','Used Tesla Standard Range','trim-family:Standard Range',[x for x in items if x.get('trim_family')=='Standard Range']),
        ('austin-build','Austin Gigafactory Built Used Teslas','factory:Austin',[x for x in items if x.get('factory')=='Austin']),
        ('fremont-build','Fremont Factory Built Used Teslas','factory:Fremont',[x for x in items if x.get('factory')=='Fremont']),
    ]
    for slug,label,preset,sub in deal_specs:
        if len(sub)>=5:categories.append(('deals',slug,label,preset,sub))
    if len(items)>=50:
        by_ym=collections.defaultdict(list)
        by_sm=collections.defaultdict(list)
        for x in items:
            by_ym[(x['year'],x['model'])].append(x)
            if x['state']!='US':by_sm[(x['state'],x['model'])].append(x)
        for (y,m),sub in sorted(by_ym.items(),key=lambda kv:(-kv[0][0],kv[0][1])):
            if len(sub)>=15:categories.append(('models',f"{y}-{m.lower().replace(' ','-')}",f"{y} Tesla {m}",f"model:{m};year:{y}",sub))
        for (s,m),sub in sorted(by_sm.items()):
            if len(sub)>=35:categories.append(('states',f"{s.lower()}-{m.lower().replace(' ','-')}",f"Used Tesla {m} in {s}",f"state:{s};model:{m}",sub))
    def nav_links(prefix):
        links=[f'<a href="{prefix}browse/index.html">All vehicles, models, and locations</a>']
        links+=[f'<a href="{prefix}{g}/{s}.html">{html.escape(l)}</a>' for g,s,l,_,_ in categories if g=='deals'][:10]
        links+=[f'<a href="{prefix}{g}/{s}.html">{html.escape(l)}</a>' for g,s,l,_,_ in categories if g in ('models','years')][:22]
        links+=[f'<a href="{prefix}{g}/{s}.html">{html.escape(l)}</a>' for g,s,l,_,_ in categories if g=='states'][:18]
        return '<nav class="seo-links" aria-label="Browse Used Tesla inventory by deal, model, year, and state">'+''.join(links)+'</nav>'
    home_finds=sum(1 for x in items if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5)
    home_desc=f"Compare {len(items):,} VIN-decoded used Tesla Model Y, Model 3, Model S, Model X, and Cybertruck listings ({home_finds:,} priced $500+ below mileage-adjusted peer benchmarks) on Volts & VINs."
    root_html=template.replace('<!-- STRUCTURED_DATA -->',schema_script(BASE+'/','Volts & VINs Used Tesla Inventory',items,home_desc)).replace('<!-- SEO_INTERNAL_LINKS -->',nav_links(''))
    (output/'index.html').write_text(root_html)
    vehicle_pages=sorted(items,key=lambda x:x['stock_id'])
    for group in ('models','years','states','deals','v','browse'):
        folder=output/group;folder.mkdir(exist_ok=True)
        for obsolete in folder.glob('*.html'):obsolete.unlink()
    for group,slug,label,preset,subset in categories:
        href=f'{BASE}/{group}/{slug}.html'
        prices=sorted(x['display_price'] for x in subset) if subset else [0]
        low_p,med_p=prices[0],prices[len(prices)//2]
        finds_cnt=sum(1 for x in subset if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5)
        max_save=max((x.get('savings_amount',0) for x in subset if x.get('reference_sample',0)>=5),default=0)
        desc=f"Browse {len(subset):,} {label} listings starting at ${low_p:,.0f} (median ${med_p:,.0f}). Compare VIN-decoded specs, photos, and {finds_cnt:,} peer-benchmarked price finds{f' saving up to ${max_save:,.0f}' if max_save>=500 else ''} on Volts & VINs."
        def card_li(x):
            save_note=f" (Save ${x['savings_amount']:,.0f} vs. ${x['reference_price']:,.0f} peer benchmark)" if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5 else ''
            v_link=f'../v/{x["stock_id"]}.html'
            return f'<li><a href="{v_link}">{html.escape(str(x["year"])+" "+x["model"]+" "+x["trim"])}</a> — ${x["display_price"]:,.0f}{save_note}, {x["mileage"]:,} mi, {html.escape(x.get("city") or x["state"])}; direct Volts &amp; VINs inventory with transparent out-the-door pricing.</li>'
        cards=''.join(card_li(x) for x in subset[:24])
        text=template.replace('href="web/', 'href="../web/').replace('src="web/','src="../web/').replace('href="inventory.json"','href="../inventory.json"')
        text=text.replace('<h1>Find your next Tesla.</h1>','<h2>Find your next Tesla.</h2>')
        text=text.replace('data-preset=""',f'data-preset="{html.escape(preset,quote=True)}"')
        text=text.replace('<title>Volts &amp; VINs | Shop Used Teslas Online</title>',f'<title>{html.escape(label)} Listings ({len(subset):,}) — From ${low_p:,.0f} | Volts &amp; VINs</title>')
        text=text.replace('<meta name="description" content="Explore used Tesla Model Y, Model 3, Model S, Model X, and Cybertruck listings. Compare vehicle photos, mileage, and vehicle prices on Volts &amp; VINs.">',f'<meta name="description" content="{html.escape(desc,quote=True)}">')
        text=text.replace('<meta property="og:title" content="Volts &amp; VINs | Shop Used Teslas Online">',f'<meta property="og:title" content="{html.escape(label)} Listings ({len(subset):,}) | Volts &amp; VINs">')
        text=text.replace('<meta property="og:description" content="Compare used Teslas by model, mileage, vehicle price, and vehicle photos.">',f'<meta property="og:description" content="{html.escape(desc,quote=True)}">')
        text=text.replace('<meta property="og:url" content="https://voltsandvins.com/">',f'<meta property="og:url" content="{href}">')
        text=text.replace('<link rel="canonical" href="https://voltsandvins.com/">',f'<link rel="canonical" href="{href}">')
        text=text.replace('<!-- STRUCTURED_DATA -->',schema_script(href,f'{label} Listings | Volts & VINs',subset,desc,label))
        text=text.replace('<!-- SEO_INTERNAL_LINKS -->',nav_links('../'))
        text=text.replace('<!-- CATEGORY_CONTENT -->',f'<section class="category-intro"><h1>{html.escape(label)} listings</h1><p>{len(subset):,} vehicles to explore starting at ${low_p:,.0f} (median ${med_p:,.0f}{f" · {finds_cnt:,} price finds below peer benchmark" if finds_cnt else ""}). Direct Volts &amp; VINs inventory with transparent out-the-door pricing.</p><details><summary>Featured vehicles &amp; market benchmark snapshot</summary><ul>{cards}</ul></details></section>')
        (output/group/(slug+'.html')).write_text(text)
        entries.append(href)
    for x in vehicle_pages:
        stock=x['stock_id']
        v_href=f'{BASE}/v/{stock}.html'
        v_label=f"{x['year']} Tesla {x['model']} {x['trim']} (Stock {stock})"
        loc_text=f"{x['city']}, {x['state']}" if x.get('city') and x.get('state')!='US' else (x.get('city') or x.get('state') or 'US')
        has_benchmark=bool(x.get('reference_price') and x.get('reference_sample',0)>=5)
        has_savings=has_benchmark and x.get('savings_amount',0)>=500
        benchmark_note=(f"Save ${x['savings_amount']:,.0f} vs. ${x['reference_price']:,.0f} mileage-adjusted peer benchmark ({x['reference_sample']} comparable listings). " if has_savings else (f"Mileage-adjusted peer benchmark ${x['reference_price']:,.0f} ({x['reference_sample']} comparable listings). " if has_benchmark else 'A reliable peer price benchmark is not available for this listing. '))
        v_desc=f"{x['year']} Tesla {x['model']} {x['trim']} with {x['mileage']:,} miles in {loc_text}. Vehicle price ${x['display_price']:,.0f}. {benchmark_note}Direct Volts & VINs inventory with complete out-the-door pricing."
        spec_items=[
            f"<li><strong>VIN:</strong> {html.escape(x.get('masked_vin') or 'Verified Volts & VINs inventory')}</li>",
            f"<li><strong>Title:</strong> Clean title (salvage/branded titles excluded)</li>",
            f"<li><strong>Vehicle price:</strong> ${x['display_price']:,.0f}</li>",
            f"<li><strong>Odometer:</strong> {x['mileage']:,} mi</li>",
            *([f"<li><strong>Drivetrain:</strong> {html.escape(x['drivetrain'])}</li>"] if x.get('drivetrain') else []),
            *([f"<li><strong>Build factory:</strong> Built in {html.escape(x['factory'])}</li>"] if x.get('factory') else []),
            f"<li><strong>Vehicle location:</strong> {html.escape(loc_text)}</li>",
            *([f"<li><strong>Inventory status:</strong> Verified Volts &amp; VINs inventory. Ready for direct reservation.</li>"] if x.get('source_observed_at') else []),
        ]
        photo=(f'<img class="listing-overview-photo" src="{html.escape(x["photo"],quote=True)}" alt="{html.escape(v_label,quote=True)}" width="640" height="400" loading="lazy">' if x.get('photo') else '<p>Vehicle photos are not available for this listing yet.</p>')
        v_intro=(
            f'<section class="category-intro">'
            f'<h1>{html.escape(v_label)}</h1>'
            f'<p>Vehicle price ${x["display_price"]:,.0f}. {html.escape(benchmark_note)}'
            f'Direct Volts &amp; VINs inventory. Instant out-the-door pricing with insured shipping, state tax, and direct online reservation.</p>'
            f'{photo}'
            f'<details><summary>VIN-decoded specifications &amp; benchmark details</summary><ul>{"".join(spec_items)}</ul></details>'
            f'<p><a href="../models/{x["model"].lower().replace(" ","-")}.html">Compare other Tesla {html.escape(x["model"])} listings</a> · <a href="../browse/index.html">Browse all vehicles and locations</a></p>'
            f'</section>'
        )
        v_text=template.replace('href="web/', 'href="../web/').replace('src="web/','src="../web/').replace('href="inventory.json"','href="../inventory.json"')
        v_text=v_text.replace('<h1>Find your next Tesla.</h1>','<h2>Find your next Tesla.</h2>')
        v_text=v_text.replace('data-preset=""',f'data-preset="{html.escape("model:"+x["model"],quote=True)}" data-initial-stock-id="{html.escape(stock,quote=True)}"')
        v_title=f'{x["year"]} Tesla {x["model"]} — ${x["display_price"]:,.0f} | {stock} | Volts & VINs'
        v_text=v_text.replace('<title>Volts &amp; VINs | Shop Used Teslas Online</title>',f'<title>{html.escape(v_title)}</title>')
        v_text=v_text.replace('<meta name="description" content="Explore used Tesla Model Y, Model 3, Model S, Model X, and Cybertruck listings. Compare vehicle photos, mileage, and vehicle prices on Volts &amp; VINs.">',f'<meta name="description" content="{html.escape(v_desc,quote=True)}">')
        v_text=v_text.replace('<meta property="og:title" content="Volts &amp; VINs | Shop Used Teslas Online">',f'<meta property="og:title" content="{html.escape(v_label)} — ${x["display_price"]:,.0f} | Volts &amp; VINs">')
        v_text=v_text.replace('<meta property="og:description" content="Compare used Teslas by model, mileage, vehicle price, and vehicle photos.">',f'<meta property="og:description" content="{html.escape(v_desc,quote=True)}">')
        v_text=v_text.replace('<meta property="og:url" content="https://voltsandvins.com/">',f'<meta property="og:url" content="{v_href}">')
        v_text=v_text.replace('<link rel="canonical" href="https://voltsandvins.com/">',f'<link rel="canonical" href="{v_href}">')
        if x.get('photo'):
            v_text=v_text.replace('</head>',f'<meta property="og:image" content="{html.escape(x["photo"],quote=True)}"></head>')
        vehicle_schema=schema_script(v_href,v_label,[x],v_desc,v_label).replace(f'{BASE}/?vin={stock}',v_href)
        v_text=v_text.replace('<!-- STRUCTURED_DATA -->',vehicle_schema)
        v_text=v_text.replace('<!-- SEO_INTERNAL_LINKS -->',nav_links('../'))
        v_text=v_text.replace('<!-- CATEGORY_CONTENT -->',v_intro)
        (output/'v'/(stock+'.html')).write_text(v_text)
        entries.append(v_href)
    # A finite HTML directory reaches every VIN and category without JavaScript.
    chunks=[vehicle_pages[i:i+100] for i in range(0,len(vehicle_pages),100)] or [[]]
    browse_name=lambda n:'index.html' if n==0 else f'page-{n+1}.html'
    for number,chunk in enumerate(chunks):
        url=f'{BASE}/browse/{browse_name(number)}'
        label=f'Used Tesla inventory — page {number+1} of {len(chunks)}'
        description=f'Browse used Tesla listings {number*100+1 if chunk else 0}–{number*100+len(chunk)} of {len(vehicle_pages):,}. Compare vehicle prices, mileage, locations, and VIN-specific details.'
        rows=''.join(f'<li><a href="../v/{x["stock_id"]}.html">{x["year"]} Tesla {html.escape(x["model"])} {html.escape(x["trim"])} — Stock {x["stock_id"]}</a> — ${x["display_price"]:,.0f} · {x["mileage"]:,} mi · {html.escape(x.get("city") or "")}, {html.escape(x["state"])}</li>' for x in chunk)
        page_links=''.join(f'<a href="{browse_name(i)}"'+(' aria-current="page"' if i==number else '')+f'>{i+1}</a> ' for i in (range(len(chunks)) if number==0 else sorted({0,number-1,number,number+1,len(chunks)-1})) if 0<=i<len(chunks))
        category_links=(''.join(f'<li><a href="../{g}/{s}.html">{html.escape(l)} ({len(sub):,})</a></li>' for g,s,l,_,sub in categories) if number==0 else '')
        intro=f'<section class="category-intro"><h1>{html.escape(label)}</h1><p>{html.escape(description)} Direct Volts &amp; VINs inventory with transparent out-the-door pricing.</p><nav class="browse-pages" aria-label="Inventory pages">{page_links}</nav><ol start="{number*100+1}">{rows}</ol>'+('<h2>Browse by deal, model, year, and vehicle location</h2><ul>'+category_links+'</ul>' if category_links else '')+'</section>'
        text=template.replace('href="web/','href="../web/').replace('src="web/','src="../web/').replace('href="inventory.json"','href="../inventory.json"')
        text=text.replace('<h1>Find your next Tesla.</h1>','<h2>Find your next Tesla.</h2>')
        text=text.replace('<title>Volts &amp; VINs | Shop Used Teslas Online</title>',f'<title>{html.escape(label)} | Volts &amp; VINs</title>')
        text=re.sub(r'<meta name="description" content="[^"]*">',f'<meta name="description" content="{html.escape(description,quote=True)}">',text,count=1)
        text=text.replace('content="https://voltsandvins.com/"',f'content="{url}"').replace('<link rel="canonical" href="https://voltsandvins.com/">',f'<link rel="canonical" href="{url}">')
        text=text.replace('<meta property="og:title" content="Volts &amp; VINs | Shop Used Teslas Online">',f'<meta property="og:title" content="{html.escape(label,quote=True)} | Volts &amp; VINs">')
        text=text.replace('<meta property="og:description" content="Compare used Teslas by model, mileage, vehicle price, and vehicle photos.">',f'<meta property="og:description" content="{html.escape(description,quote=True)}">')
        text=text.replace('<!-- STRUCTURED_DATA -->',schema_script(url,label,chunk,description,label)).replace('<!-- SEO_INTERNAL_LINKS -->',nav_links('../')).replace('<!-- CATEGORY_CONTENT -->',intro)
        (output/'browse'/browse_name(number)).write_text(text)
        entries.append(url)
    ET.register_namespace('', 'http://www.sitemaps.org/schemas/sitemap/0.9')
    ET.register_namespace('image', 'http://www.google.com/schemas/sitemap-image/1.1')
    ns='{http://www.sitemaps.org/schemas/sitemap/0.9}'
    image_ns='{http://www.google.com/schemas/sitemap-image/1.1}'
    tree=ET.Element(ns+'urlset')
    vehicle_images={f'{BASE}/v/{x["stock_id"]}.html':x['photo'] for x in vehicle_pages if x.get('photo')}
    for url in entries:
        node=ET.SubElement(tree,ns+'url');ET.SubElement(node,ns+'loc').text=url
        if url in vehicle_images:ET.SubElement(ET.SubElement(node,image_ns+'image'),image_ns+'loc').text=vehicle_images[url]
    ET.ElementTree(tree).write(output/'sitemap.xml',encoding='utf-8',xml_declaration=True)
    robots_lines=[
        'User-agent: *','Disallow: /api/','Allow: /','',
        f'Sitemap: {BASE}/sitemap.xml',
    ]
    (output/'robots.txt').write_text('\n'.join(robots_lines)+'\n')
    (output/'CNAME').write_text('voltsandvins.com\n')
    (output/'voltsandvins-indexnow-key.txt').write_text(INDEXNOW_KEY+'\n')
    top_finds=sorted([x for x in items if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5],key=lambda x:(-x['savings_amount'],x['display_price']))[:100]
    model_lines=[]
    for m in sorted({x['model'] for x in items}):
        ms=[x for x in items if x['model']==m]
        mp=sorted(x['display_price'] for x in ms)
        mf=sum(1 for x in ms if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5)
        model_lines.append(f"- **Tesla {m}**: {len(ms):,} listings | Low: `${mp[0]:,.0f}` | Median: `${mp[len(mp)//2]:,.0f}` | Price Finds (`$500+` below peer benchmark): {mf:,} | Browse: {BASE}/models/{m.lower().replace(' ','-')}.html")
    llms_summary=[
        '# Volts & VINs (https://voltsandvins.com)',
        '',
        f'> Volts & VINs is a direct used-Tesla inventory and price benchmark index covering {len(items):,} listings across the United States ({home_finds:,} priced $500+ below mileage-adjusted peer asking benchmarks). Direct online reservation and delivery.',
        '',
        '## Key Marketplace Facts',
        f'- **Published VIN-Decoded Catalog**: {len(items):,} used Tesla vehicles (Model Y, Model 3, Model S, Model X, Cybertruck)',
        f'- **Peer-Benchmarked Price Finds**: {home_finds:,} listings priced `$500+` below mileage-adjusted peer asking prices (minimum 5 comparable peers in the same model, year, trim, drivetrain, and mileage band)',
        '- **VIN-Decoded Specifications**: Listings include VIN-derived build factory and drivetrain where decoded, with recorded mileage and vehicle location. Build factory is not the current vehicle location',
        '- **Purchase & Reservation Model**: Direct online purchase and reservation through Volts & VINs. Start with a $0 price lock, verify clean title and inspection details, then place a refundable $250 deposit to complete your order and arrange delivery.',
        '',
        '## Used Tesla Inventory & Benchmark Summary by Model',
        *model_lines,
        '',
        '## High-Intent Deal & Configuration Hubs',
        *[f'- [{label} ({len(sub):,} listings)]({BASE}/{g}/{s}.html)' for g,s,label,_,sub in categories if g=='deals'],
        '',
        '## Machine-Readable Feeds & Indexes',
        f'- AI Agent Filter & Search API (Filtered JSON): https://api.voltsandvins.com/api/search?model=Model+Y&max_price=36000&only_price_finds=true&limit=10',
        f'- OpenAPI 3.1 Action Specification (ChatGPT / Claude / Gemini Tools): {BASE}/openapi.json',
        f'- Full Top-100 Price-Find Stock Digest: {BASE}/llms-full.txt',
        f'- XML Sitemap ({len(entries)} URLs): {BASE}/sitemap.xml',
        f'- Complete crawlable vehicle and category directory: {BASE}/browse/index.html',
        f'- Live Public JSON Catalog: {BASE}/inventory.json',
    ]
    (output/'llms.txt').write_text('\n'.join(llms_summary)+'\n')
    openapi_spec={
        'openapi':'3.1.0',
        'info':{'title':'Volts & VINs Used Tesla Search & Benchmark API','version':'1.0.0','description':f'Query {len(items):,} direct Volts & VINs used Tesla listings with VIN-decoded facts, peer price benchmarks, and online reservation links.'},
        'servers':[{'url':'https://api.voltsandvins.com'}],
        'paths':{
            '/api/search':{
                'get':{
                    'operationId':'searchUsedTeslas',
                    'summary':'Filter VIN-decoded used Teslas by model, year, max price, mileage, state, drivetrain, and peer-benchmark savings.',
                    'parameters':[
                        {'name':'model','in':'query','schema':{'type':'string','enum':['Model Y','Model 3','Model S','Model X','Cybertruck']}},
                        {'name':'year_min','in':'query','schema':{'type':'integer'}},
                        {'name':'year_max','in':'query','schema':{'type':'integer'}},
                        {'name':'max_price','in':'query','schema':{'type':'integer'}},
                        {'name':'max_mileage','in':'query','schema':{'type':'integer'}},
                        {'name':'state','in':'query','schema':{'type':'string'}},
                        {'name':'drivetrain','in':'query','schema':{'type':'string','enum':['AWD','RWD']}},
                        {'name':'only_price_finds','in':'query','schema':{'type':'boolean'}},
                        {'name':'sort','in':'query','schema':{'type':'string','enum':['savings','price_asc','mileage_asc']}},
                        {'name':'limit','in':'query','schema':{'type':'integer','default':10,'maximum':50}},
                    ],
                    'responses':{'200':{'description':'Matching VIN-decoded Tesla listings with peer benchmarks and vehicle detail URLs.'}},
                }
            }
        },
    }
    (output/'openapi.json').write_text(json.dumps(openapi_spec,indent=2)+'\n')
    find_rows=[
        f"- **{x['year']} Tesla {x['model']} {x['trim']}** (Stock `{x['stock_id']}`) — Est. Price: `${x['display_price']:,.0f}` | Peer Benchmark: `${x['reference_price']:,.0f}` ({x['reference_sample']} peers) | **Save `${x['savings_amount']:,.0f}`** | {x['mileage']:,} mi | {x.get('drivetrain') or 'EV'} | {x.get('city') or ''}, {x['state']} | {BASE}/v/{x['stock_id']}.html"
        for x in top_finds
    ]
    (output/'llms-full.txt').write_text('\n'.join([
        *llms_summary,
        '',
        '## Top 100 Peer-Benchmarked Used Tesla Price Finds (Live Stock Index)',
        *(find_rows or ['- No multi-peer price finds in current test fixture.']),
        '',
        '## All Indexed Category, Model-Year & State Pages',
        *[f'- [{label} ({len(sub):,})]({BASE}/{g}/{s}.html)' for g,s,label,_,sub in categories],
    ])+'\n')
    # Content fingerprint changes with page data or assets, even if URLs stay the same.
    # No timestamps are invented. This marker is publication evidence, not indexing proof.
    digest=hashlib.sha256()
    public_files=['index.html','sitemap.xml','robots.txt','llms.txt','llms-full.txt','openapi.json']
    public_files += [urlsplit(url).path.lstrip('/') for url in entries if url!=BASE+'/']
    for name in sorted(set(public_files)):
        digest.update(name.encode()+b'\0'+hashlib.sha256((output/name).read_bytes()).digest())
    for name in ('app.js','pricing.js','legacy-redirect.js','styles.css'):
        digest.update(name.encode()+b'\0'+hashlib.sha256((ROOT/'web'/name).read_bytes()).digest())
    catalog_hash=hashlib.sha256(json.dumps(catalog,separators=(',',':')).encode()).hexdigest()
    digest.update(catalog_hash.encode())
    (output/'search-release.json').write_text(json.dumps({'version':1,'artifact_digest':digest.hexdigest(),
        'sitemap_sha256':hashlib.sha256((output/'sitemap.xml').read_bytes()).hexdigest(),
        'catalog_sha256':catalog_hash,'vehicle_pages':len(vehicle_pages),'browse_pages':len(chunks),'sitemap_urls':len(entries)},sort_keys=True)+'\n')
    result={'published':len(items),'excluded':dict(excluded or {}),'category_pages':len(categories),'vehicle_pages':len(vehicle_pages),'browse_pages':len(chunks),'sitemap_urls':len(entries)}
    print(json.dumps(result))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group();group.add_argument('--source',type=Path);group.add_argument('--public-catalog',type=Path);parser.add_argument('--output',type=Path,default=ROOT);args=parser.parse_args()
    if args.public_catalog:migrate_public_catalog(json.loads(args.public_catalog.read_text()),args.output,render=True)
    else:build(args.source,output=args.output)
