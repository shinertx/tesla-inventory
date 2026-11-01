"""Recorded settled funds must cover financed vehicle release; private evidence stays private."""
import json
import time

import pytest
from test_transactions import setup, request, customer, approve, checkout, event, auth, admin, status, t_body


def prepared(setup, financed=True):
    client, _, payments, store = setup
    order = request(client, body={**customer(), 'payment_preference': 'partner_financing' if financed else 'cash'})
    quote = approve(client, order)['quote']
    assert checkout(client, order).status_code == 200
    assert event(client, payments, order).status_code == 200
    assert client.post('/api/admin/orders/' + order['id'] + '/transition', json=t_body('deposit_paid'), headers=admin()).status_code == 200
    return client, payments, store, order, quote


def record_funding(client, order, amount, state='lender_funded', **changes):
    body = {'state': state, 'provider': 'Fixture lender', 'reference': 'PRIVATE_FUNDING_REFERENCE',
            'funded_amount_cents': amount, **changes}
    result = client.post('/api/admin/orders/' + order['id'] + '/financing', json=body, headers=admin())
    assert result.status_code == 200, result.text
    return result


def advance(client, order, state):
    return client.post('/api/admin/orders/' + order['id'] + '/transition', json=t_body(state), headers=admin())


def dispatch_body():
    now = int(time.time())
    return {'state': 'dispatched', 'provider': 'Fixture carrier', 'quote_reference': 'PRIVATE_CARRIER_QUOTE',
            'rate_cents': 47555, 'quote_expires_at': now+86400,
            'pickup_window_start': now, 'pickup_window_end': now+3600,
            'delivery_window_start': now+86400, 'delivery_window_end': now+172800,
            'carrier_acceptance_reference': 'PRIVATE_CARRIER_ACCEPTANCE',
            'bol_reference': 'customer-bol-fixture', 'tracking_url': 'https://carrier.example.test/tracking/fixture',
            'notes': 'PRIVATE_OPERATOR_NOTES'}


@pytest.mark.parametrize('shortfall', ['one_cent_received', 'one_cent_short'])
def test_partial_funding_never_advances_to_dealer_funded(setup, shortfall):
    client, _, store, order, quote = prepared(setup)
    balance = quote['balance_after_deposit_cents']
    record_funding(client, order, 1 if shortfall == 'one_cent_received' else balance-1)
    result = advance(client, order, 'dealer_confirmed')
    assert result.status_code == 409 and 'do not cover' in result.json()['detail']
    assert status(client, order) == 'dealer_confirmed'
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE order_id=? AND kind='dealer_funded'", (order['id'],)).fetchone()[0] == 0


@pytest.mark.parametrize('extra', [0, 100])
def test_exact_or_greater_settled_lender_proceeds_allow_release(setup, extra):
    client, _, _, order, quote = prepared(setup)
    record_funding(client, order, quote['balance_after_deposit_cents']+extra)
    assert advance(client, order, 'dealer_confirmed').status_code == 200
    assert advance(client, order, 'dealer_funded').status_code == 200
    assert status(client, order) == 'in_transit'


def test_conditional_approval_is_not_settled_money(setup):
    client, _, _, order, quote = prepared(setup)
    record_funding(client, order, 0, state='conditional_approval', approved_amount_cents=quote['total_cents'])
    assert advance(client, order, 'dealer_confirmed').status_code == 409


def test_legacy_funded_state_and_direct_dispatch_cannot_skip_coverage(setup):
    client, _, store, order, quote = prepared(setup)
    record_funding(client, order, quote['balance_after_deposit_cents']-1)
    # Simulate an older release state accepted before the coverage check existed.
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='dealer_funded' WHERE id=?", (order['id'],))
    assert advance(client, order, 'dealer_funded').status_code == 409
    endpoint = '/api/admin/orders/' + order['id'] + '/transport'
    assert client.post(endpoint, json=dispatch_body(), headers=admin()).status_code == 409
    record_funding(client, order, quote['balance_after_deposit_cents'])
    assert client.post(endpoint, json=dispatch_body(), headers=admin()).status_code == 200
    assert advance(client, order, 'dealer_funded').status_code == 200


