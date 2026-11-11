"""Desktop/mobile checkout UI fixtures. No Stripe API or payment calls."""
import functools,json,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from static_browser_smoke import PagesHandler

ROOT=Path(__file__).resolve().parents[1]
SVG='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>'


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(PagesHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    item=next(x for x in json.loads((ROOT/'inventory.json').read_text())['items'] if x.get('curated') and x.get('photo'))
    quote=dict(vehicle_price_cents=2900000,tax_cents=181250,title_registration_cents=15000,
        documentation_cents=0,delivery_charge_cents=60000,total_cents=3156250,valid_until=4102444800,
        seller={'legal_name':'FIXTURE RETAIL SELLER','license_number':'FIXTURE','address':'TEST ADDRESS'},
        terms={'deposit_terms_reference':'https://example.test/terms'})
    checks=[];errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (1440,390):
                for mode in ('platform','dealer_direct'):
                    order={'id':'fixture-order','stock_id':item['stock_id'],'masked_vin':item['masked_vin'],'state':'quoted','quote_version':1,
                           'quote':quote,'online_actions':[],'deposit_collection_mode':mode,
                           'deposit_collector_legal_name':'JENNI PRO INC' if mode=='platform' else 'FIXTURE RETAIL SELLER'}
                    calls=[]
                    context=browser.new_context(viewport={'width':width,'height':1000})
                    def route(r):
                        url=r.request.url
                        if r.request.resource_type=='image':return r.fulfill(content_type='image/svg+xml',body=SVG)
                        if '/api/' in url:
                            path=url.split('/api/')[1]
                            if path=='config':return r.fulfill(json={'requests_enabled':True,'payments_enabled':True})
                            if path=='orders/fixture-order':return r.fulfill(json=order)
                            if path=='orders/fixture-order/checkout':
                                calls.append(r.request.post_data_json)
                                assert r.request.headers['authorization']=='Bearer fixture-access'
                                return r.fulfill(json={'mode':'embedded_page','publishable_key':'pk_test_fixture',
                                    'account':None if mode=='platform' else 'acct_fixtureSeller','client_secret':'fixture_secret'})
                            return r.fulfill(status=404,json={'detail':'Fixture endpoint unavailable'})
                        if 'js.stripe.com' in url:
                            return r.fulfill(content_type='application/javascript',body='''window.Stripe=(...args)=>{window.fixtureStripeArgs=args;return {createEmbeddedCheckoutPage:async options=>{window.fixtureSecret=await options.fetchClientSecret();return {mount:s=>{document.querySelector(s).textContent='FIXTURE PAYMENT FORM'},destroy:()=>{}}}}}''')
                        if 'inventory.json' in url:return r.fulfill(json={'meta':{},'items':[item]})
                        if '/media/' in url:return r.fulfill(json={})
                        if r.request.resource_type=='image':return r.fulfill(content_type='image/svg+xml',body=SVG)
                        if url.startswith(base):return r.continue_()
                        return r.abort()
                    context.route('**/*',route)
                    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(base);page.wait_for_selector('.card')
                    page.evaluate('sessionStorage.setItem("marketplace_order",JSON.stringify({id:"fixture-order",token:"fixture-access"}))')
                    page.locator('#order-button').click();page.locator('#order-dialog[open]').wait_for()
                    assert 'FIXTURE RETAIL SELLER' in page.locator('#order-quote').inner_text()
                    assert page.locator('#pay-deposit').inner_text()=='Reserve for $250'
                    if mode=='platform':
                        assert 'JENNI PRO INC' in page.locator('#deposit-collector').inner_text()
                        assert 'Your reservation payment provider is' in page.locator('#deposit-collector').inner_text()
                        assert 'accepted terms explain collection and release.' in page.locator('#deposit-collector').inner_text()
                    else:assert page.locator('#deposit-collector').count()==0
                    page.locator('#pay-deposit').click();assert not calls
                    page.locator('#accept-quote').check();page.locator('#pay-deposit').click()
                    page.get_by_text('FIXTURE PAYMENT FORM').wait_for()
                    args=page.evaluate('window.fixtureStripeArgs')
                    assert args==(['pk_test_fixture'] if mode=='platform' else ['pk_test_fixture',{'stripeAccount':'acct_fixtureSeller'}]),args
                    assert calls==[{'quote_version':1,'terms_accepted':True}]
                    assert page.evaluate('window.fixtureSecret')=='fixture_secret'
                    assert page.url==base and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    checks.append({'width':width,'mode':mode,'seller_disclosed':True,'acceptance_required':True,'sdk_scope_correct':True})
                    context.close()
            assert not errors,errors
            browser.close()
    finally:server.shutdown();server.server_close()
    print(json.dumps({'fixture_only':True,'no_provider_calls':True,'checks':checks,'javascript_errors':errors}))

if __name__=='__main__':main()
