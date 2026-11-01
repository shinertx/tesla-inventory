"""Observational funding reconciliation. No transfers, captures, refunds, or payouts."""
import hashlib
import json
from .models import Quote, canonical_reference

CREDITED_STATES={'deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending','completed'}
REFUND_REVIEW_STATES={'cancelled','refunded','refund_pending'}
CASH_RECORD_STATES={'deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending'}


def seller_key(row):
    profile=json.loads(row['dealer_profile'] or '{}')
    identity={k:profile.get(k) for k in ('legal_name','license_number','address')}
    identity.update(dealer_id=row['dealer_id'],payment_account=row['payment_account'])
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()


def cash_totals(c,row):
    current=unallocated=0
    for receipt in c.execute("SELECT * FROM buyer_cash_entries WHERE order_id=? AND kind='receipt'",(row['id'],)):
        reversed_cents=c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM buyer_cash_entries WHERE receipt_id=? AND kind='reversal'",(receipt['id'],)).fetchone()[0]
        net=receipt['amount_cents']-reversed_cents
        if receipt['quote_version']==row['quote_version'] and receipt['dealer_id']==row['dealer_id'] and receipt['seller_key']==seller_key(row):current+=net
        else:unallocated+=net
    return current,unallocated


def _legacy_lender_proceeds(c,row):
    if row['financing_state']!='lender_funded':return 0,False
    try:
        detail=json.loads(row['financing_detail'])
        amount=detail['funded_amount_cents']
        if detail['state']!='lender_funded' or type(amount) is not int or not 0<amount<=100_000_000:raise ValueError()
        for other in c.execute('SELECT financing_detail FROM orders WHERE id!=? AND financing_detail IS NOT NULL',(row['id'],)):
            if canonical_reference(json.loads(other[0]).get('reference'))==canonical_reference(detail.get('reference')):return 0,True
        if '_quote_version' in detail or '_seller_key' in detail:
            matched=detail.get('_quote_version')==row['quote_version'] and detail.get('_seller_key')==seller_key(row)
        else:
            # Historical API events establish ordering without inventing a historical snapshot.
            funded=c.execute("SELECT id,detail FROM events WHERE order_id=? AND kind='financing_lender_funded' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
            quote=c.execute("SELECT id,detail FROM events WHERE order_id=? AND kind='quote_approved' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
            historical=json.loads(funded['detail']) if funded else {}
            historical={**historical,'reference':canonical_reference(historical.get('reference'))}
            normalized={**detail,'reference':canonical_reference(detail.get('reference'))}
            matched=bool(funded and quote and funded['id']>quote['id'] and historical==normalized
                         and json.loads(quote['detail']).get('dealer_id')==row['dealer_id']
                         and c.execute("SELECT COUNT(*) FROM events WHERE order_id=? AND kind='quote_approved'",(row['id'],)).fetchone()[0]==row['quote_version'])
        return (amount,False) if matched else (0,True)
    except (ValueError,TypeError,KeyError,AttributeError):return 0,True



def lender_head(c,row):
    return c.execute('SELECT * FROM lender_funding_observations WHERE order_id=? AND quote_version=? AND dealer_id=? AND seller_key=? ORDER BY seq DESC LIMIT 1',
                     (row['id'],row['quote_version'],row['dealer_id'],seller_key(row))).fetchone()


def lender_proceeds(c,row):
    contexts={};represented_refs=set();represented_events=set()
    for observation in c.execute('SELECT * FROM lender_funding_observations WHERE order_id=? ORDER BY seq DESC',(row['id'],)):
        context=(observation['quote_version'],observation['dealer_id'],observation['seller_key'])
        contexts.setdefault(context,observation)
        represented_refs.add(canonical_reference(observation['reference']))
        if observation['prior_reference']:represented_refs.add(canonical_reference(observation['prior_reference']))
        if observation['legacy_prior_event_id']:represented_events.add(observation['legacy_prior_event_id'])
    current=(row['quote_version'],row['dealer_id'],seller_key(row))
    head=contexts.get(current)
    allocated=head['amount_cents'] if head else 0
    prior=sum(item['amount_cents'] for context,item in contexts.items() if context!=current)
    represented_contexts={(context[0],context[1]) for context in contexts}
    legacy={};version=0;dealer=None;ambiguous=False
    # Historical funded events are cumulative snapshots within their actual preceding quote.
    # Read them alongside registry heads, not only until the first registry row appears.
    for event in c.execute("SELECT id,kind,detail FROM events WHERE order_id=? AND kind IN ('quote_approved','financing_lender_funded') ORDER BY id",(row['id'],)):
        if event['kind']=='quote_approved':version+=1;dealer=None
        try:
            detail=json.loads(event['detail'])
            if not isinstance(detail,dict):raise ValueError()
            if event['kind']=='quote_approved':
                dealer=detail.get('dealer_id');continue
            reference=canonical_reference(detail.get('reference'))
            if event['id'] in represented_events or reference in represented_refs:continue
            amount=detail.get('funded_amount_cents')
            if type(amount) is not int or not 0<amount<=100_000_000 or not isinstance(reference,str) or len(reference)<5 or detail.get('state')!='lender_funded':raise ValueError()
            if version<1 or not isinstance(dealer,str) or not dealer:raise ValueError()
            context=(version,dealer)
            if context in represented_contexts:continue  # A current net registry snapshot replaces its older cumulative history.
            legacy[context]=amount
        except (ValueError,TypeError,KeyError):ambiguous=True
    if not head:
        existing,review=_legacy_lender_proceeds(c,row)
        ambiguous=ambiguous or review
        if existing:
            allocated=existing
            legacy.pop((row['quote_version'],row['dealer_id']),None)
    prior+=sum(legacy.values())
    return allocated,bool(prior or ambiguous),prior,bool(head and head['kind']=='correction')


class FundingRuleError(ValueError):
    pass


def observe_lender_snapshot(c,row,body,now):
    """Record a cumulative net settled snapshot. Snapshots are never summed as deltas."""
    identity={'order_id':row['id'],'quote_version':row['quote_version'],'dealer_id':row['dealer_id'],
              'seller_key':seller_key(row),'amount_cents':body.funded_amount_cents,'provider':body.provider,'currency':'USD'}
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    existing=c.execute('SELECT * FROM lender_funding_observations WHERE canonical_reference(reference)=?',(body.reference,)).fetchone()
    if existing:
        if existing['kind']!='funding' or existing['payload_hash']!=fingerprint:
            raise FundingRuleError('Lender funding reference is already bound to another amount, order, quote, or seller')
        # Replaying an older observation must not replace a newer reconciliation head.
        head=lender_head(c,row)
        if not head or canonical_reference(head['reference'])!=canonical_reference(existing['reference']):
            raise FundingRuleError('A newer lender reconciliation exists; the old funding snapshot cannot replace it')
        return
    for event in c.execute("SELECT id,detail FROM events WHERE order_id=? AND kind='financing_lender_funded' ORDER BY id DESC",(row['id'],)):
        try:historical=json.loads(event['detail'])
        except (ValueError,TypeError):continue
        if canonical_reference(historical.get('reference'))!=body.reference:continue
        if c.execute('SELECT 1 FROM lender_funding_observations WHERE legacy_prior_event_id=?',(event['id'],)).fetchone():
            raise FundingRuleError('Historical lender funding has been reconciled; its old snapshot cannot be replayed')
        version=c.execute("SELECT COUNT(*) FROM events WHERE order_id=? AND kind='quote_approved' AND id<?",(row['id'],event['id'])).fetchone()[0]
        if version!=row['quote_version'] or historical.get('funded_amount_cents')!=body.funded_amount_cents or historical.get('provider')!=body.provider:
            raise FundingRuleError('Historical lender reference cannot be reassigned to a different quote, amount, or lender')
        break
    head=lender_head(c,row)
    baseline=head['amount_cents'] if head else _legacy_lender_proceeds(c,row)[0]
    if body.funded_amount_cents<baseline:
        raise FundingRuleError('A lower lender amount requires an append-only lender funding correction with actual evidence')
    if baseline>0:
        baseline_provider=head['provider'] if head else json.loads(row['financing_detail']).get('provider')
        if baseline_provider!=body.provider:
            raise FundingRuleError('Changing the recorded lender requires reconciliation before new funding can be applied')
    c.execute('INSERT INTO lender_funding_observations(reference,kind,prior_reference,order_id,quote_version,dealer_id,seller_key,provider,amount_cents,currency,evidence_reference,observed_at,payload_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (body.reference,'funding',head['reference'] if head else None,row['id'],row['quote_version'],row['dealer_id'],seller_key(row),
         body.provider,body.funded_amount_cents,'USD',body.reference,now,fingerprint))

def settled_balance(c,row):
    if row['balance_payment_state']!='paid' or not row['balance_payment_id']:return 0,False
    for event in c.execute("SELECT id,detail FROM events WHERE order_id=? AND kind='balance_payment_settled' ORDER BY id DESC",(row['id'],)):
        try:
            detail=json.loads(event['detail'])
            if detail.get('balance_payment_id')!=row['balance_payment_id']:continue
            amount=detail.get('amount_cents')
            if type(amount) is not int or amount<=0:continue
            latest=c.execute("SELECT id FROM events WHERE order_id=? AND kind='quote_approved' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
            if not latest or latest['id']>event['id']:return 0,True
            return amount,False
        except (ValueError,TypeError):continue
    return 0,True


def funding_summary(c,row,deposit_cents=25000):
    if not row['quote'] or row['workflow_model']!='dealer_fulfillment':return None
    quote=Quote.model_validate_json(row['quote'])
    deposit=deposit_cents if row['payment_id'] and row['state'] in CREDITED_STATES and not row['refund_id'] else 0
    lender,lender_review,prior_lender,corrected=lender_proceeds(c,row)
    balance,balance_review=settled_balance(c,row)
    cash,unallocated=cash_totals(c,row)
    received=deposit+lender+balance+cash
    remaining=max(0,quote.total_cents-received)
    overpaid=max(0,received-quote.total_cents)
    in_flight_conflict=bool((cash or lender or unallocated or prior_lender)
        and row['balance_payment_state'] in {'checkout_open','ach_processing','payment_review'})
    review=bool(lender_review or balance_review or unallocated or prior_lender or overpaid or (corrected and remaining>0 and row['state'] not in REFUND_REVIEW_STATES)
                or in_flight_conflict
                or row['balance_payment_state']=='payment_review'
                or (row['state'] in REFUND_REVIEW_STATES and (cash or lender or balance))
                or (row['state'] in {'dealer_funded','in_transit','delivered','settlement_pending','completed'} and remaining))
    checkout_allowed=bool(row['state']=='dealer_confirmed' and not (cash or lender or balance or review or remaining==0)
        and row['balance_payment_state'] not in {'ach_processing','paid'}
        and (row['payment_preference']=='cash' or row['financing_state']=='declined'))
    return {'currency':'USD','quote_version':row['quote_version'],'quote_total_cents':quote.total_cents,'credited_deposit_cents':deposit,
            'lender_funded_cents':lender,'settled_balance_cents':balance,
            'net_additional_cash_cents':cash,'prior_quote_unallocated_cash_cents':unallocated,
            'prior_quote_unallocated_lender_cents':prior_lender,
            'remaining_cents':remaining,'overpaid_cents':overpaid,'coverage_complete':remaining==0,
            'funds_review_required':review,'balance_checkout_allowed':checkout_allowed,
            'in_flight_balance_conflict':in_flight_conflict}
