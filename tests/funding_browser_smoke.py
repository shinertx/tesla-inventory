"""Customer funding receipts, reversals and duplicate-payment controls.

Local HTTP fixtures only. No bank, lender, carrier or payment provider calls.
"""
import functools
import json
import threading
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
    row = fixtures()[0]
    quote = dict(vehicle_price_cents=2900000, tax_cents=181250, title_registration_cents=15000,
                 documentation_cents=0, delivery_charge_cents=60000, total_cents=3156250,
                 deposit_cents=25000, balance_after_deposit_cents=3131250, valid_until=4102444800,
                 seller={'legal_name': 'FIXTURE SELLER', 'license_number': 'FIXTURE', 'address': 'FIXTURE ADDRESS'},
                 terms={})
    order = {'id': 'funding-fixture', 'vin': row['vin'], 'state': 'dealer_confirmed',
             'quote_version': 1, 'quote': quote, 'payment_preference': 'partner_financing',
             'balance_payment_state': 'unpaid', 'financing': {'state': 'lender_funded',
             'provider': 'Fixture lender', 'funded_amount_cents': 2800000},
             'transport': {'state': 'unquoted'}, 'online_actions': []}
    summary = {'currency': 'USD', 'quote_version': 1, 'quote_total_cents': 3156250,
               'credited_deposit_cents': 25000, 'lender_funded_cents': 2800000,
               'settled_balance_cents': 0, 'net_additional_cash_cents': 331250,
               'prior_quote_unallocated_cash_cents': 0, 'prior_quote_unallocated_lender_cents': 0, 'remaining_cents': 0,
               'overpaid_cents': 0, 'coverage_complete': True,
               'funds_review_required': False, 'balance_checkout_allowed': False}
    order['funding_summary'] = dict(summary)
    results = {'local_fixtures': True, 'provider_calls': False, 'financial_actions': False,
               'viewports': {}, 'javascript_errors': []}

    def route(r):
        url = r.request.url
        if 'inventory.json' in url:
            return r.fulfill(json={'meta': {}, 'items': [row]})
        if '/media/' in url:
            return r.fulfill(json={row['vin']: [{'url': row['photo'], 'category': 'photos'}]})
        if '/api/' in url:
            path = url.split('/api/', 1)[1]
            if path == 'config':
                return r.fulfill(json={'requests_enabled': True, 'payments_enabled': True})
            if path == 'orders/funding-fixture':
                assert r.request.method == 'GET'
                assert r.request.headers.get('authorization') == 'Bearer fixture-access'
                return r.fulfill(json=order)
            if path == 'orders/funding-fixture/cases':
                return r.fulfill(json={'items': []})
            raise AssertionError('Unexpected fixture operation: ' + path)
        if r.request.resource_type == 'image':
            return r.fulfill(content_type='image/svg+xml', body=SVG)
        if url.startswith(base):
            return r.continue_()
        return r.abort()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in (1440, 390):
                order.update(state='dealer_confirmed', payment_preference='partner_financing',
                             funding_summary=dict(summary), online_actions=[],
                             financing={'state':'lender_funded','provider':'Fixture lender','funded_amount_cents':2800000})
                context = browser.new_context(viewport={'width': width, 'height': 844})
                context.route('**/*', route)
                context.add_init_script('sessionStorage.setItem("marketplace_order",JSON.stringify({id:"funding-fixture",token:"fixture-access"}))')
                page = context.new_page()
                page.on('pageerror', lambda error: results['javascript_errors'].append(str(error)))
                page.goto(base); page.wait_for_selector('.card')
                page.locator('#order-button').click()
                page.locator('#order-funding').wait_for()
                funding = page.locator('#order-funding').inner_text()
                assert '$28,000.00' in funding and '$3,312.50' in funding and '$250.00' in funding
                assert page.locator('#order-amount-due').inner_text() == '$0.00'
                assert not page.locator('#pay-balance').count()
                assert 'Recorded settled funds cover' in page.locator('#order-payment-summary').inner_text()

                # Observed cash reversal creates a real funding shortfall.
                order['funding_summary'] = dict(summary, net_additional_cash_cents=231250,
                    remaining_cents=100000, coverage_complete=False)
                page.locator('#refresh-order').click()
                page.locator('#order-amount-due').filter(has_text='$1,000.00').wait_for()
                assert '$1,000.00 remains' in page.locator('#order-status-message').inner_text()
                assert not page.locator('#pay-balance').count()
                assert 'cover your purchase' not in page.locator('#order-payment-summary').inner_text()

                # A preference change cannot revive a stale full-balance portal.
                order['payment_preference'] = 'cash'
                order['online_actions'] = [{'kind': 'pay_balance', 'url': 'https://fixture.invalid/old-full-balance'}]
                page.locator('#refresh-order').click()
                page.wait_for_function('()=>document.querySelector("#order-payment-pref")?.value==="cash"')
                assert not page.locator('#pay-balance').count()
                assert not page.locator('#review-balance').count()
                assert not page.locator('a[href="https://fixture.invalid/old-full-balance"]').count()

                # Excess cash and prior-quote cash require review, not another payment.
                order['funding_summary'] = dict(summary, net_additional_cash_cents=331350,
                    overpaid_cents=100, funds_review_required=True)
                page.locator('#refresh-order').click()
                page.get_by_text('Excess funds to reconcile', exact=True).wait_for()
                assert '$1.00 more' in page.locator('#order-funding').inner_text()
                assert 'does not send a refund' in page.locator('#order-funding').inner_text()
                assert not page.locator('#pay-balance').count()

                order['funding_summary'] = dict(summary, net_additional_cash_cents=0,
                    prior_quote_unallocated_cash_cents=331250, remaining_cents=331250,
                    coverage_complete=False, funds_review_required=True)
                page.locator('#refresh-order').click()
                page.get_by_text('Unallocated funds to reconcile', exact=True).wait_for()
                assert 'earlier quote or seller' in page.locator('#order-funding').inner_text()
                assert not page.locator('#pay-balance').count()

                # Malformed or mismatched summaries never restore payment controls.
                for invalid in (dict(summary, currency='EUR'), dict(summary, quote_version=2),
                                dict(summary, coverage_complete='true'), dict(summary, remaining_cents=-1),
                                dict(summary, remaining_cents=100), dict(summary, coverage_complete=False, remaining_cents=100, overpaid_cents=100)):
                    order['funding_summary'] = invalid
                    page.locator('#refresh-order').click()
                    page.locator('#order-funding-unavailable').wait_for()
                    assert not page.locator('#pay-balance').count()
                    assert page.locator('#order-amount-due').inner_text() == 'Review required'

                # Review flags override a contradictory positive payment permission.
                order['funding_summary'] = dict(summary, lender_funded_cents=0,
                    net_additional_cash_cents=100000, remaining_cents=3031250,
                    coverage_complete=False, funds_review_required=True, balance_checkout_allowed=True)
                page.locator('#refresh-order').click()
                page.get_by_text('Funding under review', exact=True).wait_for()
                assert not page.locator('#pay-balance').count()
                assert not page.locator('#review-balance').count()

                # An observed lender correction can reduce net proceeds to zero.
                order['financing'] = {'state': 'funding_reconciled', 'provider': 'Fixture lender', 'funded_amount_cents': 0}
                order['payment_preference'] = 'partner_financing'
                order['funding_summary'] = dict(summary, lender_funded_cents=0,
                    remaining_cents=2800000, coverage_complete=False, funds_review_required=True)
                page.locator('#refresh-order').click()
                page.get_by_text('Lender funds reconciled', exact=True).wait_for()
                assert '$28,000.00' in page.locator('#order-funding').inner_text()
                assert 'Lender payment confirmed' not in page.locator('#order-content').inner_text()
                assert not page.locator('#pay-balance').count()
                order['payment_preference'] = 'cash'

                # The original deposit-only cash path still has its existing action.
                order['online_actions'] = []
                order['financing'] = {'state': 'not_requested'}
                order['funding_summary'] = dict(summary, lender_funded_cents=0,
                    net_additional_cash_cents=0, remaining_cents=3131250,
                    coverage_complete=False, balance_checkout_allowed=True)
                page.locator('#refresh-order').click()
                page.locator('#review-balance').wait_for()
                page.locator('#review-balance').click()
                page.locator('#pay-balance').wait_for(state='visible')
                assert '$31,312.50' in page.locator('#order-balance').inner_text()
                assert page.locator('#order-funding').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')

                # Closed records remain readable without a collection action.
                order.update(state='cancelled', funding_summary=dict(summary,
                    prior_quote_unallocated_cash_cents=331250, funds_review_required=True))
                page.locator('#refresh-order').click()
                page.get_by_role('heading', name='Request cancelled', exact=True).wait_for()
                assert not page.locator('#pay-balance').count()
                assert not page.locator('#pay-deposit').count()
                assert 'earlier quote or seller' in page.locator('#order-funding').inner_text()
                assert 'Remaining purchase balance' not in page.locator('#order-funding').inner_text()
                assert 'This purchase is closed' in page.locator('#order-funding').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                context.close()
                results['viewports'][str(width)] = {'mixed_funding': True, 'reversal_shortfall': True,
                    'stale_full_balance_hidden': True, 'overpayment_and_unallocated_review': True,
                    'invalid_summary_fails_closed': True, 'deposit_only_cash_path': True,
                    'closed_record_no_collection': True, 'review_flag_overrides_permission': True,
                    'zero_lender_correction': True}
            browser.close()
    finally:
        server.shutdown(); server.server_close()
    assert not results['javascript_errors'], results['javascript_errors']
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
