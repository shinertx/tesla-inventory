"""Desktop/mobile browser journey through real local handlers and a fake card provider."""
import functools
import json
import sys
import tempfile
import threading
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.main import create_app
from app.catalog import stock_id_for
from test_transactions import setup,approve,auth,admin,VIN
from test_manual_authorizations import ManualPayments,authorize
from static_browser_smoke import PagesHandler

SVG='<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600"><rect width="900" height="600" fill="#dde7ed"/></svg>'
SDK="""window.Stripe=()=>({createEmbeddedCheckoutPage:async options=>{
  window.fixtureStripeCreates=(window.fixtureStripeCreates||0)+1;
  await options.fetchClientSecret();await new Promise(resolve=>setTimeout(resolve,window.fixtureStripeDelay||0));
  if(window.fixtureStripeFailOnce){window.fixtureStripeFailOnce=false;throw new Error('FIXTURE secure form initialization failed');}
  let button;return {
    mount:selector=>{window.fixtureStripeMounts=(window.fixtureStripeMounts||0)+1;button=document.createElement('button');button.id='fixture-authorize';button.textContent='FIXTURE: authorize test card';button.onclick=()=>options.onComplete();document.querySelector(selector).append(button)},
    destroy:()=>{window.fixtureStripeDestroys=(window.fixtureStripeDestroys||0)+1;button?.remove();}
  };
}});"""


