"""Fault-path browser checks using explicit local fixtures; no providers or messages."""
import functools,json,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from static_browser_smoke import PagesHandler

ROOT=Path(__file__).resolve().parents[1]
SVG='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#dce5eb"/></svg>'
STALE='7SAYGDEE0TEST0001'

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(PagesHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    source=json.loads((ROOT/'inventory.json').read_text())
    rows=[dict(x) for x in source['items'] if x.get('photo')][:3]
    for index,row in enumerate(rows):
        row.update(photo=f'https://example.test/photo-{index}-0.svg',photo_count=2,display_price=20000,
                   reference_price=[None,19000,20000][index],reference_sample=[0,10,10][index],
                   hardware=None,reservable=False)
    empty=dict(source['items'][3],photo=None,photo_count=0,hardware=None,reservable=False)
    fixture_rows=[*rows,empty]
    galleries={x['vin']:[{'url':f'https://example.test/photo-{i}-{p}.svg','title':f'Fixture angle {p+1}','category':'photos'} for p in range(2)] for i,x in enumerate(rows)}
    results={};errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (1440,390):
                context=browser.new_context(viewport={'width':width,'height':1000})
                state={'order':None,'cases':[],'case_calls':[],'pending':None,'lost_ack':True}
                def route(request):
                    url=request.request.url
                    if 'inventory.json' in url:return request.fulfill(json={'meta':{'media_version':'fixture'},'items':fixture_rows})
                    if '/media/' in url:return request.fulfill(json=galleries)
                    if '/api/' in url:
                        path=url.split('/api/',1)[1]
                        if path=='config':return request.fulfill(json={'requests_enabled':True,'payments_enabled':False})
                        if path=='requests':
                            state['order']={'id':'fixture-order','access_token':'fixture-access','vin':rows[0]['vin'],'state':'requested','payment_preference':'cash','quote_version':0,'quote':None,'online_actions':[]}
                            return request.fulfill(status=201,json=state['order'])
                        if path=='orders/fixture-order/cases':
                            assert request.request.headers.get('authorization')=='Bearer fixture-access'
                            if request.request.method=='GET':return request.fulfill(json={'items':state['cases']})
                            state['case_calls'].append(request.request.headers.get('idempotency-key'))
                            if not state['cases']:state['cases'].append({'id':'case-fixture','kind':'other','description':'Fixture support request','status':'open','created_at':1,'due_at':2})
                            if state['lost_ack']:
                                state['pending']=request;state['lost_ack']=False;return
                            return request.fulfill(status=200,json=state['cases'][0])
                        if path=='orders/fixture-order/cancel':
                            state['order']['state']='cancelled';return request.fulfill(json=state['order'])
                        if path=='orders/fixture-order':return request.fulfill(json=state['order'])
                        return request.fulfill(status=404,json={'detail':'Fixture endpoint unavailable'})
                    if request.request.resource_type=='image':
                        return request.fulfill(content_type='image/svg+xml',body=SVG)
                    if url.startswith(base):return request.continue_()
                    return request.abort()
                context.route('**/*',route)
                context.add_init_script('localStorage.setItem("marketplace_saved",'+json.dumps(json.dumps([x['vin'] for x in rows]+[STALE]))+')')
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base);page.wait_for_selector('.card')
                assert not page.locator('#hardware').is_visible() and not page.locator('#reservable-only').is_visible()
                page.locator('#saved-button').click();assert page.locator('.shortlist-unavailable').count()==1
                page.locator('[data-remove-unavailable]').click();assert page.locator('#saved-count').inner_text()=='3'
                page.locator('#compare-saved').click();text=page.locator('#compare-content').inner_text()
                assert 'Comparison unavailable' in text and '$1,000 above the $19,000 peer reference' in text and 'At the $20,000 peer reference' in text,text
                assert 'At market reference' not in text
                results[f'comparison_and_stale_favorites_{width}']=True
                page.locator('[data-close=compare-dialog]').click()
                page.locator(f'[data-open="{rows[0]["vin"]}"]').click();page.wait_for_selector('.gallery-thumb')
                page.locator('#photo-expand').click()
                # Cached images may not issue a request; inject the browser failure event deterministically.
                page.locator('#full-photo').evaluate('(img)=>img.dispatchEvent(new Event("error"))')
                page.locator('#full-photo-error').wait_for(state='visible')
                assert not page.locator('#full-photo').is_visible()
                page.locator('#retry-full-photo').click()
                page.wait_for_function('()=>document.querySelector("#full-photo").naturalWidth>0&&!document.querySelector("#full-photo").hidden')
                assert page.locator('#full-next').is_visible() and page.locator('#full-prev').is_visible()
                results[f'fullscreen_retry_{width}']=True
                page.locator('[data-close=photo-dialog]').click();page.locator('[data-close=vehicle-dialog]').click()
                page.goto(base+'?vin='+empty['vin'])
                page.get_by_text('Vehicle photos are not available yet.',exact=True).wait_for()
                assert not page.locator('#photo-expand').is_visible()
                assert not page.locator('#gallery-next').is_visible() and not page.locator('#gallery-prev').is_visible()
                results[f'empty_gallery_has_no_dead_controls_{width}']=True
                # Eligible inventory must restore these filters and a real loaded photo must restore expansion.
                eligible={**empty,'hardware':'HW4','reservable':True,'photo_count':None}
                page.route('**/inventory.json*',lambda r:r.fulfill(json={'meta':{},'items':[eligible]}))
                page.route('**/api/vehicles/*/photos',lambda r:r.fulfill(json={'photos':[{'url':'https://example.test/recovered.svg','title':'Recovered fixture photo','category':'photos'}]}))
                page.reload();page.locator('#photo-expand').wait_for(state='visible')
                page.locator('[data-close=vehicle-dialog]').click()
                if width==390:page.locator('#mobile-filters').click()
                assert page.locator('#hardware').is_visible() and page.locator('#reservable-only').is_visible()
                page.locator('#photos-only').uncheck();page.select_option('#hardware','HW4');page.locator('#reservable-only').check()
                assert page.locator('#result-count').inner_text()=='1 Tesla listing'
                results[f'eligible_controls_restore_{width}']=True
                context.close()

                context=browser.new_context(viewport={'width':width,'height':1000});context.route('**/*',route)
                context.add_init_script('Object.defineProperty(window,"sessionStorage",{get(){throw new DOMException("Storage blocked","SecurityError")}})')
                page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'?vin='+rows[0]['vin']);page.locator('#vehicle-request').click();page.locator('#deal-zip').fill('78701');page.locator('#deal-continue').click()
                page.locator('[name=name]').fill('Fixture Storage Test');page.locator('[name=email]').fill('fixture@example.test');page.locator('[name=consent]').check();page.locator('#submit-request').click()
                page.locator('#access-warning').wait_for();assert 'Preparing your deal' in page.locator('#order-content').inner_text()
                page.locator('#refresh-order').click();page.locator('#report-issue').wait_for();assert 'fixture-order' in page.locator('#order-content').inner_text()
                results[f'storage_blocked_request_access_{width}']=True
                page.locator('#report-issue').click();page.locator('#issue-description').fill('Fixture support request');page.locator('#send-issue').dblclick()
                page.wait_for_function('()=>document.querySelector("#send-issue").disabled')
                assert len(state['case_calls'])==1
                state['pending'].fulfill(status=503,json={'detail':'Fixture lost acknowledgment'})
                page.get_by_text('Fixture lost acknowledgment',exact=True).wait_for();page.locator('#send-issue').click()
                page.get_by_text('Support request recorded. Reference: case-fixture',exact=True).wait_for()
                assert len(state['cases'])==1 and len(state['case_calls'])==2
                assert len(set(state['case_calls']))==1 and state['case_calls'][0].startswith('support-')
                results[f'support_submit_retry_{width}']=True
                state['order']['state']='deposit_processing';page.locator('#refresh-order').click()
                page.get_by_role('heading',name='Deposit processing (bank debit pending)').wait_for();page.locator('#cancel-order').click()
                page.get_by_role('heading',name='Request cancelled').wait_for();results[f'pending_deposit_cancel_{width}']=True
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                # A delayed response must never replace a different recovered request.
                second={**state['order'],'id':'fixture-second','state':'requested'}
                page.route('**/api/orders/fixture-second',lambda r:r.fulfill(json=second))
                page.route('**/api/orders/fixture-second/cases',lambda r:r.fulfill(json={'items':[]}))
                delayed=[];page.route('**/api/orders/fixture-order',lambda r:delayed.append(r))
                with page.expect_request(lambda r:r.url.endswith('/api/orders/fixture-order')):
                    page.locator('#refresh-order').click()
                page.locator('#switch-order').click();page.locator('#recover-id').fill('fixture-second');page.locator('#recover-token').fill('second-access');page.locator('#recover-form button.primary').click()
                page.get_by_text('Request fixture-second',exact=True).wait_for()
                assert len(delayed)==1;delayed[0].fulfill(json=state['order']);page.wait_for_load_state('networkidle')
                assert 'Request fixture-second' in page.locator('#order-content').inner_text()
                page.unroute('**/api/orders/fixture-order');state['order']['state']='requested'
                page.locator('#switch-order').click();page.locator('#recover-id').fill('fixture-order');page.locator('#recover-token').fill('fixture-access');page.locator('#recover-form button.primary').click();page.locator('#order-payment-pref').wait_for()
                pending_preference=[];page.route('**/api/orders/fixture-order/payment-preference',lambda r:pending_preference.append(r))
                with page.expect_request(lambda r:r.url.endswith('/payment-preference')):
                    page.select_option('#order-payment-pref','partner_financing')
                page.locator('#switch-order').click();page.locator('#recover-id').fill('fixture-second');page.locator('#recover-token').fill('second-access');page.locator('#recover-form button.primary').click();page.get_by_text('Request fixture-second',exact=True).wait_for()
                assert len(pending_preference)==1;pending_preference[0].fulfill(json={**state['order'],'payment_preference':'partner_financing'});page.wait_for_load_state('networkidle')
                assert 'Request fixture-second' in page.locator('#order-content').inner_text()
                results[f'late_order_responses_keep_current_request_{width}']=True
                context.close()
            assert not errors,errors
            browser.close()
    finally:server.shutdown();server.server_close()
    print(json.dumps({'fake_provider':True,'checks':results,'javascript_errors':errors}))

if __name__=='__main__':main()
