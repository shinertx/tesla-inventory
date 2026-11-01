"""Pure transport evidence and lifecycle checks; no provider or payment actions.

Funding coverage remains the caller's separate mandatory gate. Quote expiry applies
before booking; an unchanged, recorded accepted booking survives its rate expiry.
"""
from collections.abc import Mapping


class TransportRuleError(ValueError):
    pass


_BOOKED = {'carrier_accepted', 'dispatched', 'delivered'}
_RANK = {'unquoted': 0, 'quoted': 1, 'carrier_accepted': 2, 'dispatched': 3, 'delivered': 4}
_ORDER_PHASES = {
    'quoted': {'quoted', 'quote_expired', 'checkout_pending', 'deposit_processing', 'deposit_paid', 'dealer_confirmed', 'dealer_funded'},
    'carrier_accepted': {'dealer_confirmed', 'dealer_funded'},
    'dispatched': {'dealer_funded', 'in_transit'},
    'delivered': {'in_transit', 'delivered', 'settlement_pending'},
}
_CLOSED = {'cancelled', 'refunded', 'completed'}


def _reference(value, minimum=5):
    return isinstance(value, str) and len(value.strip()) >= minimum


def validate_windows(detail):
    """Validate supplied planning windows, without inventing missing delivery dates.

These are planning windows, not guaranteed chronology for every endpoint.
Overlapping ranges are valid; reject only delivery wholly before earliest pickup.
"""
    for kind in ('pickup', 'delivery'):
        start, end = detail.get(kind + '_window_start'), detail.get(kind + '_window_end')
        if start is None and end is None: continue
        if type(start) is not int or type(end) is not int or start <= 0 or end <= 0 or end < start:
            raise TransportRuleError('Transport windows require paired positive timestamps in chronological order')
    pickup = detail.get('pickup_window_start')
    delivery = detail.get('delivery_window_end')
    if pickup is not None and delivery is not None and delivery < pickup:
        raise TransportRuleError('Delivery window cannot end before pickup can begin')


def _identity(detail):
    if not isinstance(detail, Mapping) or detail.get('state') not in _BOOKED: return None
    if not _reference(detail.get('provider'), 2) or not _reference(detail.get('quote_reference')) or not _reference(detail.get('carrier_acceptance_reference')):
        return None
    rate = detail.get('rate_cents')
    if type(rate) is not int or not 0 <= rate <= 2_000_000: return None
    return tuple(detail[key] for key in ('provider', 'quote_reference', 'carrier_acceptance_reference', 'rate_cents'))


def same_accepted_booking(recorded, incoming):
    """Only an explicit accepted/dispatched/delivered record establishes identity.

A quoted/exception payload containing an acceptance-looking string is insufficient.
For an exception, callers can supply the prior accepted event from their ledger.
"""
    original, current = _identity(recorded), _identity(incoming)
    return original is not None and original == current


def require_booked_transport(state, detail):
    """Require recorded acceptance before the order enters in_transit.

A rate quote, missing detail, exception, or prematurely delivered status cannot
replace accepted booking evidence. No quote-expiry check applies after booking.
"""
    if state not in {'carrier_accepted', 'dispatched'} or not isinstance(detail, Mapping) or detail.get('state') != state:
        raise TransportRuleError('Carrier acceptance is required before dispatch; a rate quote alone cannot release the vehicle')
    if _identity(detail) is None:
        raise TransportRuleError('Recorded carrier acceptance evidence is required before dispatch')
    validate_windows(detail)
    if detail.get('pickup_window_start') is None:
        raise TransportRuleError('Carrier acceptance requires a pickup window')
    if state == 'dispatched' and not _reference(detail.get('bol_reference')):
        raise TransportRuleError('Dispatch requires a bill of lading reference')


def validate_transport_update(order_state, previous, incoming, now, *, accepted_booking=None):
    """Reject lifecycle regressions; preserve unchanged accepted booking updates.

Pass previous as the current stored detail (or {'state':'unquoted'}). Optional
accepted_booking must be a prior accepted/dispatched/delivered ledger event, not
an incoming claim. This preserves booking identity across exception reporting.
Funding validation must still run in the caller before recording dispatch/delivery.
"""
    if order_state in _CLOSED: raise TransportRuleError('Order is closed')
    state = incoming.get('state')
    if state not in {*_ORDER_PHASES, 'exception'}: raise TransportRuleError('Unsupported transport state')
    validate_windows(incoming)
    previous = previous if isinstance(previous, Mapping) else {'state': 'unquoted'}
    recorded = accepted_booking if _identity(accepted_booking) is not None else previous
    same_booking = same_accepted_booking(recorded, incoming)
    previous_state = previous.get('state', 'unquoted')
    allowed = state == 'exception' or order_state in _ORDER_PHASES[state]
    # The order can enter transit while its transport record still says accepted.
    # Allow metadata updates to that same record, not a new pre-dispatch booking.
    if state == 'carrier_accepted' and order_state == 'in_transit':
        allowed = previous_state == 'carrier_accepted' and same_booking
    if not allowed: raise TransportRuleError('Transport status does not match the order phase')
    if state != 'exception':
        floor = max(_RANK.get(previous_state, 0), _RANK.get(recorded.get('state'), 0) if isinstance(recorded, Mapping) and _identity(recorded) else 0)
        if _RANK[state] < floor: raise TransportRuleError('Transport status cannot regress after carrier acceptance or dispatch')
    if state in _BOOKED:
        if _identity(incoming) is None: raise TransportRuleError('Carrier booking evidence is required')
        if incoming.get('pickup_window_start') is None: raise TransportRuleError('Carrier acceptance requires a pickup window')
        if state in {'dispatched', 'delivered'} and not _reference(incoming.get('bol_reference')):
            raise TransportRuleError('Dispatch and delivery require a bill of lading reference')
    if state != 'exception' and not same_booking:
        expiry = incoming.get('quote_expires_at')
        if type(expiry) is not int or expiry <= now:
            raise TransportRuleError('A new transport rate or booking requires an unexpired quote')
