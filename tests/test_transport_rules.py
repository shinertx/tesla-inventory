"""Pure helper regressions. API hooks and funding checks belong to integration."""
import pytest
from app.transport_rules import (TransportRuleError, validate_windows,
    validate_transport_update, require_booked_transport, same_accepted_booking)

NOW = 1000


def booking(state='carrier_accepted', **overrides):
    return dict(state=state, provider='Fixture carrier', quote_reference='quote:fixture', rate_cents=60000,
        carrier_acceptance_reference='accepted:fixture', bol_reference='bol:fixture',
        pickup_window_start=2000, pickup_window_end=4000, delivery_window_start=3000,
        delivery_window_end=5000, quote_expires_at=1500, **overrides)


@pytest.mark.parametrize('change', [
    {'pickup_window_start': None}, {'pickup_window_end': None}, {'pickup_window_start': -1},
    {'pickup_window_end': 100}, {'delivery_window_start': None}, {'delivery_window_end': None},
    {'delivery_window_end': 2500}, {'delivery_window_start': 0}, {'delivery_window_start': True},
    {'delivery_window_start': 500, 'delivery_window_end': 1500}])
def test_invalid_windows_rejected(change):
    data = booking(); data.update(change)
    with pytest.raises(TransportRuleError): validate_windows(data)


def test_overlapping_windows_and_unknown_delivery_are_valid():
    validate_windows(booking())
    data = booking(); data.update(delivery_window_start=None, delivery_window_end=None)
    validate_windows(data); require_booked_transport('carrier_accepted', data)
    validate_windows({'state': 'quoted'})


@pytest.mark.parametrize('order_state,state', [('quoted', 'carrier_accepted'), ('deposit_paid', 'carrier_accepted'),
    ('dealer_funded', 'delivered'), ('quoted', 'dispatched'), ('delivered', 'quoted'), ('in_transit', 'quoted')])
def test_order_phase_alignment(order_state, state):
    with pytest.raises(TransportRuleError): validate_transport_update(order_state, {}, booking(state), NOW)


@pytest.mark.parametrize('previous,state,order_state', [('carrier_accepted', 'quoted', 'dealer_funded'),
    ('dispatched', 'carrier_accepted', 'dealer_funded'), ('delivered', 'dispatched', 'in_transit')])
def test_no_silent_transport_regression(previous, state, order_state):
    with pytest.raises(TransportRuleError, match='regress'):
        validate_transport_update(order_state, booking(previous), booking(state), NOW)


@pytest.mark.parametrize('state', ['unquoted', 'quoted', 'exception', 'delivered'])
def test_transit_requires_genuine_accepted_or_dispatched_record(state):
    with pytest.raises(TransportRuleError): require_booked_transport(state, booking(state))


@pytest.mark.parametrize('detail', [None, {}, {'state': 'carrier_accepted'},
    dict(booking(), carrier_acceptance_reference=''), dict(booking('dispatched'), bol_reference='')])
def test_transit_rejects_missing_booking_evidence(detail):
    with pytest.raises(TransportRuleError): require_booked_transport('carrier_accepted' if not detail else detail.get('state', 'carrier_accepted'), detail)


@pytest.mark.parametrize('state', ['carrier_accepted', 'dispatched', 'delivered'])
def test_recorded_booking_survives_old_rate_expiry(state):
    old = booking(); incoming = booking(state); incoming['quote_expires_at'] = 500
    phase = 'in_transit' if state == 'delivered' else 'dealer_funded'
    validate_transport_update(phase, old, incoming, NOW)
    if state != 'delivered': require_booked_transport(state, incoming)


@pytest.mark.parametrize('field,value', [('provider', 'Another carrier'), ('quote_reference', 'quote:new'),
    ('carrier_acceptance_reference', 'accepted:new'), ('rate_cents', 70000)])
def test_changed_booking_cannot_reuse_expired_rate(field, value):
    incoming = booking('dispatched'); incoming.update(quote_expires_at=500); incoming[field] = value
    with pytest.raises(TransportRuleError, match='unexpired'):
        validate_transport_update('dealer_funded', booking(), incoming, NOW)


def test_expired_unaccepted_rate_and_first_acceptance_rejected():
    for state in ('quoted', 'carrier_accepted'):
        incoming = booking(state); incoming['quote_expires_at'] = 500
        with pytest.raises(TransportRuleError, match='unexpired'):
            validate_transport_update('dealer_confirmed', {}, incoming, NOW)


def test_exception_recovery_uses_recorded_booking_not_exception_claim():
    old = booking('dispatched'); exception = dict(old, state='exception')
    incoming = dict(old, quote_expires_at=500)
    validate_transport_update('in_transit', exception, incoming, NOW, accepted_booking=old)
    with pytest.raises(TransportRuleError, match='unexpired'):
        validate_transport_update('in_transit', exception, incoming, NOW)
    assert not same_accepted_booking(exception, incoming)


def test_accepted_metadata_update_after_order_transit_is_allowed_without_regression():
    old = booking(); incoming = dict(old, quote_expires_at=500, tracking_url='https://carrier.example/track')
    validate_transport_update('in_transit', old, incoming, NOW)
    changed = dict(incoming, carrier_acceptance_reference='accepted:new')
    with pytest.raises(TransportRuleError): validate_transport_update('in_transit', old, changed, NOW)


def test_exception_can_record_problem_but_not_reopen_delivered_booking():
    old = booking('delivered')
    validate_transport_update('delivered', old, dict(old, state='exception'), NOW)
    with pytest.raises(TransportRuleError):
        validate_transport_update('delivered', dict(old, state='exception'), booking('quoted'), NOW, accepted_booking=old)
