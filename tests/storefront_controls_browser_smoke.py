"""Bounded local-fixture control checks; no real providers, payments, or messages.

Uses twelve synthetic listings, local ZIP/API responses, and intercepted SVGs.
It checks control behavior, not live inventory, carrier prices, or lender access.
"""
import functools
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright
from static_browser_smoke import PagesHandler

ROOT=Path(__file__).resolve().parents[1]
SVG='<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500"><rect width="800" height="500" fill="#dde7ed"/></svg>'


def fixtures():
    models=['Model 3','Model Y','Cybertruck','Model X','Model S','Model Y']*2
    prices=[20000,24000,28000,32000,48000,55000,23000,29000,35000,60000,45000,18000]
    miles=[15000,45000,25000,65000,8000,90000,70000,20000,35000,55000,100000,0]
    rows=[]
    for index,model in enumerate(models):
        price=prices[index];gap=[1000,3000,0,500,2000,0][index%6]
        rows.append({'vin':f'5YJ3E1EA8TEST{index:04d}','stock_number':f'FIXTURE-{index:04d}',
            'year':2018+index%7,'model':model,'trim':'Long Range','trim_family':'Long Range',
            'drivetrain':'AWD','drivetrain_basis':'Synthetic fixture','factory':'Fremont',
            'mileage':miles[index],'display_price':price,'reference_price':price+gap,
            'reference_sample':10,'benchmark_date':'2026-11-01','city':f'Fixture City {index}',
            'state':['TX','CA','CO'][index%3],'location_center':[index+1,0],
            'photo':None if index==11 else f'https://fixture.invalid/car-{index}-0.svg',
            'photo_count':0 if index==11 else 2,'hardware':'HW4' if index==0 else None,
            'reservable':index==0})
    return rows


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(PagesHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    rows=fixtures();by_vin={row['vin']:row for row in rows}
    photographed=rows[:-1]
    galleries={row['vin']:[{'url':row['photo'],'title':'Fixture front','category':'photos'},
        {'url':f'https://fixture.invalid/car-{index}-1.svg','title':'Fixture rear','category':'photos'}]
        for index,row in enumerate(photographed)}
    results={'local_fixtures':True,'real_provider':False,'real_payments':False,
             'fixture_listings':len(rows),'viewports':{},'javascript_errors':[]}
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (1440,390):
                state={'order':None,'privacy_requests':0,'preferences':[],'external_requests':[]}
                context=browser.new_context(viewport={'width':width,'height':1000},is_mobile=width<500)
                def route(request):
                    url=request.request.url
                    if 'inventory.json' in url:
                        return request.fulfill(json={'meta':{'media_version':'controls-fixture','built_at':'2026-11-01T00:00:00Z'},'items':rows})
                    if '/data/us_zip_centers.json' in url:
                        return request.fulfill(json={'zips':{'78201':['TX',0,0],'94103':['CA',10,0]}})
                    if '/media/' in url:return request.fulfill(json=galleries)
                    if '/api/' in url:
                        path=url.split('/api/',1)[1]
                        if path=='config':return request.fulfill(json={'requests_enabled':True,'payments_enabled':False})
                        if path=='requests':
                            data=request.request.post_data_json
                            assert data['consent'] is True and data['vin'] in by_vin
                            assert request.request.headers.get('idempotency-key')
                            state['order']={'id':'controls-fixture-order','access_token':'controls-fixture-access',
                                'vin':data['vin'],'state':'requested','payment_preference':data['payment_preference'],
                                'quote_version':0,'quote':None,'online_actions':[]}
                            return request.fulfill(status=201,json=state['order'])
                        assert request.request.headers.get('authorization')=='Bearer controls-fixture-access'
                        if path=='orders/controls-fixture-order/payment-preference':
                            pref=request.request.post_data_json['payment_preference']
                            state['preferences'].append(pref);state['order']['payment_preference']=pref
                            return request.fulfill(json=state['order'])
                        if path=='orders/controls-fixture-order/privacy':
                            assert request.request.method=='POST';state['privacy_requests']+=1
                            return request.fulfill(json={'recorded':True})
                        if path=='orders/controls-fixture-order/cases':return request.fulfill(json={'items':[]})
                        if path=='orders/controls-fixture-order':return request.fulfill(json=state['order'])
                        raise AssertionError('Unexpected fixture API request: '+path)
                    if request.request.resource_type=='image':return request.fulfill(content_type='image/svg+xml',body=SVG)
                    if url.startswith(base):return request.continue_()
                    state['external_requests'].append(url);return request.abort()
                context.route('**/*',route)
                page=context.new_page();page.on('pageerror',lambda error:results['javascript_errors'].append(str(error)))
                page.goto(base);page.wait_for_selector('.card')
                page.wait_for_function('()=>document.querySelector("#order-button").textContent==="Track my request"')
                assert page.locator('.card').count()==len(photographed)
                if width<500:page.locator('#mobile-filters').click()
                def visible_vins():return page.locator('.card').evaluate_all('(cards)=>cards.map(card=>card.dataset.vin)')
                def expect_rows(expected):
                    page.wait_for_function('(vins)=>{const actual=[...document.querySelectorAll(".card")].map(x=>x.dataset.vin);return actual.length===vins.length&&actual.every(v=>vins.includes(v));}',arg=[x['vin'] for x in expected])
                def reset():
                    page.locator('#reset').click();expect_rows(photographed)
                checks={}
                chips=['all','finds','under25','under30','lowmiles','Model Y','Model 3','Cybertruck']
                assert page.locator('[data-discover]').count()==len(chips)
                for chip in chips:
                    reset();page.locator(f'[data-discover="{chip}"]').click()
                    expected=photographed
                    if chip=='finds':expected=[x for x in expected if x['reference_price']-x['display_price']>=500]
                    elif chip=='under25':expected=[x for x in expected if x['display_price']<=25000]
                    elif chip=='under30':expected=[x for x in expected if x['display_price']<=30000]
                    elif chip=='lowmiles':expected=[x for x in expected if 0<x['mileage']<=30000]
                    elif chip in ('Model Y','Model 3','Cybertruck'):expected=[x for x in expected if x['model']==chip]
                    expect_rows(expected)
                    assert page.locator('.discovery-chip.active').get_attribute('data-discover')==chip
                checks['all_eight_discovery_buttons']=True
                reset();page.locator('#search').fill('FIXTURE-0002');expect_rows([rows[2]])
                page.locator('#search').fill('NO-SUCH-FIXTURE-TESLA');expect_rows([])
                assert page.locator('#empty').is_visible()
                checks['search_and_empty_results']=True
                for selector,value,predicate in [
                    ('year','2022',lambda x:x['year']==2022),
                    ('state','CA',lambda x:x['state']=='CA'),
                    ('price','30000',lambda x:x['display_price']<=30000),
                    ('mileage','60000',lambda x:0<x['mileage']<=60000),
                    ('hardware','HW4',lambda x:x['hardware']=='HW4')]:
                    reset();page.select_option('#'+selector,value);expect_rows([x for x in photographed if predicate(x)])
                checks['year_state_price_mileage_hardware_filters']=True
                reset();page.locator('#reservable-only').check();expect_rows([rows[0]])
                reset();page.locator('#photos-only').uncheck();expect_rows(rows)
                page.locator('#photos-only').check();expect_rows(photographed)
                checks['photos_and_reservable_toggles']=True
                page.locator('#zip-button').click();page.locator('#zip-input').fill('78201')
                page.locator('#zip-form button').click();page.locator('#zip-dialog').wait_for(state='hidden')
                sort_keys={'price':lambda x:x['display_price'],'price-desc':lambda x:-x['display_price'],
                    'mileage':lambda x:x['mileage'],'year':lambda x:-x['year'],
                    'savings':lambda x:-(x['reference_price']-x['display_price']),
                    'distance':lambda x:x['location_center'][0]}
                assert set(page.locator('#sort option').evaluate_all('(options)=>options.map(x=>x.value)'))==set(sort_keys)|{'recommended'}
                for mode,key in sort_keys.items():
                    page.select_option('#sort',mode)
                    page.wait_for_function('(mode)=>document.querySelector("#sort").value===mode',arg=mode)
                    values=[key(by_vin[vin]) for vin in visible_vins()]
                    assert values==sorted(values),(mode,values)
                page.select_option('#sort','recommended');expect_rows(photographed)
                assert len({by_vin[vin]['model'] for vin in visible_vins()[:3]})==3
                checks['all_seven_sort_modes']=True
                for row in rows[:2]:page.locator(f'[data-save="{row["vin"]}"]').click()
                page.locator('#saved-only').check();expect_rows(rows[:2])
                page.locator('#saved-only').uncheck();expect_rows(photographed)
                checks['saved_only_toggle']=True
                if width<500:page.locator('#mobile-filters').click()
                page.locator(f'[data-open="{rows[0]["vin"]}"]').first.click()
                page.locator('#vehicle-save').click();assert page.locator('#saved-count').inner_text()=='1'
                page.locator('#vehicle-save').click();assert page.locator('#saved-count').inner_text()=='2'
                page.locator('[data-close=vehicle-dialog]').click();checks['detail_save_toggle']=True
                page.locator('#saved-button').click()
                page.locator(f'[data-shortlist-open="{rows[1]["vin"]}"]').click()
                assert page.locator('#vehicle-dialog[open]').count()==1
                assert rows[1]['vin'] in page.url
                page.locator('[data-close=vehicle-dialog]').click();checks['shortlist_vehicle_open']=True
                page.locator('#saved-button').click();page.locator('#compare-saved').click()
                page.locator(f'[data-compare-open="{rows[0]["vin"]}"]').click()
                assert page.locator('#compare-dialog[open]').count()==0
                assert page.locator('#vehicle-dialog[open]').count()==1
                assert rows[0]['vin'] in page.url;checks['comparison_explore']=True
                page.locator('[data-close=vehicle-dialog]').click()
                page.locator('#privacy-button').click();page.locator('#privacy-dialog[open]').wait_for()
                assert 'retention' in page.locator('#privacy-dialog').inner_text().lower()
                page.locator('[data-close=privacy-dialog]').click();checks['privacy_notice_panel']=True
                page.locator(f'[data-open="{rows[0]["vin"]}"]').first.click();page.locator('#vehicle-request').click()
                page.locator('#deal-continue').click();page.locator('#request-dialog[open]').wait_for()
                page.locator('[name=name]').fill('Controls Fixture Buyer');page.locator('[name=email]').fill('controls@example.test')
                page.locator('[name=consent]').check();page.locator('#submit-request').click()
                page.locator('#order-dialog[open]').wait_for();page.locator('#order-payment-pref').select_option('partner_financing')
                page.wait_for_function('()=>document.querySelector("#order-payment-pref")?.value==="partner_financing"&&!document.querySelector("#order-payment-pref").disabled')
                assert state['preferences']==['partner_financing']
                page.reload();page.wait_for_selector('.card');page.locator('[data-close=vehicle-dialog]').click()
                page.locator('#order-button').click();page.locator('#order-dialog[open]').wait_for()
                assert page.locator('#order-payment-pref').input_value()=='partner_financing'
                checks['payment_preference_persists_after_reload']=True
                page.locator('#delete-request').click()
                page.wait_for_function('()=>document.querySelector("#toast").textContent.includes("Deletion request recorded")')
                assert state['privacy_requests']==1;checks['privacy_request_submission']=True
                assert not state['external_requests'],state['external_requests']
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                results['viewports'][str(width)]=checks
                context.close()
            assert not results['javascript_errors'],results['javascript_errors']
            browser.close()
    finally:server.shutdown();server.server_close()
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
