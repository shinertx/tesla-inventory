"""Provider placeholders fail closed; estimates cannot approve a payable quote."""
import json
import uuid
import pytest
from app.models import Quote
from pydantic import ValidationError
from app.providers import (
    AutoFiLendingAdapter, RunBuggyAdapter, SuperDispatchPricingAdapter,
    ProviderNotConfigured, build_instant_quote_payload, shipping_tier_cents,
)
from test_transactions import setup, request, auth, admin


@pytest.mark.parametrize('distance,amount', [(10, 20000), (180, 59000), (450, 79000), (900, 109000), (1500, 139000)])
def test_distance_tiers_are_illustrative_estimates(distance, amount):
    assert shipping_tier_cents(distance) == amount


@pytest.mark.parametrize('distance', [-1, float('nan'), float('inf'), True, '100'])
def test_invalid_distance_does_not_produce_a_plausible_estimate(distance):
    with pytest.raises(ValueError):
        shipping_tier_cents(distance)


@pytest.mark.parametrize('adapter,kwargs,name', [
    (SuperDispatchPricingAdapter, {'api_key': 'supplied-key'}, 'Super Dispatch'),
    (RunBuggyAdapter, {'api_token': 'supplied-key'}, 'RunBuggy'),
    (AutoFiLendingAdapter, {'api_key': 'supplied-key', 'dealer_code': 'supplied-dealer'}, 'AutoFi'),
])
def test_unverified_provider_contracts_cannot_network_even_with_credentials(monkeypatch, adapter, kwargs, name):
    def prohibited(*args, **kwargs):
        pytest.fail('Unverified adapter attempted network access')
    monkeypatch.setattr('urllib.request.Request', prohibited)
    monkeypatch.setattr('urllib.request.urlopen', prohibited)
    monkeypatch.setattr('urllib.request.build_opener', prohibited)
    with pytest.raises(ProviderNotConfigured, match=name + '.*disabled'):
        adapter(**kwargs, base_url='https://example.test/unverified')


def estimate():
    return build_instant_quote_payload(dealer_id='unverified-dealer', dealer_vehicle_net_cents=2850000,
        vehicle_price_cents=3150000, buyer_state='TX', distance_miles=195,
        terms_base_url='https://example.test/terms-not-verified')


def test_estimate_has_no_generated_vehicle_or_seller_evidence():
    result = estimate()
    assert result['estimate_only'] is True and result['binding'] is False and result['carrier_booked'] is False
    assert result['estimated_delivery_cents'] == 59000
    assert result['estimated_tax_cents'] == 196875
    assert result['estimated_total_cents'] == 3434375
    assert not any(key.endswith('_reference') for key in result)
    assert not {'seller_hold_until', 'valid_until', 'title_status', 'condition_status', 'recall_disposition',
                'dealer_id', 'dealer_vehicle_net_cents', 'apr_bps', 'application_url'} & result.keys()
    assert 'verified-onboarding' not in json.dumps(result)
    assert 'https://' not in json.dumps(result)
    with pytest.raises(ValidationError):
        Quote.model_validate(result)


def test_estimate_cannot_approve_quote_or_unlock_checkout(setup):
    client, _, payments, _ = setup
    order = request(client)
    response = client.post('/api/admin/orders/' + order['id'] + '/quote', json=estimate(), headers=admin())
    assert response.status_code == 422
    status = client.get('/api/orders/' + order['id'], headers=auth(order)).json()
    assert status['state'] == 'requested' and status['quote'] is None
    checkout = client.post('/api/orders/' + order['id'] + '/checkout',
        json={'quote_version': 1, 'terms_accepted': True}, headers=auth(order))
    assert checkout.status_code == 409 and payments.session_calls == 0


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
