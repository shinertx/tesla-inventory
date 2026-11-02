"""Terminal orders expire internal sourcing commitments without claiming dealer release."""
import json
import time
import uuid

import pytest

from test_transactions import setup,request,approve,auth,admin,t_body
from test_manual_authorizations import manual,prepared,authorize,capture,current,fully_fund,pi_succeeded


def source_state(store,order):
    with store.connect() as c:
        hold=dict(c.execute('SELECT * FROM source_holds WHERE order_id=?',(order['id'],)).fetchone())
        events=[json.loads(row[0]) for row in c.execute(
            "SELECT detail FROM events WHERE order_id=? AND kind='source_hold_release_requested'",(order['id'],))]
    return hold,events


def cancel(client,order):
    response=client.post('/api/orders/'+order['id']+'/cancel',json={'reason':'Changed plans'},headers=auth(order))
    assert response.status_code==200,response.text
    return response.json()


def refund(client,order):
    response=client.post('/api/admin/orders/'+order['id']+'/refund',json={},headers=admin())
    assert response.status_code==200,response.text
    return response.json()


def refund_event(client,order):
    return client.post('/api/stripe/webhook',json={
        'id':'evt_'+str(uuid.uuid4()),'type':'refund.updated','account':'acct_fixtureDealer','livemode':False,
        'data':{'object':{'id':'re_fixture','payment_intent':'pi_'+order['id'],'amount':25000,'status':'succeeded'}}},
        headers={'Stripe-Signature':'valid-test-signature'})


def assert_expired_once(store,order,previous):
    hold,events=source_state(store,order)
    assert hold['expires_at']<=int(time.time())
    assert hold['reference']==previous['reference']
    assert len(events)==1
    assert events[0]['previous_expires_at']==previous['expires_at']
    assert events[0]['scope']=='internal_commitment_only'
    assert events[0]['dealer_release_confirmed'] is False
    assert events[0]['external_request_sent'] is False
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM outbox WHERE order_id=? AND kind='source_hold_release_requested'",(order['id'],)).fetchone()[0]==1


def paid(manual):
    client,settings,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    assert capture(client,order).status_code==200
    return client,settings,payments,store,order


def test_quoted_cancellation_expires_commitment_once_without_provider_action(manual):
    client,_,payments,store=manual;order=request(client);approve(client,order)
    previous,_=source_state(store,order)
    assert cancel(client,order)['state']=='cancelled'
    assert cancel(client,order)['state']=='cancelled'
    assert_expired_once(store,order,previous)
    assert payments.refunds==payments.release_calls==payments.capture_calls==payments.session_calls==0


def test_open_checkout_cancellation_expires_source_commitment(manual):
    client,_,payments,store,order=prepared(manual);previous,_=source_state(store,order)
    assert cancel(client,order)['state']=='cancelled'
    assert_expired_once(store,order,previous)
    assert payments.release_calls==payments.refunds==0


def test_source_commitment_waits_for_confirmed_card_release_then_worker_expires_it(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    previous,_=source_state(store,order);payments.fail_release=True
    assert cancel(client,order)['state']=='authorization_release_pending'
    assert source_state(store,order)==(previous,[])
    payments.fail_release=False
    with store.transaction() as c:c.execute('UPDATE orders SET action_due_at=? WHERE id=?',(int(time.time())-1,order['id']))
    assert client.post('/api/admin/refunds/process',json={},headers=admin()).status_code==200
    assert current(client,order)['state']=='cancelled'
    cancel(client,order);assert_expired_once(store,order,previous)


def test_successful_refund_closes_source_commitment_and_replays_do_not_repeat_request(manual):
    client,_,payments,store,order=paid(manual);previous,_=source_state(store,order)
    assert cancel(client,order)['state']=='refund_pending'
    assert source_state(store,order)==(previous,[])
    assert refund(client,order)['state']=='refunded'
    assert refund(client,order)['state']=='refunded'
    assert refund_event(client,order).status_code==200
    assert refund_event(client,order).status_code==200
    cancel(client,order);assert_expired_once(store,order,previous)
    assert payments.refunds==1 and payments.capture_calls==1


def test_pending_refund_keeps_commitment_until_signed_success_event(manual):
    client,_,payments,store,order=paid(manual);previous,_=source_state(store,order)
    original=payments.refund
    payments.refund=lambda row:{**original(row),'status':'pending'}
    cancel(client,order)
    assert refund(client,order)['state']=='refund_pending'
    assert source_state(store,order)==(previous,[])
    assert refund_event(client,order).status_code==200
    assert current(client,order)['state']=='refunded'
    assert refund_event(client,order).status_code==200
    assert_expired_once(store,order,previous)
    assert payments.refunds==1


@pytest.mark.parametrize('entrypoint',['refund','cancel'])
def test_historical_refunded_order_cleans_internal_commitment_without_another_refund(manual,entrypoint):
    client,_,payments,store,order=paid(manual);previous,_=source_state(store,order)
    with store.transaction() as c:
        c.execute("UPDATE orders SET state='refunded',refund_id='re_historical' WHERE id=?",(order['id'],))
        c.execute('DELETE FROM holds WHERE order_id=?',(order['id'],))
    result=refund(client,order) if entrypoint=='refund' else cancel(client,order)
    assert result['state']=='refunded'
    assert_expired_once(store,order,previous)
    assert payments.refunds==0


@pytest.mark.parametrize('cash',[False,True])
def test_other_settled_funds_preserve_commitment_and_review_lock_after_deposit_refund(manual,cash):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    fully_fund(client,order,cash=cash);previous,_=source_state(store,order)
    payments.intents['pi_'+order['id']].update(status='succeeded',amount_capturable=0,amount_received=25000)
    assert pi_succeeded(client,payments,order).status_code==200
    result=refund(client,order)
    assert result['state']=='refunded' and result['funding_summary']['funds_review_required']
    cancel(client,order)
    assert source_state(store,order)==(previous,[])
    with store.connect() as c:
        assert c.execute('SELECT expires_at FROM holds WHERE order_id=?',(order['id'],)).fetchone()[0] is None


@pytest.mark.parametrize('cash',[False,True])
def test_fully_funded_purchase_keeps_source_commitment_when_card_hold_is_released(manual,cash):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    fully_fund(client,order,cash=cash);previous,_=source_state(store,order)
    response=client.post('/api/admin/orders/'+order['id']+'/transition',json=t_body('deposit_paid'),headers=admin())
    assert response.status_code==200 and response.json()['state']=='dealer_confirmed'
    assert source_state(store,order)==(previous,[])
    assert payments.release_calls==1 and payments.refunds==0


def test_unresolved_bank_payment_keeps_source_commitment_for_review(manual):
    client,_,_,store,order=paid(manual);previous,_=source_state(store,order)
    with store.transaction() as c:c.execute("UPDATE orders SET balance_payment_state='ach_processing' WHERE id=?",(order['id'],))
    cancel(client,order);assert refund(client,order)['state']=='refunded'
    assert source_state(store,order)==(previous,[])
