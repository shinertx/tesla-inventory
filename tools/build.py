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
    buyer_surplus_share=float(os.getenv('BUYER_SURPLUS_SHARE','0.5')),
)

def schema_script(page_url, page_name, subset, description='', breadcrumb_name=None):
    prices=sorted(x['display_price'] for x in subset) if subset else []
    low_price=prices[0] if prices else 0
    med_price=prices[len(prices)//2] if prices else 0
    finds=[x for x in subset if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5]
    max_save=max((x.get('savings_amount',0) for x in finds),default=0)
    graph=[
        {'@type':['Organization','AutoDealer'],'@id':BASE+'/#organization','name':'Volts & VINs','url':BASE,
         'description':'Online used-Tesla marketplace with VIN-decoded specs and mileage-adjusted peer price benchmarks.'},
        {'@type':'WebSite','@id':BASE+'/#website','url':BASE,'name':'Volts & VINs','publisher':{'@id':BASE+'/#organization'},
         'potentialAction':{'@type':'SearchAction','target':BASE+'/?q={search_term_string}','query-input':'required name=search_term_string'}},
        {'@type':'Dataset','name':f'{page_name} — Used Tesla VIN & Market Benchmark Index',
         'description':description or f'VIN-verified catalog and mileage-adjusted peer price comparisons across {len(subset):,} used Tesla listings on Volts & VINs.',
         'url':page_url,'creator':{'@id':BASE+'/#organization'},'isAccessibleForFree':True,
         'keywords':['Used Tesla','Tesla Model Y','Tesla Model 3','Tesla Cybertruck','Tesla Model S','Tesla Model X','Used Tesla Price Benchmark','Tesla VIN Lookup']},
        {'@type':'ItemList','name':page_name,'url':page_url,'numberOfItems':len(subset),'itemListElement':[
            {'@type':'ListItem','position':i+1,'item':{
                '@type':'Car','name':f"{x['year']} Tesla {x['model']} {x['trim']}",
                'brand':{'@type':'Brand','name':'Tesla'},'model':x['model'],'vehicleModelDate':str(x['year']),
                'vehicleConfiguration':x['trim'],'fuelType':'Electricity',
                'vehicleIdentificationNumber':x['vin'],'itemCondition':'https://schema.org/UsedCondition',
                'mileageFromOdometer':{'@type':'QuantitativeValue','value':x['mileage'],'unitCode':'SMI'},
                **({'driveWheelConfiguration':x['drivetrain']} if x.get('drivetrain') else {}),
                **({'image':x['photo']} if x.get('photo') else {}),
                **({'offers':{'@type':'Offer','priceCurrency':'USD','price':x['display_price'],'availability':'https://schema.org/InStock','url':f"{BASE}/?vin={x['vin']}"}} if x.get('reservable') else {}),
                'url':f"{BASE}/?vin={x['vin']}"
            }} for i,x in enumerate(subset[:24])
        ]}
    ]
    if breadcrumb_name and page_url!=BASE+'/':
        graph.append({'@type':'BreadcrumbList','itemListElement':[
            {'@type':'ListItem','position':1,'name':'Volts & VINs','item':BASE+'/'},
            {'@type':'ListItem','position':2,'name':breadcrumb_name,'item':page_url}
        ]})
    if subset:
        graph.append({'@type':'FAQPage','mainEntity':[
            {'@type':'Question','name':f'How many listings are available in {page_name}?',
             'acceptedAnswer':{'@type':'Answer','text':f'Volts & VINs currently indexes {len(subset):,} VIN-verified used Tesla listings in this view, with estimated vehicle prices starting at ${low_price:,.0f} and a median estimated price of ${med_price:,.0f} (tax, title, and delivery quoted separately).'}},
            {'@type':'Question','name':'How does Volts & VINs calculate used Tesla buyer savings?',
             'acceptedAnswer':{'@type':'Answer','text':f'Each listing is compared against mileage-adjusted peer asking prices across matching Tesla model, year, trim, drivetrain, and mileage bands (minimum 5 comparable peers). In this view, {len(finds):,} vehicles are priced $500 or more below their peer benchmark{f" (up to ${max_save:,.0f} below benchmark)" if max_save else ""}. Vehicle savings apply to the vehicle price only; peer asking prices are not appraisals.'}},
            {'@type':'Question','name':'How does the $250 refundable Tesla reservation work?',
             'acceptedAnswer':{'@type':'Answer','text':'Select any Tesla and enter your delivery ZIP to review a complete quote identifying the licensed selling dealer, delivery fee, and taxes. Once the selling dealer confirms availability and a written hold, you can place a $250 refundable deposit credited toward your purchase.'}}
        ]})
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
    categories=[('models',m.lower().replace(' ','-'),f'{m} Tesla',f'model:{m}',[x for x in items if x['model']==m]) for m in sorted({x['model'] for x in items})]
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
        links=[f'<a href="{prefix}{g}/{s}.html">{html.escape(l)}</a>' for g,s,l,_,_ in categories if g=='deals'][:10]
        links+=[f'<a href="{prefix}{g}/{s}.html">{html.escape(l)}</a>' for g,s,l,_,_ in categories if g in ('models','years')][:22]
        links+=[f'<a href="{prefix}{g}/{s}.html">{html.escape(l)}</a>' for g,s,l,_,_ in categories if g=='states'][:18]
        return '<nav class="seo-links" aria-label="Browse Used Tesla inventory by deal, model, year, and state">'+''.join(links)+'</nav>'
    home_finds=sum(1 for x in items if x.get('savings_amount',0)>=500 and x.get('reference_sample',0)>=5)
    home_desc=f"Compare {len(items):,} VIN-verified used Tesla Model Y, Model 3, Model S, Model X, and Cybertruck listings ({home_finds:,} priced $500+ below mileage-adjusted peer benchmarks) on Volts & VINs."
    root_html=template.replace('<!-- STRUCTURED_DATA -->',schema_script(BASE+'/','Volts & VINs Used Tesla Inventory',items,home_desc)).replace('<!-- SEO_INTERNAL_LINKS -->',nav_links(''))
    (output/'index.html').write_text(root_html)
    for group in ('models','years','states','deals'):
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
            return f'<li><a href="../?vin={x["vin"]}">{html.escape(str(x["year"])+" "+x["model"]+" "+x["trim"])}</a> — ${x["display_price"]:,.0f}{save_note}, {x["mileage"]:,} mi, {html.escape(x.get("city") or x["state"])}; estimated vehicle price, tax, title and delivery quoted separately.</li>'
        cards=''.join(card_li(x) for x in subset[:24])
        text=template.replace('href="web/', 'href="../web/').replace('src="web/','src="../web/').replace('href="inventory.json"','href="../inventory.json"')
        text=text.replace('data-preset=""',f'data-preset="{html.escape(preset,quote=True)}"')
        text=text.replace('<title>Volts &amp; VINs | Shop Used Teslas Online</title>',f'<title>{html.escape(label)} Listings ({len(subset):,}) — From ${low_p:,.0f} | Volts &amp; VINs</title>')
        text=text.replace('<meta name="description" content="Explore used Tesla Model Y, Model 3, Model S, Model X, and Cybertruck listings. Compare vehicle photos, mileage, and estimated prices on Volts &amp; VINs.">',f'<meta name="description" content="{html.escape(desc,quote=True)}">')
        text=text.replace('<meta property="og:title" content="Volts &amp; VINs | Shop Used Teslas Online">',f'<meta property="og:title" content="{html.escape(label)} Listings ({len(subset):,}) | Volts &amp; VINs">')
        text=text.replace('<meta property="og:description" content="Compare used Teslas by model, mileage, estimated price, and vehicle photos.">',f'<meta property="og:description" content="{html.escape(desc,quote=True)}">')
        text=text.replace('<meta property="og:url" content="https://voltsandvins.com/">',f'<meta property="og:url" content="{href}">')
        text=text.replace('<link rel="canonical" href="https://voltsandvins.com/">',f'<link rel="canonical" href="{href}">')
        text=text.replace('<!-- STRUCTURED_DATA -->',schema_script(href,f'{label} Listings | Volts & VINs',subset,desc,label))
        text=text.replace('<!-- SEO_INTERNAL_LINKS -->',nav_links('../'))
        text=text.replace('<!-- CATEGORY_CONTENT -->',f'<section class="category-intro"><h1>{html.escape(label)} listings</h1><p>{len(subset):,} vehicles to explore starting at ${low_p:,.0f} (median ${med_p:,.0f}{f" · {finds_cnt:,} price finds below peer benchmark" if finds_cnt else ""}). Dealer confirmation is required before reservation.</p><details><summary>Featured vehicles &amp; market benchmark snapshot</summary><ul>{cards}</ul></details></section>')
        (output/group/(slug+'.html')).write_text(text)
        entries.append(href)
    ET.register_namespace('', 'http://www.sitemaps.org/schemas/sitemap/0.9')
    ns='{http://www.sitemaps.org/schemas/sitemap/0.9}'
    tree=ET.Element(ns+'urlset')
    for url in entries:ET.SubElement(ET.SubElement(tree,ns+'url'),ns+'loc').text=url
    ET.ElementTree(tree).write(output/'sitemap.xml',encoding='utf-8',xml_declaration=True)
    robots_lines=[
        'User-agent: *','Allow: /','Disallow: /api/','',
        'User-agent: Googlebot','Allow: /','',
        'User-agent: Google-Extended','Allow: /','',
        'User-agent: Bingbot','Allow: /','',
        'User-agent: OAI-SearchBot','Allow: /','',
        'User-agent: GPTBot','Allow: /','',
        'User-agent: ChatGPT-User','Allow: /','',
        'User-agent: PerplexityBot','Allow: /','',
        'User-agent: ClaudeBot','Allow: /','',
        'User-agent: Applebot','Allow: /','',
        'User-agent: Applebot-Extended','Allow: /','',
        'User-agent: Meta-ExternalAgent','Allow: /','',
        'User-agent: Amazonbot','Allow: /','',
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
        f'> Volts & VINs is a public used-Tesla marketplace and VIN-level price benchmark index covering {len(items):,} active used Tesla listings across the United States ({home_finds:,} priced $500+ below mileage-adjusted peer asking benchmarks).',
        '',
        '## Key Marketplace Facts',
        f'- **Published VIN-Verified Catalog**: {len(items):,} used Tesla vehicles (Model Y, Model 3, Model S, Model X, Cybertruck)',
        f'- **Peer-Benchmarked Price Finds**: {home_finds:,} listings priced `$500+` below mileage-adjusted peer asking prices (minimum 5 comparable peers in the same model, year, trim, drivetrain, and mileage band)',
        '- **VIN-Decoded Specifications**: Every listing includes 17-character ISO 3779 VIN validation, VIN-derived build factory (Austin vs. Fremont), drivetrain (AWD vs. RWD), mileage, and location',
        '- **Purchase & Reservation Model**: Online deal builder with ZIP delivery distance estimation; `$250` refundable reservation deposit after licensed selling dealer confirmation and written hold (`dealer_fulfillment`)',
        '',
        '## Used Tesla Inventory & Benchmark Summary by Model',
        *model_lines,
        '',
        '## High-Intent Deal & Configuration Hubs',
        *[f'- [{label} ({len(sub):,} listings)]({BASE}/{g}/{s}.html)' for g,s,label,_,sub in categories if g=='deals'],
        '',
        '## Machine-Readable Feeds & Indexes',
        f'- Full Top-100 Price-Find VIN Digest: {BASE}/llms-full.txt',
        f'- XML Sitemap ({len(entries)} URLs): {BASE}/sitemap.xml',
        f'- Live Public JSON Catalog: {BASE}/inventory.json',
    ]
    (output/'llms.txt').write_text('\n'.join(llms_summary)+'\n')
    find_rows=[
        f"- **{x['year']} Tesla {x['model']} {x['trim']}** (VIN `{x['vin']}`) — Est. Price: `${x['display_price']:,.0f}` | Peer Benchmark: `${x['reference_price']:,.0f}` ({x['reference_sample']} peers) | **Save `${x['savings_amount']:,.0f}`** | {x['mileage']:,} mi | {x.get('drivetrain') or 'EV'} | {x.get('city') or ''}, {x['state']} | {BASE}/?vin={x['vin']}"
        for x in top_finds
    ]
    (output/'llms-full.txt').write_text('\n'.join([
        *llms_summary,
        '',
        '## Top 100 Peer-Benchmarked Used Tesla Price Finds (Live VIN Index)',
        *(find_rows or ['- No multi-peer price finds in current test fixture.']),
        '',
        '## All Indexed Category, Model-Year & State Pages',
        *[f'- [{label} ({len(sub):,})]({BASE}/{g}/{s}.html)' for g,s,label,_,sub in categories],
    ])+'\n')
    print(json.dumps({'published':len(items),'excluded':dict(excluded),'category_pages':len(categories),'sitemap_urls':len(entries)}))
    return payload

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);args=parser.parse_args();build(args.source)
