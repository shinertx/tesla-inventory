#!/usr/bin/env python3
"""Build static discovery pages from a dated, attributed snapshot. No network calls."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse, collections, html, json, statistics, sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.inventory import valid_vin
BASE='https://shinertx.github.io/tesla-inventory'
SERVICE_FEE=1500


def safe_url(value):
    try:
        parsed=urlsplit(value or '')
        return value if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password else ''
    except ValueError:return ''

def timestamp(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)
    except (ValueError,AttributeError,TypeError):return None

def build(source=None,output=ROOT,now=None):
    output=Path(output);now=now or datetime.now(timezone.utc)
    source=Path(source or ROOT/'data/source_snapshot.json')
    raw=json.loads(source.read_text());items=[];seen=set();excluded=collections.Counter()
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
        observed=timestamp(x.get('observed_at'))
        # A live source observation is still not an exclusive dealer hold.
        source_recent=bool(observed and observed>=now-timedelta(hours=48))
        items.append({'vin':vin,'model':x['model'],'year':x['year'],
            'trim':x.get('dealer_trim') or 'Trim unverified','mileage':mileage,'asking_price':price,
            'service_fee':SERVICE_FEE,'display_price':price+SERVICE_FEE,
            'dealer':x.get('dealer_name') or 'Source dealer unverified','city':x.get('city') or '',
            'state':x.get('state') or 'US','photo':safe_url(x.get('photo_url')),'source_url':url,
            'source':x.get('source','unknown'),'source_observed_at':x.get('observed_at'),
            'expires_at':(age+timedelta(days=7)).isoformat(),'availability':'source_observed' if source_recent else 'unverified','title_status':'unverified',
            'hardware':None,'inspection_status':'not_verified','reference_price':None,'reference_sample':0})
    groups=collections.defaultdict(list)
    for x in items:
        band=next((b for b in (15000,30000,50000,75000) if x['mileage']<=b),999999)
        key=(x['model'],x['year'],x['trim'].casefold(),band)
        groups[key].append(x)
    for group in groups.values():
        if len(group)>=5:
            med=int(statistics.median(x['display_price'] for x in group))
            for x in group:x.update(reference_price=med,reference_sample=len(group))
    items.sort(key=lambda x:(x['display_price'],x['vin']))
    payload={'meta':{'built_at':now.isoformat(),'count':len(items),'mode':'discovery',
        'license_status':'pending','excluded':dict(excluded),'source_provenance':raw.get('provenance',''),
        'service_fee':SERVICE_FEE,'availability_note':'Listings require seller, title, condition, and price verification.'},'items':items}
    output.mkdir(parents=True,exist_ok=True)
    (output/'inventory.json').write_text(json.dumps(payload,separators=(',',':')))
    template=(ROOT/'web/index.html').read_text()
    (output/'index.html').write_text(template)
    # Category pages use the same shopping application with an explicit preset.
    # Only category pages enter the sitemap; VIN queries are application detail links.
    entries=[BASE+'/']
    categories=[('models',x.lower().replace(' ','-'),x,'model') for x in sorted({x['model'] for x in items})]
    categories += [('years',str(x),str(x),'year') for x in sorted({x['year'] for x in items})]
    categories += [('states',x.lower(),x,'state') for x in sorted({x['state'] for x in items}) if x!='US']
    for group in ('models','years','states'):
        folder=output/group;folder.mkdir(exist_ok=True)
        for obsolete in folder.glob('*.html'):obsolete.unlink()
    for group,slug,label,field in categories:
        subset=[x for x in items if str(x[field])==label]
        href=f'{BASE}/{group}/{slug}.html'
        cards=''.join(f'<li><a href="../?vin={x["vin"]}">{html.escape(str(x["year"])+" "+x["model"]+" "+x["trim"])}</a> — ${x["display_price"]:,}, includes ${SERVICE_FEE:,} service fee; tax, title and delivery unquoted.</li>' for x in subset[:24])
        text=template.replace('href="web/', 'href="../web/').replace('src="web/','src="../web/')
        text=text.replace('data-preset=""',f'data-preset="{field}:{html.escape(label,quote=True)}"')
        text=text.replace('<title>Tesla Marketplace</title>',f'<title>{html.escape(label)} Tesla listings | Tesla Marketplace</title>')
        text=text.replace('<link rel="canonical" href="'+BASE+'/">','<link rel="canonical" href="'+href+'">')
        text=text.replace('<!-- CATEGORY_CONTENT -->',f'<section class="category-intro"><h1>{html.escape(label)} Tesla listings</h1><p>{len(subset):,} candidate listings. Availability requires confirmation.</p><details><summary>Featured source listings</summary><ul>{cards}</ul></details></section>')
        (output/group/(slug+'.html')).write_text(text)
        entries.append(href)
    ET.register_namespace('', 'http://www.sitemaps.org/schemas/sitemap/0.9')
    ns='{http://www.sitemaps.org/schemas/sitemap/0.9}'
    tree=ET.Element(ns+'urlset')
    for url in entries:ET.SubElement(ET.SubElement(tree,ns+'url'),ns+'loc').text=url
    ET.ElementTree(tree).write(output/'sitemap.xml',encoding='utf-8',xml_declaration=True)
    (output/'robots.txt').write_text(f'User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {BASE}/sitemap.xml\n')
    print(json.dumps({'published':len(items),'excluded':dict(excluded),'category_pages':len(categories),'sitemap_urls':len(entries)}))
    return payload

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);args=parser.parse_args();build(args.source)
