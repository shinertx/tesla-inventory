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
from app.catalog import public_catalog
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
)

def schema_script(page_url, page_name, subset):
    graph=[
        {'@type':'Organization','@id':BASE+'/#organization','name':'Volts & VINs','url':BASE},
        {'@type':'WebSite','@id':BASE+'/#website','url':BASE,'name':'Volts & VINs'},
        {'@type':'ItemList','name':page_name,'url':page_url,'numberOfItems':len(subset),'itemListElement':[
            {'@type':'ListItem','position':i+1,'item':{
                '@type':'Car','name':f"{x['year']} Tesla {x['model']} {x['trim']}",
                'brand':{'@type':'Brand','name':'Tesla'},'model':x['model'],'vehicleModelDate':str(x['year']),
                'vehicleIdentificationNumber':x['vin'],'itemCondition':'https://schema.org/UsedCondition',
                'mileageFromOdometer':{'@type':'QuantitativeValue','value':x['mileage'],'unitCode':'SMI'},
                **({'image':x['photo']} if x.get('photo') else {}),
                'url':f"{BASE}/?vin={x['vin']}"
            }} for i,x in enumerate(subset[:24])
        ]}
    ]
    return '<script type="application/ld+json">'+json.dumps({'@context':'https://schema.org','@graph':graph},separators=(',',':'))+'</script>'


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
        if x.get('risk_flag') or vin in blocked:excluded['title_or_condition_risk']+=1;continue
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
        reservable=bool(x.get('agreed_dealer_net_cents') and x.get('supplier_commitment_reference') and x.get('configuration_evidence_reference') and hold_active and x.get('title_status')=='clean_verified')
        photos=normalize_photos(galleries.get(vin,[]) or x.get('photos',[]))
        items.append({'vin':vin,'model':x['model'],'year':x['year'],
            'trim':customer_trim(x.get('dealer_trim'),x['model']),'mileage':mileage,'display_price':price,
            'stock_number':'TSL-'+vin[-6:],'pricing_status':'estimate','city':x.get('city') or '',
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
    # Keep the first customer download small. Fetch only the selected gallery shard.
    media_dir=output/'media';media_dir.mkdir(exist_ok=True)
    shards={}
    for item in items:
        photos=item.get('photos',[])
        item['photo_count']=len(photos) or int(bool(item.get('photo')))
        if photos:shards.setdefault(format(int(item['vin'][-3:])%128,'02x'),{})[item['vin']]=photos
    for path in media_dir.glob('*.json'):
        if path.stem not in shards:path.unlink()
    for shard,values in shards.items():
        (media_dir/(shard+'.json')).write_text(json.dumps(values,sort_keys=True,separators=(',',':')))
    payload['meta']['media_version']=hashlib.sha256(json.dumps(shards,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12]
    index=public_catalog(payload)
    for item in index['items']:item.pop('photos',None)
    (output/'inventory.json').write_text(json.dumps(index,separators=(',',':')))
    template=(ROOT/'web/index.html').read_text()
    for asset in ('app.js','styles.css'):
        version=hashlib.sha256((ROOT/'web'/asset).read_bytes()).hexdigest()[:12]
        template=template.replace('web/'+asset,'web/'+asset+'?v='+version)
    # Category pages use the same shopping application with an explicit preset.
    # Only category pages enter the sitemap; VIN queries are application detail links.
    entries=[BASE+'/']
    categories=[('models',x.lower().replace(' ','-'),x,'model') for x in sorted({x['model'] for x in items})]
    categories += [('years',str(x),str(x),'year') for x in sorted({x['year'] for x in items})]
    categories += [('states',x.lower(),x,'state') for x in sorted({x['state'] for x in items}) if x!='US']
    def nav_links(prefix):
        links=[f'<a href="{prefix}{g}/{s}.html">{html.escape(l)} Tesla</a>' for g,s,l,_ in categories if g in ('models','years')][:18]
        links+=[f'<a href="{prefix}{g}/{s}.html">Used Tesla {html.escape(l)}</a>' for g,s,l,_ in categories if g=='states'][:16]
        return '<nav class="seo-links" aria-label="Browse Used Tesla inventory by model, year, and state">'+''.join(links)+'</nav>'
    root_html=template.replace('<!-- STRUCTURED_DATA -->',schema_script(BASE+'/','Volts & VINs Used Tesla Inventory',items)).replace('<!-- SEO_INTERNAL_LINKS -->',nav_links(''))
    (output/'index.html').write_text(root_html)
    for group in ('models','years','states'):
        folder=output/group;folder.mkdir(exist_ok=True)
        for obsolete in folder.glob('*.html'):obsolete.unlink()
    for group,slug,label,field in categories:
        subset=[x for x in items if str(x[field])==label]
        href=f'{BASE}/{group}/{slug}.html'
        cards=''.join(f'<li><a href="../?vin={x["vin"]}">{html.escape(str(x["year"])+" "+x["model"]+" "+x["trim"])}</a> — ${x["display_price"]:,.0f}, estimated vehicle price; tax, title and delivery quoted separately.</li>' for x in subset[:24])
        text=template.replace('href="web/', 'href="../web/').replace('src="web/','src="../web/').replace('href="inventory.json"','href="../inventory.json"')
        text=text.replace('data-preset=""',f'data-preset="{field}:{html.escape(label,quote=True)}"')
        text=text.replace('<title>Volts &amp; VINs | Used Tesla Inventory, Verified VINs &amp; Price Finds</title>',f'<title>{html.escape(label)} Used Tesla listings ({len(subset):,}) | Volts &amp; VINs</title>')
        text=text.replace('<link rel="canonical" href="'+BASE+'/">','<link rel="canonical" href="'+href+'">')
        text=text.replace('<!-- STRUCTURED_DATA -->',schema_script(href,f'{label} Used Tesla listings | Volts & VINs',subset))
        text=text.replace('<!-- SEO_INTERNAL_LINKS -->',nav_links('../'))
        text=text.replace('<!-- CATEGORY_CONTENT -->',f'<section class="category-intro"><h1>{html.escape(label)} Tesla listings</h1><p>{len(subset):,} vehicles to explore. Dealer confirmation is required before reservation.</p><details><summary>Featured vehicles</summary><ul>{cards}</ul></details></section>')
        (output/group/(slug+'.html')).write_text(text)
        entries.append(href)
    ET.register_namespace('', 'http://www.sitemaps.org/schemas/sitemap/0.9')
    ns='{http://www.sitemaps.org/schemas/sitemap/0.9}'
    tree=ET.Element(ns+'urlset')
    for url in entries:ET.SubElement(ET.SubElement(tree,ns+'url'),ns+'loc').text=url
    ET.ElementTree(tree).write(output/'sitemap.xml',encoding='utf-8',xml_declaration=True)
    (output/'robots.txt').write_text(f'User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {BASE}/sitemap.xml\n')
    if output!=ROOT or os.getenv('ENABLE_GITHUB_PAGES_CNAME','').lower()=='true':
        (output/'CNAME').write_text('voltsandvins.com\n')
    elif (output/'CNAME').exists():
        (output/'CNAME').unlink()
    (output/'voltsandvins-indexnow-key.txt').write_text(INDEXNOW_KEY+'\n')
    print(json.dumps({'published':len(items),'excluded':dict(excluded),'category_pages':len(categories),'sitemap_urls':len(entries)}))
    return payload

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);args=parser.parse_args();build(args.source)