def main():
    output=ROOT.parents[1]/'outputs/volts-purchase-flow/manual-browser'
    output.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(PagesHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    base=origin+'/tesla-inventory/'
    result={'real_local_handlers':True,'provider':'fake','actual_money_moved':False,'checks':[],'javascript_errors':[]}
    try:
        with tempfile.TemporaryDirectory() as tmp,sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            for width in (1440,390):
                folder=Path(tmp)/str(width);folder.mkdir()
                _,settings,_,store=setup.__wrapped__(folder)
                settings.inventory_path.write_text(json.dumps({'meta':{},'items':[{
                    'vin':VIN,'year':2024,'model':'Model Y','trim':'FIXTURE Long Range',
                    'mileage':20000,'display_price':29000,'city':'Fixture City','state':'TX',
                    'location_center':[0,0],'photo':'https://fixture.invalid/car.jpg','photo_count':1,
                    'reservable':False,'title_status':'unverified'}]}))
                with store.transaction() as connection:
                    profile=json.loads(connection.execute('SELECT profile FROM dealers').fetchone()[0])
                    profile['online_portal_hosts']=['finance.example.test']
                    connection.execute('UPDATE dealers SET profile=?',(json.dumps(profile),))
                payments=ManualPayments()
                settings=replace(settings,origin=origin,deposit_capture_method='manual',auto_refund_enabled=True)
                client=TestClient(create_app(settings,payments))
                for scenario in ('release','capture_refund'):
                    context=browser.new_context(viewport={'width':width,'height':900},accept_downloads=True)
                    def route(r):
                        url=r.request.url
                        if '/api/' in url:
                            path='/api/'+urlsplit(url).path.split('/api/',1)[1]
                            response=client.request(r.request.method,path,content=r.request.post_data_buffer,
                                headers={k:v for k,v in r.request.headers.items() if k.lower() in ('authorization','content-type','idempotency-key','origin')})
                            return r.fulfill(status=response.status_code,body=response.content,
                                headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-encoding')})
                        if 'inventory.json' in url:
                            return r.fulfill(json=client.get('/inventory.json').json())
                        if '/data/us_zip_centers.json' in url:return r.fulfill(json={'zips':{'78201':['TX',0,0]}})
                        if url.startswith('https://js.stripe.com/'):return r.fulfill(content_type='application/javascript',body=SDK)
                        if url.startswith('https://finance.example.test/'):
                            return r.fulfill(content_type='text/html',body='<h1>FIXTURE secure lender application</h1>')
                        if r.request.resource_type=='image':return r.fulfill(content_type='image/svg+xml',body=SVG)
                        if url.startswith(origin):return r.continue_()
                        return r.abort()
                    context.route('**/*',route)
                    page=context.new_page();page.on('pageerror',lambda error:result['javascript_errors'].append(str(error)))
                    page.goto(base);page.locator('[data-price]').click();page.locator('#deal-zip').fill('78201')
                    page.locator('#deal-continue').click()
                    page.locator('[name=name]').fill('Fixture Buyer');page.locator('[name=email]').fill('fixture@example.test')
                    page.locator('[name=phone]').fill('2105550100');page.locator('[name=consent]').check()
                    page.locator('#submit-request').click();page.locator('#order-dialog[open]').wait_for()
                    access=page.evaluate('JSON.parse(sessionStorage.getItem("marketplace_order"))')
                    order={'id':access['id'],'access_token':access['token']}
                    assert VIN not in page.locator('#order-content').inner_text()
                    assert stock_id_for(VIN) in page.locator('#order-content').inner_text()
                    approve(client,order)
                    page.locator('#refresh-order').click();page.locator('#pay-deposit').wait_for()
                    assert 'card hold' in page.locator('#pay-deposit').inner_text()
                    delayed=width==1440 and scenario=='release'
                    if delayed:page.evaluate('window.fixtureStripeDelay=4600')
                    if width==390 and scenario=='release':page.evaluate('window.fixtureStripeFailOnce=true')
                    page.locator('#accept-quote').check();page.locator('#pay-deposit').click()
                    if width==390 and scenario=='release':
                        page.get_by_text('FIXTURE secure form initialization failed',exact=True).wait_for()
                        assert page.locator('#pay-deposit').is_enabled()
                        page.locator('#pay-deposit').click()
                        result['checks'].append({'sdk_failure_recoverable':True,'width':width})
                    page.locator('#fixture-authorize').wait_for(timeout=10000)
                    if delayed:
                        assert page.locator('#accept-quote').is_checked()
                        assert page.locator('#pay-deposit').is_disabled()
                        assert page.evaluate('window.fixtureStripeCreates===1&&window.fixtureStripeMounts===1')
                        result['checks'].append({'delayed_sdk_survives_order_poll':True,'delay_ms':4600})
                        # A second slow mount is closed before resolution. Its late result must be destroyed.
                        page.locator('[data-close="order-dialog"]').click()
                        page.locator('#order-button').click();page.locator('#pay-deposit').wait_for()
                        page.locator('#accept-quote').check();page.locator('#pay-deposit').click()
                        page.wait_for_function('window.fixtureStripeCreates===2')
                        page.locator('[data-close="order-dialog"]').click()
                        page.wait_for_function('window.fixtureStripeDestroys===2',timeout=10000)
                        assert page.locator('#fixture-authorize').count()==0
                        page.evaluate('window.fixtureStripeDelay=0')
                        page.locator('#order-button').click();page.locator('#pay-deposit').wait_for()
                        page.locator('#accept-quote').check();page.locator('#pay-deposit').click()
                        page.locator('#fixture-authorize').wait_for()
                        assert payments.session_calls==1
                        result['checks'].append({'closed_view_rejects_late_sdk_mount':True,'same_checkout_reused':True})
                    assert authorize(client,payments,order).status_code==200
                    page.locator('#fixture-authorize').click();page.locator('#purchase-payment-paths').wait_for()
                    state=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
                    assert state['state']=='deposit_authorized' and state['deposit_captured_cents']==0
                    assert state['funding_summary']['credited_deposit_cents']==0
                    assert state['funding_summary']['remaining_cents']==3156250
                    assert VIN in page.locator('#order-content').inner_text()
                    with page.expect_download() as download:
                        page.locator('#download-buyers-order').click()
                    document=Path(download.value.path()).read_text()
                    assert VIN in document and 'FIXTURE FULFILLING DEALER' in document and '31,562.50' in document
                    finance=client.post('/api/admin/orders/'+order['id']+'/financing',headers=admin(),json={
                        'state':'application_ready','provider':'FIXTURE lender','reference':'fixture:application',
                        'application_url':'https://finance.example.test/application'})
                    assert finance.status_code==200,finance.text
                    page.locator('#refresh-order').click();page.locator('#continue-financing').wait_for()
                    with context.expect_page() as popup:
                        page.locator('#continue-financing').click()
                    popup.value.get_by_role('heading',name='FIXTURE secure lender application').wait_for()
                    assert popup.value.evaluate('window.opener===null')
                    popup.value.close()
                    if scenario=='capture_refund':
                        page.locator('#capture-deposit').click()
                        assert 'Accept the deposit collection terms first.' in page.locator('#order-error').inner_text()
                        page.locator('#accept-deposit-capture').check();page.locator('#capture-deposit').click()
                        page.get_by_role('heading',name='Deposit verified',exact=True).wait_for()
                        state=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
                        assert state['funding_summary']['credited_deposit_cents']==25000
                        assert state['funding_summary']['remaining_cents']==3131250
                    page.screenshot(path=str(output/f'{width}-{scenario}.png'))
                    page.locator('#cancel-order').click()
                    page.get_by_role('heading',name='Deposit refunded' if scenario=='capture_refund' else 'Request cancelled',exact=True).wait_for()
                    state=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
                    assert state['funding_summary']['credited_deposit_cents']==0
                    if scenario=='release':assert state['deposit_status']=='released'
                    else:assert state['deposit_status']=='refunded'
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    result['checks'].append({'width':width,'scenario':scenario,'buyer_order':True,
                        'secure_lender_link':True,'hold_credit_zero':True,'final_state':state['state']})
                    context.close()
                assert payments.capture_calls==payments.refunds==1 and payments.release_calls==1
            assert not result['javascript_errors'],result['javascript_errors']
            browser.close()
    finally:server.shutdown();server.server_close()
    (output/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':main()
