"""Bound reservation authorizations are not captured deposits or settled funds."""

DEPOSIT_CENTS=25000
PAID_STATES={'deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending','completed'}


def captured_cents(row):
    recorded=int(row['deposit_captured_cents'] or 0)
    if recorded:return recorded
    # Preserve pre-migration automatic deposits without inventing manual captures.
    if row['deposit_capture_method']=='automatic' and row['payment_id'] and row['state'] in PAID_STATES:
        return DEPOSIT_CENTS
    return 0


def deposit_summary(row):
    state=row['state'];captured=captured_cents(row)
    if state=='refunded':status='refunded'
    elif state=='refund_pending':status='refund_pending'
    elif state=='authorization_release_pending':status='release_pending'
    elif row['deposit_released_at']:status='released'
    elif state=='deposit_authorized':status='authorized'
    elif captured:status='paid'
    elif state in {'deposit_processing','checkout_pending'}:status='pending'
    elif state in {'payment_review','model_review'}:status='review'
    else:status='unpaid'
    return {'deposit_status':status,'deposit_capture_method':row['deposit_capture_method'],
            'authorized_cents':int(row['authorized_cents'] or 0),
            'authorization_expires_at':row['authorization_expires_at'],
            'deposit_captured_cents':captured}


def validate_intent(intent,row,live,*,payment_id=None):
    """Validate the canonical intent retrieved with the order's exact account scope."""
    if not isinstance(intent,dict) or not isinstance(intent.get('metadata'),dict):
        raise ValueError('Authorization metadata is unavailable')
    metadata=intent['metadata']
    expected=payment_id or row['payment_id']
    if not (isinstance(intent,dict) and isinstance(expected,str) and expected.startswith('pi_')
            and intent.get('id')==expected and intent.get('capture_method')=='manual'
            and type(intent.get('amount')) is int and intent['amount']==DEPOSIT_CENTS
            and type(intent.get('amount_received')) is int and type(intent.get('amount_capturable')) is int
            and intent.get('currency')=='usd' and intent.get('livemode') is live
            and metadata.get('order_id')==row['id']
            and metadata.get('quote_version')==str(row['quote_version'])
            and metadata.get('payment_stage')=='deposit'
            and metadata.get('vin')==row['vin']
            and intent.get('payment_method_types')==['card']):
        raise ValueError('Authorization does not match this order')
    return intent


def authorization_deadline(intent,now):
    try:
        deadline=intent['latest_charge']['payment_method_details']['card']['capture_before']
    except (KeyError,TypeError):
        raise ValueError('Card authorization expiry could not be verified') from None
    if type(deadline) is not int or not now<deadline<=now+31*86400:
        raise ValueError('Card authorization has expired or has no valid deadline')
    return deadline