def test_dispatch_requires_order_funding_before_release_marker(setup):
    client, _, _, order, _ = prepared(setup, financed=False)
    result = client.post('/api/admin/orders/' + order['id'] + '/transport', json=dispatch_body(), headers=admin())
    assert result.status_code == 409 and 'funding must be confirmed' in result.json()['detail']


def test_switching_to_cash_does_not_erase_partial_lender_funding(setup):
    client, _, _, order, _ = prepared(setup)
    record_funding(client, order, 1)
    assert client.post('/api/orders/' + order['id'] + '/payment-preference',
        json={'payment_preference': 'cash'}, headers=auth(order)).status_code == 200
    assert advance(client, order, 'dealer_confirmed').status_code == 409


def test_deposit_is_not_assumed_when_no_credited_payment_is_recorded(setup):
    client, _, store, order, quote = prepared(setup)
    with store.transaction() as db:
        db.execute('UPDATE orders SET payment_id=NULL WHERE id=?', (order['id'],))
    record_funding(client, order, quote['balance_after_deposit_cents'])
    assert advance(client, order, 'dealer_confirmed').status_code == 409
    record_funding(client, order, quote['total_cents'])
    assert advance(client, order, 'dealer_confirmed').status_code == 200


def test_existing_cash_receipt_and_settled_ach_paths_remain_available(setup):
    client, _, _, order, _ = prepared(setup, financed=False)
    assert advance(client, order, 'dealer_confirmed').status_code == 200
    assert advance(client, order, 'dealer_funded').status_code == 200


def test_full_recorded_ach_covers_financed_order_without_assuming_loan_proceeds(setup):
    client, _, store, order, _ = prepared(setup)
    # Simulate the existing canonical full-balance settlement record, not a down payment.
    with store.transaction() as db:
        db.execute("UPDATE orders SET balance_payment_state='paid',balance_payment_id='pi_fixture_settled_full_balance' WHERE id=?", (order['id'],))
    assert advance(client, order, 'dealer_confirmed').status_code == 200


def test_customer_projection_keeps_status_and_customer_delivery_charge_without_private_evidence(setup):
    client, _, store, order, quote = prepared(setup)
    with store.transaction() as db:
        row = db.execute('SELECT id,profile FROM dealers').fetchone()
        profile = json.loads(row['profile']); profile['online_portal_hosts'] = ['lender.example.test']
        db.execute('UPDATE dealers SET profile=? WHERE id=?', (json.dumps(profile), row['id']))
        # The existing order keeps its seller profile; portal approval uses the current dealer.
    financing = record_funding(client, order, 0, state='application_ready',
        application_url='https://lender.example.test/application/fixture', stipulations=['Proof of income']).json()['financing']
    assert financing == {'state': 'application_ready', 'provider': 'Fixture lender',
        'approved_amount_cents': 0, 'funded_amount_cents': 0,
        'stipulations': ['Proof of income'], 'application_url': 'https://lender.example.test/application/fixture'}
    body = dispatch_body(); body['state'] = 'quoted'
    response = client.post('/api/admin/orders/' + order['id'] + '/transport', json=body, headers=admin())
    assert response.status_code == 200
    public = client.get('/api/orders/' + order['id'], headers=auth(order)).json()
    transport = public['transport']
    assert transport['state'] == 'quoted' and transport['provider'] == 'Fixture carrier'
    assert transport['customer_delivery_charge_cents'] == quote['delivery_charge_cents']
    assert transport['bol_reference'] == 'customer-bol-fixture'
    assert transport['tracking_url'] == body['tracking_url']
    assert transport['pickup_window_start'] == body['pickup_window_start']
    assert not {'reference', 'notes', 'rate_cents', 'quote_reference', 'carrier_acceptance_reference'} & transport.keys()
    assert 'reference' not in public['financing']
    assert 'PRIVATE_' not in json.dumps(public)
