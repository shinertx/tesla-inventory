"""Exercise branded checkout with an explicit fake provider; never sends money."""
import functools,json,threading,sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from static_browser_smoke import PagesHandler
ROOT=Path(__file__).resolve().parents[1]

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(PagesHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    quote=dict(vehicle_price_cents=2900000,tax_cents=181250,title_registration_cents=15000,documentation_cents=0,delivery_charge_cents=60000,total_cents=3156250,valid_until=4102444800,seller={'legal_name':'FIXTURE SELLING DEALER','license_number':'FIXTURE','address':'TEST ADDRESS'},terms={'deposit_terms_reference':'https://example.test/terms'})
    order={'id':'fixture-order','vin':'5YJ3E1EA8SF921313','state':'quoted','quote_version':1,'quote':quote,'online_actions':[]}
    calls=[]
    def api(route):
        path=route.request.url.split('/api/')[1]
        if path=='config':return route.fulfill(json={'requests_enabled':True,'payments_enabled':True})
        if path=='orders/fixture-order/checkout':
            calls.append(route.request.post_data_json)
            assert route.request.headers['authorization']=='Bearer fixture-access'
            return route.fulfill(json={'mode':'embedded_page','publishable_key':'pk_test_fixture','account':'acct_fixtureDealer','client_secret':'fixture_secret'})
        if path=='orders/fixture-order':return route.fulfill(json=order)
        return route.fulfill(status=404,json={'detail':'Fixture endpoint unavailable'})
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (1440,390):
                page=browser.new_page(viewport={'width':width,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/api/**',api)
                page.route('https://js.stripe.com/endive/stripe.js',lambda route:route.fulfill(content_type='application/javascript',body='''window.Stripe=(key,account)=>{window.fixtureStripe={key,account};return {createEmbeddedCheckoutPage:async options=>{window.fixtureCreateCount=(window.fixtureCreateCount||0)+1;window.fixtureStripe.secret=await options.fetchClientSecret();window.fixtureComplete=options.onComplete;return {mount:selector=>{document.querySelector(selector).textContent='FIXTURE SECURE PAYMENT FORM'},destroy:()=>{window.fixtureDestroyed=true}}}}}'''))
                page.goto(base);page.wait_for_selector('.card')
                page.evaluate('sessionStorage.setItem("marketplace_order",JSON.stringify({id:"fixture-order",token:"fixture-access"}))')
                page.locator('#order-button').click();page.locator('#order-dialog[open]').wait_for()
                assert 'FIXTURE SELLING DEALER' in page.locator('#order-content').inner_text()
                assert '-$250.00' in page.locator('#order-content').inner_text()
                assert '$31,312.50' in page.locator('#order-content').inner_text()
                page.locator('#pay-deposit').click();page.get_by_text('Review and accept the quote and linked terms first.').wait_for();assert not calls
                page.locator('#accept-quote').check();assert page.locator('#order-error').inner_text()==''
                page.locator('#pay-deposit').click();page.get_by_text('FIXTURE SECURE PAYMENT FORM').wait_for()
                assert page.url==base
                assert page.evaluate('window.fixtureStripe.account.stripeAccount')=='acct_fixtureDealer'
                assert page.evaluate('window.fixtureStripe.secret')=='fixture_secret'
                assert 'fixture_secret' not in page.evaluate('JSON.stringify({...localStorage,...sessionStorage})')
                order['state']='checkout_pending'
                page.evaluate('window.fixtureComplete()');page.get_by_text('Secure checkout opened',exact=True).wait_for()
                assert page.evaluate('window.fixtureDestroyed')
                assert 'Deposit verified' not in page.locator('#order-content').inner_text()
                assert not errors
                order['state']='quoted';page.locator('#refresh-order').click();page.locator('#accept-quote').wait_for();page.locator('#accept-quote').check()
                pending=[];page.route('**/api/orders/fixture-order/checkout',lambda r:pending.append(r))
                with page.expect_request(lambda r:r.url.endswith('/checkout')):page.locator('#pay-deposit').click()
                page.locator('[data-close=order-dialog]').click()
                assert len(pending)==1;pending[0].fulfill(json={'mode':'embedded_page','publishable_key':'pk_test_fixture','account':'acct_fixtureDealer','client_secret':'fixture_stale_secret'})
                page.wait_for_load_state('networkidle');assert page.evaluate('window.fixtureCreateCount')==1
                assert not page.locator('#order-dialog').evaluate('(x)=>x.open')
                assert not errors;page.close();calls.clear();order['state']='quoted'
            browser.close()
    finally:server.shutdown();server.server_close()
    print(json.dumps({'fake_provider':True,'desktop_and_mobile_embedded':True,'no_redirect':True,'seller_disclosed':True,'acceptance_required':True,'client_callback_cannot_mark_paid':True,'late_checkout_cannot_mount_after_close':True}))
if __name__=='__main__':main()
