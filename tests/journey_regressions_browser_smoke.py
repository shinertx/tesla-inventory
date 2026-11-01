"""Focused local-fixture journey regressions; no real providers or payments."""
import functools
import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright
from static_browser_smoke import PagesHandler
from storefront_controls_browser_smoke import fixtures, SVG

ROOT = Path(__file__).resolve().parents[1]


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(PagesHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    rows = [dict(row, factory='Austin' if i == 1 else 'Fremont', city='Wahoo', state='NE')
            for i, row in enumerate(fixtures()[:4])]
    quote = dict(vehicle_price_cents=2900000, tax_cents=181250, title_registration_cents=15000,
                 documentation_cents=0, delivery_charge_cents=60000, total_cents=3156250,
                 deposit_cents=25000, balance_after_deposit_cents=3131250, valid_until=4102444800,
                 seller={'legal_name': 'FIXTURE RETAIL SELLER', 'license_number': 'FIXTURE', 'address': 'FIXTURE ADDRESS'},
                 terms={'deposit_terms_reference': 'https://fixture.invalid/terms'})
    order = {'id': 'journey-fixture-order', 'vin': rows[0]['vin'], 'state': 'requested',
             'payment_preference': 'partner_financing', 'quote_version': 0, 'quote': None,
             'financing': {'state': 'not_requested'}, 'transport': {'state': 'unquoted'},
             'balance_payment_state': 'unpaid', 'online_actions': []}
    results = {'local_fixtures': True, 'real_payments': False, 'real_providers': False, 'viewports': {}, 'javascript_errors': []}

    def route(r):
        url = r.request.url
        if 'inventory.json' in url: return r.fulfill(json={'meta': {}, 'items': rows})
        if '/media/' in url: return r.fulfill(json={row['vin']: [{'url': row['photo'], 'category': 'photos'}] for row in rows})
        if '/api/' in url:
            path = url.split('/api/', 1)[1]
            if path == 'config': return r.fulfill(json={'requests_enabled': True, 'payments_enabled': True})
            if path == 'orders/journey-fixture-order':
                assert r.request.headers.get('authorization') == 'Bearer journey-fixture-access'
                return r.fulfill(json=order)
            if path == 'orders/journey-fixture-order/cases': return r.fulfill(json={'items': []})
            raise AssertionError('Unexpected fixture API operation: ' + path)
        if r.request.resource_type == 'image': return r.fulfill(content_type='image/svg+xml', body=SVG)
        if url.startswith(base): return r.continue_()
        return r.abort()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 844})
                context.route('**/*', route)
                context.add_init_script('localStorage.setItem("marketplace_saved",' + json.dumps(json.dumps([x['vin'] for x in rows])) + ')')
                page = context.new_page()
                page.on('pageerror', lambda error: results['javascript_errors'].append(str(error)))
                page.goto(base); page.wait_for_selector('.card')
                for i, row in enumerate(rows):
                    assert f'Built in {row["factory"]}' in page.locator(f'.card[data-vin="{row["vin"]}"] .card-specs').inner_text()
                page.locator(f'[data-open="{rows[0]["vin"]}"]').first.click()
                detail = page.locator('#vehicle-panel').inner_text()
                assert 'Build factory' in detail and 'Fremont' in detail
                assert 'Vehicle location' in detail and 'Wahoo' in detail and 'NE' in detail
                page.locator('[data-close=vehicle-dialog]').click()
                page.locator('#saved-button').click()
                choices = page.locator('[data-compare-select]')
                assert choices.count() == 4 and page.locator('[data-compare-select]:checked').count() == 0
                assert page.locator('#compare-saved').is_disabled()
                choices.nth(0).check(); assert page.locator('#compare-saved').is_disabled()
                choices.nth(1).check(); assert page.locator('#compare-saved').is_enabled()
                choices.nth(2).check(); assert choices.nth(3).is_disabled() and not choices.nth(3).is_checked()
                assert page.locator('[data-compare-select]:checked').count() == 3
                choices.nth(0).uncheck(); choices.nth(3).check()
                selected = [rows[i]['vin'] for i in (1, 2, 3)]
                assert choices.nth(0).is_disabled()
                page.locator('#compare-saved').click()
                assert page.locator('[data-compare-open]').count() == 3
                assert set(page.locator('[data-compare-open]').evaluate_all('(xs)=>xs.map(x=>x.dataset.compareOpen)')) == set(selected)
                assert page.locator(f'[data-compare-open="{rows[0]["vin"]}"]').count() == 0
                page.locator('[data-close=compare-dialog]').click()
                page.evaluate('sessionStorage.setItem("marketplace_order",JSON.stringify({id:"journey-fixture-order",token:"journey-fixture-access"}))')
                page.locator('#order-button').click(); page.locator('#order-next-step').wait_for()
                # A preference alone must not look like a lender application or approval.
                note = page.locator('#order-payment-preference-note').inner_text().lower()
                assert 'financ' in note and ('not' in note or 'separate' in note) and 'application' in note
                assert not page.get_by_text('Application submitted to partner lender', exact=True).count()
                assert not page.locator('#order-amount-due').count()

                now=int(time.time())
                order['shipping_estimate']={'provider':'Super Dispatch','customer_estimate_cents':75029,'observed_at':now,'cache_expires_at':now+2,'binding':False,'carrier_booked':False}
                page.locator('#refresh-order').click()
                page.locator('#provider-shipping-estimate').wait_for(state='visible')
                assert '$750.29' in page.locator('#provider-shipping-estimate').inner_text()
                assert 'No carrier is booked' in page.locator('#provider-shipping-estimate').inner_text()
                assert '550.29' not in page.locator('#provider-shipping-estimate').inner_text()
                page.locator('#provider-shipping-estimate').wait_for(state='detached',timeout=3500)
                # An expired recommendation remains hidden even when returned by a stale fixture API.
                page.locator('#refresh-order').click()
                assert not page.locator('#provider-shipping-estimate').count()
                order.pop('shipping_estimate')

                assert page.locator('#order-next-step').evaluate('(el)=>!!(el.compareDocumentPosition(document.querySelector("#order-access"))&Node.DOCUMENT_POSITION_FOLLOWING)')
                order.update(state='deposit_paid',quote=quote,quote_version=1,payment_preference='partner_financing',financing={'state':'application_ready','provider':'Fixture lender','application_url':'https://fixture.invalid/apply','approved_amount_cents':0,'funded_amount_cents':0})
                page.locator('#refresh-order').click()
                page.get_by_role('heading',name='Deposit verified',exact=True).wait_for()
                assert 'lender application is ready' in page.locator('#order-next-step').inner_text()
                assert page.locator('#order-next-step a').get_attribute('href')=='https://fixture.invalid/apply'
                assert 'No application has been submitted' in page.locator('#order-payment-preference-note').inner_text()
                assert 'not a credit approval' in page.locator('#order-payment-preference-note').inner_text()
                order['financing']={'state':'not_requested'}
                for phase in ('quoted', 'deposit_paid', 'dealer_confirmed', 'in_transit', 'completed'):
                    order.update(state=phase, quote=quote, quote_version=1, payment_preference='cash')
                    order['balance_payment_state'] = 'paid' if phase in ('in_transit', 'completed') else 'unpaid'
                    page.locator('#refresh-order').click()
                    page.get_by_role('heading', name={
                        'quoted': 'Your final price is ready', 'deposit_paid': 'Deposit verified',
                        'dealer_confirmed': 'Dealer accepted your purchase', 'in_transit': 'Carrier has the vehicle',
                        'completed': 'Purchase complete'}[phase], exact=True).wait_for()
                    assert page.locator('#order-next-step').evaluate('(el)=>!!(el.compareDocumentPosition(document.querySelector("#order-access"))&Node.DOCUMENT_POSITION_FOLLOWING)')
                    assert page.locator('#order-payment-summary').is_visible()
                    due = page.locator('#order-amount-due').inner_text()
                    if phase in ('in_transit', 'completed'): assert '$0.00' in due
                    elif phase == 'quoted':
                        assert '$250.00' in due
                        page.locator('#review-order-quote').click(); page.locator('#accept-quote').wait_for(state='visible')
                        assert page.locator('#order-quote').is_visible()
                    elif phase == 'dealer_confirmed':
                        assert '$31,312.50' in due
                        page.locator('#review-balance').click(); page.locator('#order-balance').wait_for(state='visible')
                page.locator('[data-close=order-dialog]').click()
                context.close()
                order.update(state='requested', quote=None, quote_version=0, payment_preference='partner_financing', balance_payment_state='unpaid')
                results['viewports'][str(width)] = {'factory_and_vehicle_location_distinct': True,
                    'explicit_two_to_three_comparison': True, 'fourth_choice_not_silently_omitted': True,
                    'next_steps_above_account_controls': True, 'finance_preference_not_application': True,
                    'customer_shipping_estimate_expires': True, 'hosted_financing_ready_not_approval': True,
                    'settled_balance_current_due_zero': True, 'review_buttons_open_correct_section': True}
            assert not results['javascript_errors'], results['javascript_errors']
            browser.close()
    finally:
        server.shutdown(); server.server_close()
    print(json.dumps(results, indent=2))


if __name__ == '__main__': main()
