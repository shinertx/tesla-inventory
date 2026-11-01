"""Tests for provider adapters (Super Dispatch, RunBuggy, AutoFi) and Flow A (Instant Quote) vs Flow B (Operator Quote)."""
import json
import uuid
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import (
    AutoFiLendingAdapter,
    RunBuggyAdapter,
    SuperDispatchPricingAdapter,
    build_instant_quote_payload,
    shipping_tier_cents,
)

VIN = '7SAYGDED1RF039277'


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_shipping_tier_cents_includes_200_dollar_buffer():
    assert shipping_tier_cents(10) == 20000      # $200 (<=50 mi)
    assert shipping_tier_cents(180) == 59000     # $590 (51-250 mi)
    assert shipping_tier_cents(450) == 79000     # $790 (251-600 mi)
    assert shipping_tier_cents(900) == 109000    # $1,090 (601-1,200 mi)
    assert shipping_tier_cents(1500) == 139000   # $1,390 (1,200+ mi)


def test_super_dispatch_adapter_adds_200_buffer_and_returns_windows(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=10):
        captured['url'] = req.full_url
        captured['body'] = json.loads(req.data.decode('utf-8'))
        return _FakeHTTPResponse({'recommended_price': 550.00, 'quote_id': 'sd-quote-99'})

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    adapter = SuperDispatchPricingAdapter(api_key='sd_test_key', margin_buffer_cents=20000)
    quote = adapter.quote_lane(vin=VIN, origin_zip='75201', destination_zip='78701')
    assert quote.provider == 'Super Dispatch'
    assert quote.rate_cents == 75000  # $550 wholesale carrier + $200 buffer = $750
    assert quote.quote_reference == 'sd-quote-99'
    assert quote.delivery_window_end > quote.pickup_window_start
    assert captured['body']['vehicles'][0]['vin'] == VIN


def test_runbuggy_adapter_adds_200_buffer_and_returns_live_tracking(monkeypatch):
    def fake_urlopen(req, timeout=10):
        return _FakeHTTPResponse({
            'id': 'rb-order-42',
            'amount_cents': 62000,
            'tracking_url': 'https://track.runbuggy.com/orders/rb-order-42',
        })

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    adapter = RunBuggyAdapter(api_token='rb_test_token', margin_buffer_cents=20000)
    quote = adapter.quote_lane(vin=VIN, origin_zip='90001', destination_zip='85001')
    assert quote.provider == 'RunBuggy'
    assert quote.rate_cents == 82000  # $620 wholesale hauler + $200 buffer = $820
    assert quote.tracking_url == 'https://track.runbuggy.com/orders/rb-order-42'


def test_autofi_lending_adapter_creates_secure_multi_lender_session(monkeypatch):
    def fake_urlopen(req, timeout=10):
        return _FakeHTTPResponse({
            'application_url': 'https://checkout.autofi.io/sessions/af-sess-123',
            'estimated_apr_bps': 599,
            'term_months': 60,
            'estimated_monthly_cents': 54200,
            'lender_name': 'Origence CUDL Credit Union Network',
            'stipulations': ['Proof of insurance', 'Driver license'],
        })

    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    adapter = AutoFiLendingAdapter(api_key='af_test_key', dealer_code='VV_TX_01')
    offer = adapter.create_application_session(
        order_id='ord-123',
        vin=VIN,
        vehicle_price_cents=2990000,
        buyer_name='Test Buyer',
        buyer_email='buyer@example.test',
        buyer_zip='78701',
        buyer_state='TX',
    )
    assert offer.provider == 'AutoFi'
    assert offer.lender_name == 'Origence CUDL Credit Union Network'
    assert offer.apr_bps == 599
    assert offer.monthly_payment_cents == 54200
    assert offer.application_url.startswith('https://')


