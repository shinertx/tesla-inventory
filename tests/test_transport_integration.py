"""API regressions for transport hooks; explicit local payment/lender fixtures only.

Requires main/model integration of app.transport_rules. No external network.
"""
import json
import time

import pytest
import app.main as main_module
from test_transactions import setup, request, customer, approve, checkout, event, admin, status, t_body


def advance(client, order, old_state):
    return client.post(f"/api/admin/orders/{order['id']}/transition", json=t_body(old_state), headers=admin())


def prepare(setup, funded=True):
    client, _, payments, store = setup
    order = request(client, body={**customer(), 'payment_preference': 'partner_financing'})
    quote = approve(client, order)['quote']
    if not funded: return client, store, order
    assert checkout(client, order).status_code == 200
    assert event(client, payments, order).status_code == 200
    assert advance(client, order, 'deposit_paid').status_code == 200
    result = client.post(f"/api/admin/orders/{order['id']}/financing", headers=admin(), json={
        'state': 'lender_funded', 'provider': 'Fixture lender', 'reference': 'fixture:settled-full-balance',
        'funded_amount_cents': quote['balance_after_deposit_cents']})
    assert result.status_code == 200, result.text
    result = advance(client, order, 'dealer_confirmed')
    assert result.status_code == 200, result.text
    assert status(client, order) == 'dealer_funded'
    return client, store, order


def transport_body(state='carrier_accepted', now=None):
    now = int(time.time()) if now is None else now
    return {'state': state, 'provider': 'Fixture carrier', 'quote_reference': 'fixture:carrier-rate',
        'rate_cents': 60000, 'quote_expires_at': now + 10,
        'pickup_window_start': now + 100, 'pickup_window_end': now + 400,
        'delivery_window_start': now + 300, 'delivery_window_end': now + 600,
        'carrier_acceptance_reference': 'fixture:carrier-accepted', 'bol_reference': 'fixture:bill-of-lading'}


def post_transport(client, order, body):
    return client.post(f"/api/admin/orders/{order['id']}/transport", json=body, headers=admin())


@pytest.mark.parametrize('change', [{'delivery_window_end': None},
    {'delivery_window_start': 200, 'delivery_window_end': 100},
    {'delivery_window_start': 1, 'delivery_window_end': 2}])
def test_api_rejects_half_inverted_or_impossible_windows(setup, change):
    client, store, order = prepare(setup, funded=False)
    body = {**transport_body('quoted'), **change}
    result = post_transport(client, order, body)
    assert result.status_code == 422, result.text
    with store.connect() as db:
        assert db.execute('SELECT transport_state FROM orders WHERE id=?', (order['id'],)).fetchone()[0] == 'unquoted'


def test_api_accepts_real_overlapping_planning_windows(setup):
    client, _, order = prepare(setup)
    body = transport_body()
    assert body['delivery_window_start'] < body['pickup_window_end']
    result = post_transport(client, order, body)
    assert result.status_code == 200, result.text
    assert result.json()['transport']['state'] == 'carrier_accepted'


def test_unpaid_quote_cannot_claim_carrier_acceptance(setup):
    client, _, order = prepare(setup, funded=False)
    result = post_transport(client, order, transport_body())
    assert result.status_code == 409, result.text
    assert status(client, order) == 'quoted'


def test_fully_funded_order_still_cannot_claim_delivery_before_transit(setup):
    client, _, order = prepare(setup)
    assert post_transport(client, order, transport_body()).status_code == 200
    result = post_transport(client, order, transport_body('delivered'))
    assert result.status_code == 409, result.text
    assert status(client, order) == 'dealer_funded'


@pytest.mark.parametrize('phase', ['dispatched', 'delivered'])
def test_api_rejects_regressing_real_booking_to_quote(setup, phase):
    client, _, order = prepare(setup)
    assert post_transport(client, order, transport_body()).status_code == 200
    assert post_transport(client, order, transport_body('dispatched')).status_code == 200
    if phase == 'delivered':
        assert advance(client, order, 'dealer_funded').status_code == 200
        assert post_transport(client, order, transport_body('delivered')).status_code == 200
        assert advance(client, order, 'in_transit').status_code == 200
    result = post_transport(client, order, transport_body('quoted'))
    assert result.status_code == 409, result.text


def test_unquoted_funded_order_cannot_enter_transit(setup):
    client, _, order = prepare(setup)
    result = advance(client, order, 'dealer_funded')
    assert result.status_code == 409, result.text
    assert status(client, order) == 'dealer_funded'


@pytest.mark.parametrize('marker', ['carrier_accepted', 'dispatched'])
def test_unchanged_booking_and_transit_survive_prebooking_rate_expiry(setup, monkeypatch, marker):
    client, _, order = prepare(setup)
    now = int(time.time()); accepted = transport_body(now=now)
    assert post_transport(client, order, accepted).status_code == 200
    monkeypatch.setattr(main_module.time, 'time', lambda: now + 20)
    updated = {**accepted, 'state': marker}
    result = post_transport(client, order, updated)
    assert result.status_code == 200, result.text
    result = advance(client, order, 'dealer_funded')
    assert result.status_code == 200, result.text
    assert status(client, order) == 'in_transit'


@pytest.mark.parametrize('marker', ['quoted', 'carrier_accepted'])
def test_api_rejects_expired_new_rate_or_booking(setup, marker):
    client, _, order = prepare(setup)
    result = post_transport(client, order, {**transport_body(marker), 'quote_expires_at': int(time.time()) - 1})
    assert result.status_code == 409, result.text


def test_changed_booking_identity_cannot_reuse_expired_rate(setup, monkeypatch):
    client, _, order = prepare(setup)
    now = int(time.time()); accepted = transport_body(now=now)
    assert post_transport(client, order, accepted).status_code == 200
    monkeypatch.setattr(main_module.time, 'time', lambda: now + 20)
    changed = {**accepted, 'state': 'dispatched', 'carrier_acceptance_reference': 'fixture:different-booking'}
    result = post_transport(client, order, changed)
    assert result.status_code == 409, result.text


def test_exception_recovery_reads_real_stored_accepted_event(setup, monkeypatch):
    client, store, order = prepare(setup)
    now = int(time.time()); accepted = transport_body(now=now)
    assert post_transport(client, order, accepted).status_code == 200
    dispatched = {**accepted, 'state': 'dispatched'}
    assert post_transport(client, order, dispatched).status_code == 200
    assert post_transport(client, order, {**dispatched, 'state': 'exception', 'notes': 'Fixture delay'}).status_code == 200
    with store.connect() as db:
        row = db.execute('SELECT transport_state,transport_detail FROM orders WHERE id=?', (order['id'],)).fetchone()
        assert row['transport_state'] == 'exception' and json.loads(row['transport_detail'])['state'] == 'exception'
        receipt = db.execute("SELECT detail FROM events WHERE order_id=? AND kind='transport_dispatched'", (order['id'],)).fetchone()
        assert json.loads(receipt['detail'])['carrier_acceptance_reference'] == accepted['carrier_acceptance_reference']
    monkeypatch.setattr(main_module.time, 'time', lambda: now + 20)
    result = post_transport(client, order, dispatched)
    assert result.status_code == 200, result.text
    assert advance(client, order, 'dealer_funded').status_code == 200
