"""Bounded local fixtures for price, request, and private return UX.

No actual provider, payment, finance application, message, or customer data.
"""
import functools
import json
import re
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright
from static_browser_smoke import PagesHandler
from storefront_controls_browser_smoke import fixtures, SVG

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parents[1] / 'outputs' / 'simple-flow-browser-results.json'


def visible_button(page, selector):
    """Button stays inside the viewport and receives pointer input at its center."""
    page.locator(selector).wait_for(state='visible')
    assert page.locator(selector).evaluate('''(el)=>{
      const r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      return r.width>0&&r.height>0&&r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth&&(hit===el||el.contains(hit));
    }'''), selector


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(PagesHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    row = dict(fixtures()[0], city='Wahoo', state='NE', location_center=[0, 0],
               display_price=20000, reference_price=23000, hardware=None, reservable=False)
    order_id, token = 'simple-fixture-order', 'simple-fixture-private-token'
    order = {'id': order_id, 'vin': row['vin'], 'state': 'requested', 'quote_version': 0,
             'quote': None, 'payment_preference': 'cash', 'online_actions': []}
    state = {'malformed': False, 'posts': 0, 'reads': 0, 'visits': [], 'unexpected': [], 'hold_request': False, 'pending': []}
    results = {'local_fixtures': True, 'real_providers': False, 'real_payments': False, 'viewports': {}, 'javascript_errors': []}

    def route(r):
        url = r.request.url
        if 'inventory.json' in url:
            return r.fulfill(json={'meta': {'media_version': 'simple-fixture'}, 'items': [row]})
        if '/data/us_zip_centers.json' in url:
            return r.fulfill(json={'zips': {'78201': ['TX', 0, 0], '78701': ['TX', 0, 0]}})
        if '/media/' in url:
            return r.fulfill(json={row['vin']: [{'url': row['photo'], 'title': 'Fixture photo', 'category': 'photos'}]})
        if '/api/' in url:
            path = url.split('/api/', 1)[1]
            if path == 'config': return r.fulfill(json={'requests_enabled': True, 'payments_enabled': False})
            if path.startswith('visit'):
                state['visits'].append(r.request.post_data or '')
                return r.fulfill(json={'recorded': True})
            if path == 'requests':
                state['posts'] += 1
                if state['hold_request']:
                    state['pending'].append(r)
                    return
                if state['malformed']: return r.fulfill(content_type='application/json', body='{bad-json')
                return r.fulfill(status=201, json=dict(order, access_token=token))
            if path == f'orders/{order_id}':
                assert r.request.headers.get('authorization') == 'Bearer ' + token
                state['reads'] += 1
                return r.fulfill(json=order)
            if path == f'orders/{order_id}/cases': return r.fulfill(json={'items': []})
            if '/photos' in path: return r.fulfill(json={'photos': [{'url': row['photo'], 'category': 'photos'}]})
            state['unexpected'].append(path)
            return r.fulfill(status=404, json={'detail': 'Fixture route unavailable'})
        if r.request.resource_type == 'image': return r.fulfill(content_type='image/svg+xml', body=SVG)
        if url.startswith(base): return r.continue_()
        return r.abort()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 844}, permissions=['clipboard-read', 'clipboard-write'])
                context.route('**/*', route)
                context.add_init_script('window.ENABLE_VISIT_BEACON=true')
                page = context.new_page()
                page.on('pageerror', lambda e: results['javascript_errors'].append(str(e)))
                page.goto(base); page.wait_for_selector('[data-price]')
                if width == 390:
                    page.locator('#mobile-filters').click()
                    assert page.locator('#mobile-filters').get_attribute('aria-expanded') == 'true'
                    page.locator('#filters-done').click()
                    assert page.locator('#mobile-filters').get_attribute('aria-expanded') == 'false'
                card = page.locator(f'[data-price="{row["vin"]}"]')
                assert card.inner_text() == 'Review price'
                card.click(); page.locator('#deal-dialog[open]').wait_for()
                assert not page.locator('#vehicle-dialog').evaluate('(el)=>el.open')
                visible_button(page, '#deal-continue')
                page.locator('#deal-back').click(); page.locator('#vehicle-dialog[open]').wait_for()
                visible_button(page, '#vehicle-request')
                assert page.locator('#vehicle-request').inner_text() == 'Review price'
                page.locator('#vehicle-content').evaluate('(el)=>el.scrollTop=el.scrollHeight')
                visible_button(page, '#vehicle-request')
                page.locator('#tab-details').click()
                page.locator('.verification-details summary').click()
                assert re.search(r'equipment|computer|FSD', page.locator('#vehicle-panel').inner_text(), re.I)
                assert 'Clean title verified' not in page.locator('#vehicle-panel').inner_text()
                page.locator('#vehicle-request').click()
                page.locator('#deal-zip').fill('78201')
                page.wait_for_function('()=>document.querySelector("#deal-summary").textContent.includes("$21,735")')
                summary = page.locator('#deal-summary').inner_text()
                assert 'Estimated total' in summary and 'Pay in full' in summary and 'Monthly estimate' in summary
                assert '$20,000' in summary and '$1,535' in summary and '$200' in summary
                page.locator('[data-deal-mode=finance]').click()
                assert 'illustrative' in page.locator('#deal-summary').inner_text().lower()
                principal = 21735 - 3500
                rate = .0649 / 12
                monthly = int(principal * rate / (1 - (1 + rate) ** -60) + .5)
                assert f'${monthly:,}' in page.locator('.deal-finance-headline').inner_text()
                assert re.search(r'not (?:a credit offer|an offer)|not.*approval', page.locator('#deal-summary').inner_text().lower())
                if width == 390:
                    assert page.locator('#deal-scroll').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
                page.locator('#deal-scroll').evaluate('(el)=>el.scrollTop=el.scrollHeight')
                visible_button(page, '#deal-continue')
                page.locator('#deal-continue').click(); page.locator('#request-dialog[open]').wait_for()
                assert page.locator('#request-dialog h2').inner_text() == 'Your final price'
                visible_button(page, '#submit-request')
                assert page.locator('#submit-request').inner_text() == 'Request final price · $0 today'
                page.locator('[name=name]').fill('Fixture Buyer'); page.locator('[name=email]').fill('fixture@example.test')
                page.locator('[name=zip]').fill('78701'); page.locator('[name=payment_preference]').select_option('partner_financing')
                page.locator('[name=consent]').check()
                if width == 390:
                    assert page.locator('#request-scroll').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
                    assert page.locator('#request-scroll').evaluate('''(el)=>{
                      const box=el.getBoundingClientRect();
                      return [...el.querySelectorAll('input,select')].every(input=>{const r=input.getBoundingClientRect();return r.left>=box.left-1&&r.right<=box.right+1;});
                    }''')
                page.locator('#request-scroll').evaluate('(el)=>el.scrollTop=el.scrollHeight')
                visible_button(page, '#submit-request')
                page.locator('#request-back').click(); page.locator('#deal-dialog[open]').wait_for()
                assert page.locator('#deal-zip').input_value() == '78701'
                page.locator('#deal-continue').click(); page.locator('#request-dialog[open]').wait_for()
                for name, value in [('name', 'Fixture Buyer'), ('email', 'fixture@example.test'), ('zip', '78701'), ('payment_preference', 'partner_financing')]:
                    assert page.locator(f'[name={name}]').input_value() == value
                assert page.locator('[name=consent]').is_checked()
                state['malformed'] = True
                page.locator('#submit-request').click(); page.locator('#request-error').filter(has_text=re.compile('.+')).wait_for()
                assert page.locator('#request-dialog').evaluate('(el)=>el.open')
                assert not page.locator('#pay-deposit').count()
                assert not re.search(r'deposit verified|payment received|request recorded', page.locator('#request-error').inner_text(), re.I)
                state['malformed'] = False
                page.locator('[data-close=request-dialog]').click()
                card.click(); page.locator('[data-close=deal-dialog]').click()
                page.locator(f'[data-open="{row["vin"]}"]').first.click(); page.locator('[data-close=vehicle-dialog]').click()
                page.locator('#privacy-button').click(); assert 'equipment' in page.locator('#privacy-dialog').inner_text().lower()
                page.locator('[data-close=privacy-dialog]').click()
                card.click(); page.locator('#deal-continue').click()
                state['hold_request'] = True
                with page.expect_request(lambda req: req.url.endswith('/api/requests')):
                    page.locator('#submit-request').click()
                assert page.locator('#request-back').is_disabled()
                assert page.locator('[data-close=request-dialog]').is_disabled()
                page.keyboard.press('Escape')
                assert page.locator('#request-dialog').evaluate('(el)=>el.open')
                assert len(state['pending']) == 1
                state['pending'].pop().fulfill(status=201, json=dict(order, access_token=token))
                state['hold_request'] = False
                page.locator('#order-dialog[open]').wait_for(); page.locator('#copy-access').click()
                private_link = page.evaluate('navigator.clipboard.readText()')
                assert private_link.startswith(base) and '#request=' in private_link and token in private_link
                with page.expect_download() as download:
                    page.locator('#save-access').click()
                text = Path(download.value.path()).read_text()
                assert 'Volts' in text and token in text and 'href=' in text and '.html' in download.value.suggested_filename
                page.locator('[data-close=order-dialog]').click()
                context.close()
                fresh = browser.new_context(viewport={'width': width, 'height': 844}); fresh.route('**/*', route); fresh.add_init_script('window.ENABLE_VISIT_BEACON=true')
                recovered = fresh.new_page(); recovered.goto(private_link)
                recovered.locator('#order-dialog[open]').wait_for()
                assert '#' not in recovered.url and token not in recovered.url
                assert recovered.evaluate('JSON.parse(sessionStorage.getItem("marketplace_order")).id') == order_id
                recovered.locator('#switch-order').click()
                before = state['reads']
                for invalid in ['https://other.example/#request=x&access=y', base+'wrong#request=x&access=y', 'not a URL']:
                    recovered.locator('#recover-link').fill(invalid); recovered.locator('#open-return-link').click()
                    assert state['reads'] == before
                    assert not recovered.locator('#refresh-order').count()
                recovered.locator('#recover-link').fill(private_link); recovered.locator('#open-return-link').click()
                recovered.locator('#refresh-order').wait_for()
                assert state['reads'] > before
                assert recovered.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not any(token in v or 'access=' in v for v in state['visits'])
                fresh.close()
                results['viewports'][str(width)] = {'card_footer_direct_price': True, 'back_preserves_draft': True,
                    'close_buttons': True, 'sticky_footers_start_end': True, 'flow_input_bounds': True, 'estimate_math': True,
                    'malformed_response_no_payment_claim': True, 'pending_post_guards_navigation': True, 'private_copy_download_recovery': True,
                    'foreign_or_wrong_path_rejected': True, 'fragment_removed_before_beacon': True}
            assert not results['javascript_errors'], results['javascript_errors']
            assert not state['unexpected'], state['unexpected']
            browser.close()
    finally:
        server.shutdown(); server.server_close()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__': main()