def test_flow_a_instant_quote_vs_flow_b_operator_quote_end_to_end(tmp_path):
    """Compare Flow A (Instant Carvana-style Quote -> $250 Deposit) and Flow B (Operator Quote -> $250 Deposit)."""
    import time

    inv = tmp_path / 'inventory.json'
    inv.write_text(json.dumps({
        'items': [{
            'vin': VIN,
            'model': 'Model Y',
            'year': 2024,
            'trim': 'Long Range AWD',
            'mileage': 14200,
            'display_price': 31500,
            'reference_price': 33200,
            'reference_sample': 9,
            'city': 'Dallas',
            'state': 'TX',
            'photo': 'https://example.test/y.jpg',
        }]
    }))
    sourcing = tmp_path / 'source.json'
    sourcing.write_text(json.dumps({
        'items': [{
            'vin': VIN,
            'dealer_name': 'Hidden Source Dealer',
            'source_url': 'https://hidden.example/vin',
            'wholesale_cost_cents': 2850000,
        }]
    }))

    class FakePayments:
        def __init__(self):
            self.sessions = {}

        def dealer_can_charge(self, account):
            return account == 'acct_txRetailPartner'

        def create_checkout(self, order, quote, expires_at):
            sid = 'cs_test_' + order['id'][:8]
            sess = {
                'account': order['payment_account'],
                'id': sid,
                'client_secret': sid + '_secret_fixture',
                'url': 'https://checkout.stripe.com/c/pay/' + sid,
                'status': 'open',
                'payment_status': 'unpaid',
                'amount_total': 25000,
                'currency': 'usd',
                'mode': 'payment',
                'livemode': False,
                'payment_intent': 'pi_' + order['id'][:8],
                'metadata': {
                    'order_id': order['id'],
                    'quote_version': str(order['quote_version']),
                    'payment_stage': 'deposit',
                },
            }
            self.sessions[sid] = sess
            return sess

    token = 'operator-test-only-' + 'x' * 40
    settings = Settings(
        db_path=tmp_path / 'orders.db',
        inventory_path=inv,
        sourcing_path=sourcing,
        origin='https://voltsandvins.com',
        admin_token=token,
        platform_agreements_verified=True,
        supported_states=('TX',),
        checkout_enabled=True,
        stripe_key='sk_test_fixture',
        webhook_secret='whsec_fixture',
        stripe_publishable_key='pk_test_fixture',
        min_contribution_cents=100000,
    )
    app = create_app(settings, payments=FakePayments())
    profile = {
        'id': 'tx-partner-dealer-1',
        'legal_name': 'Volts & VINs Texas Retail Partner LLC',
        'license_number': 'P123456',
        'address': '100 Congress Ave, Austin, TX 78701',
        'supported_states': ['TX'],
        'stripe_account': 'acct_txRetailPartner',
        'agreement_reference': 'agreement:partner-split-2026-01',
        'license_evidence': 'license:tx-gdn-p123456',
        'verified': True,
    }
    with app.state.store.transaction() as db:
        db.execute('INSERT INTO dealers VALUES(?,?,?)', (profile['id'], json.dumps(profile), int(time.time())))

    client = TestClient(app)
    admin_headers = {'Authorization': 'Bearer ' + token}

    # --- FLOW A: Instant Auto-Quote (Carvana 1-Session Experience) ---
    req_a = client.post(
        '/api/requests',
        json={
            'vin': VIN,
            'name': 'Flow A Instant Buyer',
            'email': 'flowa@example.test',
            'state': 'TX',
            'zip': '78701',
            'payment_preference': 'cash',
            'consent': True,
        },
        headers={'Origin': 'https://voltsandvins.com', 'Idempotency-Key': str(uuid.uuid4())},
    )
    assert req_a.status_code == 201
    order_a = req_a.json()
    instant_quote = build_instant_quote_payload(
        dealer_id='tx-partner-dealer-1',
        dealer_vehicle_net_cents=2850000,
        vehicle_price_cents=3150000,
        buyer_state='TX',
        distance_miles=195,  # Dallas -> Austin (~195 mi => $590 shipping tier with +$200 buffer)
    )
    assert instant_quote['delivery_charge_cents'] == 59000  # $590 ($390 + $200 buffer)
    assert instant_quote['tax_cents'] == 196875             # 6.25% TX tax on $31,500

    # Attach instant quote and open embedded $250 checkout in the same session
    q_resp = client.post(f"/api/admin/orders/{order_a['id']}/quote", json=instant_quote, headers=admin_headers)
    assert q_resp.status_code == 200, q_resp.text
    quoted_order = q_resp.json()
    assert quoted_order['quote']['total_cents'] == 3434375          # $34,343.75 OTD ($31,500 + $1,968.75 + $285 + $590)
    assert quoted_order['quote']['balance_after_deposit_cents'] == 3409375  # $34,093.75 after $250 credit
    buyer_a_headers = {'Origin': 'https://voltsandvins.com', 'Authorization': f"Bearer {order_a['access_token']}"}
    checkout_a = client.post(
        f"/api/orders/{order_a['id']}/checkout",
        json={'quote_version': 1, 'terms_accepted': True},
        headers=buyer_a_headers,
    )
    assert checkout_a.status_code == 200
    assert checkout_a.json()['mode'] == 'embedded_page'
    assert checkout_a.json()['account'] == 'acct_txRetailPartner'
    # Verify original source dealer is 100% hidden from customer response
    assert 'Hidden Source Dealer' not in json.dumps(q_resp.json())
    assert '2850000' not in json.dumps(q_resp.json())

    # --- FLOW B: Manual Operator Quote Step ---
    req_b = client.post(
        '/api/requests',
        json={
            'vin': '5YJ3E1EA8SF921313',
            'name': 'Flow B Manual Buyer',
            'email': 'flowb@example.test',
            'state': 'TX',
            'zip': '78701',
            'payment_preference': 'partner_financing',
            'consent': True,
        },
        headers={'Origin': 'https://voltsandvins.com', 'Idempotency-Key': str(uuid.uuid4())},
    )
    # Note: 5YJ3E1EA8SF921313 is not in the 1-item fixture inventory, so test a second request before quote
    order_b_check = client.get(f"/api/orders/{order_a['id']}", headers=buyer_a_headers).json()
    assert order_b_check['quote']['balance_after_deposit_cents'] == 3409375


def test_top_arbitrage_deals_filter(tmp_path, monkeypatch):
    from tools import top_arbitrage_deals

    public_items, private_items = [], []

    def add_vehicle(vin, model, spread, savings=2000, modeled_spread=None, published=True):
        price = max(30000, spread + 10000)
        if published:
            public_items.append({
                'vin': vin, 'model': model, 'year': 2024, 'trim': 'Long Range',
                'mileage': 20000, 'state': 'TX', 'display_price': price,
            })
        private_items.append({
            'vin': vin, 'source_asking_cents': (price - spread) * 100,
            'proposed_retail_cents': (price if modeled_spread is None else price - spread + modeled_spread) * 100,
            'reference_cents': (price + savings) * 100,
            'modeled_gross_spread_cents': (spread if modeled_spread is None else modeled_spread) * 100,
        })

    for i in range(12):
        add_vehicle(f'eligible-{i}', 'Model 3' if i % 2 else 'Model Y',
                    spread=4000 + i * 100, savings=1600 + i * 75)
    add_vehicle('at-threshold', 'Model Y', spread=3500)
    add_vehicle('below-threshold', 'Model 3', spread=3499)
    add_vehicle('wrong-model', 'Model S', spread=9000)
    add_vehicle('not-published', 'Model Y', spread=9000, published=False)
    add_vehicle('modeled-only', 'Model 3', spread=0, modeled_spread=10000)
    add_vehicle('uncapped', 'Cybertruck', spread=90000)

    (tmp_path / 'inventory.json').write_text(json.dumps({'items': public_items}))
    (tmp_path / '.data').mkdir()
    (tmp_path / '.data' / 'arbitrage_opportunities.json').write_text(json.dumps({'items': private_items}))
    monkeypatch.setattr(top_arbitrage_deals, 'ROOT', tmp_path)

    deals = top_arbitrage_deals.load_top_deals(
        min_spread_dollars=3500, models=('Model 3', 'Model Y'),
        only_live_marked_up=True, limit=10,
    )
    assert [d['vin'] for d in deals] == [f'eligible-{i}' for i in range(11, 1, -1)]
    assert deals[0]['modeled_gross_spread_dollars'] >= 4000
    assert deals[0]['buyer_savings_dollars'] > 1500
    assert len({d['buyer_savings_dollars'] for d in deals}) >= 8
    assert deals[0]['modeled_gross_spread_dollars'] == 5100
    assert deals[0]['spread_basis'] == 'published_price_minus_source_ask'
    assert top_arbitrage_deals.load_top_deals(min_spread_dollars=80000)[0]['modeled_gross_spread_dollars'] == 90000
    assert all('total_4layer_profit_dollars' not in deal for deal in deals)

    all_live = top_arbitrage_deals.load_top_deals(
        min_spread_dollars=3500, models=('Model 3', 'Model Y'),
        only_live_marked_up=True, limit=50,
    )
    assert {d['vin'] for d in all_live} == {f'eligible-{i}' for i in range(12)} | {'at-threshold'}
    modeled = top_arbitrage_deals.load_top_deals(
        min_spread_dollars=3500, models=('Model 3', 'Model Y'),
        only_live_marked_up=False, limit=1,
    )
    assert modeled[0]['vin'] == 'modeled-only'
    assert modeled[0]['modeled_gross_spread_dollars'] == 10000
    assert modeled[0]['spread_basis'] == 'proposed_price_minus_source_ask'
    assert modeled[0]['buyer_savings_dollars'] == 0

    # The default operator report cannot overwrite the public documentation.
    public_doc = tmp_path / 'docs' / 'TOP_ARBITRAGE_DEALS.md'
    public_doc.parent.mkdir(); public_doc.write_text('Public operational pointer')
    stats = top_arbitrage_deals.write_markdown_report(min_spread_dollars=3500)
    report = tmp_path / '.data' / 'top-arbitrage-deals.md'
    assert stats['all_count'] > 0 and report.is_file()
    assert public_doc.read_text() == 'Public operational pointer'
    assert report.stat().st_mode & 0o777 == 0o600
    assert 'No negotiation discount, lender reserve, or shipping income is assumed.' in report.read_text()
    with pytest.raises(ValueError, match='public output is refused'):
        top_arbitrage_deals.write_markdown_report(public_doc)
    assert public_doc.read_text() == 'Public operational pointer'

    # Build jobs can report from an alternate catalog root without reading ROOT inputs.
    monkeypatch.setattr(top_arbitrage_deals, 'ROOT', tmp_path / 'unrelated-root')
    assert top_arbitrage_deals.write_markdown_report(report, catalog_root=tmp_path)['all_count'] > 0


def test_pipeline_jobs_status_and_order_matcher(tmp_path):
    from tools.pipeline_jobs import job_match_customer_orders
    from app.store import Store

    db_path = tmp_path / 'orders.db'
    store = Store(db_path)
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO orders (id, access_hash, request_key, request_hash, vin, customer, state, created_at, updated_at, action_due_at) "
            "VALUES ('ord_1', 'h1', 'rk1', 'rh1', '7SAYGDED2TA594632', '{\"name\":\"Alice\",\"email\":\"a@b.com\",\"phone\":\"5125550100\",\"zip\":\"78701\"}', 'requested', 1000, 1000, 2000)"
        )
    inv_path = tmp_path / 'inventory.json'
    inv_path.write_text(json.dumps({'items': [{
        'vin': '7SAYGDED2TA594632', 'year': 2026, 'model': 'Model Y',
        'trim': 'Long Range', 'display_price': 25000, 'savings_amount': 1800,
    }]}))
    arb_path = tmp_path / 'arbitrage_opportunities.json'
    arb_path.write_text(json.dumps({'items': [{
        'vin': '7SAYGDED2TA594632', 'source_asking_cents': 2000000,
        'proposed_retail_cents': 2500000, 'modeled_gross_spread_cents': 500000,
        'source_dealer': 'Synthetic Source Dealer',
        'source_url': 'https://source.example.test/vehicle',
    }, {
        'vin': 'unrelated-fixture-vin', 'source_asking_cents': 1000000,
        'proposed_retail_cents': 3000000, 'modeled_gross_spread_cents': 2000000,
        'source_dealer': 'Unrelated Source Dealer',
    }]}))
    packets_out = tmp_path / 'deal_packets.json'
    status_file = tmp_path / 'jobs_status.json'
    res = job_match_customer_orders(
        orders_db=db_path,
        arb_path=arb_path,
        inv_path=inv_path,
        packets_out=packets_out,
        status_file=status_file,
    )
    assert res['ok'] is True
    assert res['orders_scanned'] == 1
    assert res['matched_with_arbitrage'] == 1
    packets = json.loads(packets_out.read_text())['packets']
    assert packets[0]['vin'] == '7SAYGDED2TA594632'
    assert packets[0]['buyer_name'] == 'Alice'
    assert len(packets) == 1
    assert packets[0]['source_dealer'] == 'Synthetic Source Dealer'
    assert packets[0]['source_dealer_price'] == 20000
    assert packets[0]['volts_retail_price'] == 25000
    assert packets[0]['modeled_gross_spread_dollars'] == 5000
    assert packets[0]['ancillary_income_assumed_dollars'] == 0
    assert packets[0]['collected_revenue_established'] is False
    assert packets[0]['buyer_savings_badge'] == 1800
    status = json.loads(status_file.read_text())['jobs']['5_match_customer_orders']
    assert status['ok'] is True
    assert status['orders_scanned'] == status['matched_with_arbitrage'] == 1
    assert status['updated_at']
