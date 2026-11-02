"""Card authorizations never become deposits until canonical capture is verified."""
from dataclasses import replace
import json
import time
import uuid
from unittest.mock import Mock

import pytest
import stripe
from fastapi.testclient import TestClient

from app.catalog import stock_id_for
from app.main import create_app
from app.payments import StripePayments
from test_transactions import Payments, setup, request, approve, checkout, auth, admin, customer, VIN, t_body


class ManualPayments(Payments):
    def __init__(self):
        super().__init__();self.intents={};self.capture_calls=0;self.release_calls=0
        self.fail_release=False;self.fail_capture=False;self.read_fail=False

    def create_checkout(self,order,quote,expires_at):
        result=super().create_checkout(order,quote,expires_at)
        result['client_reference_id']=order['id'];result['metadata']['vin']=order['vin']
        self.intents[result['payment_intent']]={
            'id':result['payment_intent'],'account':order['payment_account'],'amount':25000,'currency':'usd',
            'livemode':False,'capture_method':'manual','payment_method_types':['card'],
            'metadata':dict(result['metadata']),'status':'requires_payment_method','amount_capturable':0,
            'amount_received':0,'latest_charge':{'payment_method_details':{'card':{'capture_before':int(time.time())+7*86400}}}}
        return result

    def retrieve_payment_intent(self,payment_id,account):
        if self.read_fail:raise RuntimeError('Provider unavailable')
        assert self.intents[payment_id]['account']==account
        return dict(self.intents[payment_id])

    def capture_authorization(self,order):
        self.capture_calls+=1
        if self.fail_capture:raise RuntimeError('Capture unavailable')
        result=self.intents[order['payment_id']]
        result.update(status='succeeded',amount_capturable=0,amount_received=25000)
        return dict(result)

    def release_authorization(self,order):
        self.release_calls+=1
        if self.fail_release:raise RuntimeError('Release unavailable')
        result=self.intents[order['payment_id']]
        result.update(status='canceled',amount_capturable=0,amount_received=0)
        return dict(result)

    def expire_checkout(self,session_id,account):
        session=self.retrieve_checkout(session_id,account)
        if session['status']!='open':raise RuntimeError('Checkout no longer open')
        session.update(status='expired',payment_intent=None)
        return dict(session)


@pytest.fixture
def manual(setup):
    _,settings,_,store=setup
    settings=replace(settings,deposit_capture_method='manual',payment_method_types=('card',))
    payments=ManualPayments();app=create_app(settings,payments)
    return TestClient(app),settings,payments,store


def current(client,order):
    response=client.get('/api/orders/'+order['id'],headers=auth(order))
    assert response.status_code==200,response.text
    return response.json()


def prepared(manual):
    client,settings,payments,store=manual
    body={key:value for key,value in customer().items() if key!='vin'}
    order=request(client,body={**body,'stock_id':stock_id_for(VIN),'phone':'+1 (210) 555-0123'})
    approve(client,order)
    response=checkout(client,order)
    assert response.status_code==200,response.text
    return client,settings,payments,store,order


def authorize(client,payments,order,*,event_id=None,account='acct_fixtureDealer',live=False,session_payment_status='unpaid'):
    session=payments.sessions['cs_test_'+order['id']]
    session.update(status='complete',payment_status=session_payment_status)
    intent=payments.intents[session['payment_intent']]
    intent.update(status='requires_capture',amount_capturable=25000,amount_received=0)
    event={'id':event_id or 'evt_'+str(uuid.uuid4()),'type':'checkout.session.completed','account':account,
           'livemode':live,'data':{'object':{'id':session['id']}}}
    return client.post('/api/stripe/webhook',json=event,headers={'Stripe-Signature':'valid-test-signature'})


def capture(client,order,version=1):
    return client.post('/api/orders/'+order['id']+'/capture-deposit',json={'quote_version':version,'terms_accepted':True},headers=auth(order))


def test_stock_request_and_unpaid_status_do_not_reveal_vin(manual):
    client,_,_,_,order=prepared(manual)
    state=current(client,order)
    assert state['stock_id']==stock_id_for(VIN) and state['masked_vin'].startswith(VIN[:8])
    assert 'vin' not in state and VIN not in json.dumps(state)
    assert state['deposit_status']=='pending' and state['deposit_captured_cents']==0
    assert state['funding_summary']['credited_deposit_cents']==0
    assert client.get('/api/orders/'+order['id']+'/buyers-order',headers=auth(order)).status_code==409


def test_manual_authorize_is_not_paid_or_credited_and_replay_does_not_extend(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order,event_id='evt_same').status_code==200
    first=current(client,order)
    assert first['state']=='deposit_authorized' and first['deposit_status']=='authorized'
    assert first['authorized_cents']==25000 and first['deposit_captured_cents']==0
    assert first['vin']==VIN
    assert first['funding_summary']['credited_deposit_cents']==0
    assert first['funding_summary']['remaining_cents']==first['quote']['total_cents']
    assert authorize(client,payments,order,event_id='evt_same').status_code==200
    assert authorize(client,payments,order).status_code==200
    second=current(client,order)
    assert second['authorization_expires_at']==first['authorization_expires_at']
    assert payments.capture_calls==payments.refunds==0
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM events WHERE kind='deposit_authorized'").fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM events WHERE kind='deposit_paid'").fetchone()[0]==0


def test_checkout_paid_label_never_overrides_canonical_uncaptured_intent(manual):
    client,_,payments,_,order=prepared(manual)
    assert authorize(client,payments,order,session_payment_status='paid').status_code==200
    state=current(client,order)
    assert state['state']=='deposit_authorized' and state['deposit_captured_cents']==0
    assert state['funding_summary']['credited_deposit_cents']==0


def test_authorized_cancel_releases_without_refund_and_replay_is_safe(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    for _ in range(2):
        response=client.post('/api/orders/'+order['id']+'/cancel',json={'reason':'Changed plans'},headers=auth(order))
        assert response.status_code==200,response.text
        assert response.json()['deposit_status']=='released'
    assert payments.release_calls==1 and payments.refunds==0
    assert current(client,order)['funding_summary']['credited_deposit_cents']==0
    with store.connect() as c:assert c.execute('SELECT count(*) FROM holds').fetchone()[0]==0


def test_open_checkout_cancel_prevents_a_later_card_hold(manual):
    client,_,payments,store,order=prepared(manual)
    response=client.post('/api/orders/'+order['id']+'/cancel',json={'reason':'No longer needed'},headers=auth(order))
    assert response.status_code==200,response.text
    assert response.json()['state']=='cancelled'
    assert payments.sessions['cs_test_'+order['id']]['status']=='expired'
    assert payments.release_calls==payments.refunds==0
    with store.connect() as c:assert c.execute('SELECT count(*) FROM holds').fetchone()[0]==0


def test_authorize_capture_then_refund_reconciles_money_once(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    assert capture(client,order,version=2).status_code==409
    result=capture(client,order)
    assert result.status_code==200,result.text
    paid=result.json()
    assert paid['state']=='deposit_paid' and paid['deposit_status']=='paid'
    assert paid['authorized_cents']==0 and paid['deposit_captured_cents']==25000
    assert paid['funding_summary']['credited_deposit_cents']==25000
    assert paid['funding_summary']['remaining_cents']==paid['quote']['total_cents']-25000
    assert capture(client,order).status_code==200 and payments.capture_calls==1
    cancelled=client.post('/api/orders/'+order['id']+'/cancel',json={'reason':'Changed plans'},headers=auth(order))
    assert cancelled.status_code==200 and cancelled.json()['state']=='refund_pending'
    refunded=client.post('/api/admin/orders/'+order['id']+'/refund',json={},headers=admin())
    assert refunded.status_code==200 and refunded.json()['state']=='refunded'
    assert current(client,order)['funding_summary']['credited_deposit_cents']==0
    assert payments.refunds==1 and payments.release_calls==0


def test_expired_authorization_is_released_by_existing_worker(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    with store.transaction() as c:
        c.execute('UPDATE orders SET authorization_expires_at=?,action_due_at=? WHERE id=?',(int(time.time())-1,int(time.time())-1,order['id']))
    response=client.post('/api/admin/refunds/process',json={},headers=admin())
    assert response.status_code==200,response.text
    assert response.json()['authorizations_released']==[order['id']]
    assert current(client,order)['deposit_status']=='released'
    assert payments.release_calls==1 and payments.refunds==0


def test_failed_release_stays_durable_and_blocks_competing_vin(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    payments.fail_release=True
    response=client.post('/api/orders/'+order['id']+'/cancel',json={'reason':'Cancel please'},headers=auth(order))
    assert response.status_code==200 and response.json()['state']=='authorization_release_pending'
    other=client.post('/api/requests',json=customer(),headers={'Idempotency-Key':str(uuid.uuid4())})
    assert other.status_code==409
    payments.fail_release=False
    with store.transaction() as c:c.execute('UPDATE orders SET action_due_at=? WHERE id=?',(int(time.time())-1,order['id']))
    assert current(client,order)['deposit_status']=='released'


def test_cancel_verification_outage_queues_release_without_losing_customer_intent(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    payments.read_fail=True
    response=client.post('/api/orders/'+order['id']+'/cancel',json={'reason':'Cancel please'},headers=auth(order))
    assert response.status_code==200 and response.json()['deposit_status']=='release_pending'
    with store.connect() as c:
        assert c.execute('SELECT count(*) FROM holds').fetchone()[0]==1
        assert c.execute('SELECT authorization_release_reason FROM orders').fetchone()[0]=='cancelled'
    payments.read_fail=False
    with store.transaction() as c:c.execute('UPDATE orders SET action_due_at=? WHERE id=?',(int(time.time())-1,order['id']))
    assert current(client,order)['state']=='cancelled'
    assert payments.release_calls==1 and payments.refunds==0


@pytest.mark.parametrize('field,value',[
    ('amount',24999),('currency','eur'),('livemode',True),('capture_method','automatic'),
    ('amount_capturable',24000),('amount_received',1),('payment_method_types',['us_bank_account']),
    ('metadata',{'order_id':'wrong','quote_version':'1','vin':VIN,'payment_stage':'deposit'}),
])
def test_wrong_canonical_intent_cannot_authorize_or_credit(manual,field,value):
    client,_,payments,_,order=prepared(manual)
    # Authorize helper changes amount fields, so mutate the canonical read separately.
    original=payments.retrieve_payment_intent
    payments.retrieve_payment_intent=lambda *args:{**original(*args),field:value}
    response=authorize(client,payments,order)
    assert response.status_code==409,response.text
    assert current(client,order)['state']=='checkout_pending'
    assert payments.capture_calls==payments.release_calls==payments.refunds==0


@pytest.mark.parametrize('account,live',[('acct_other',False),('acct_fixtureDealer',True)])
def test_wrong_event_scope_cannot_authorize(manual,account,live):
    client,_,payments,_,order=prepared(manual)
    assert authorize(client,payments,order,account=account,live=live).status_code==409
    assert current(client,order)['state']=='checkout_pending'


def test_accepted_quote_document_separates_hold_from_payment(manual):
    client,_,payments,_,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    path='/api/orders/'+order['id']+'/buyers-order'
    assert client.get(path).status_code==404
    response=client.get(path,headers=auth(order))
    assert response.status_code==200 and 'attachment;' in response.headers['Content-Disposition']
    assert VIN in response.text and 'FIXTURE FULFILLING DEALER' in response.text
    assert 'not a payment or a purchase credit' in response.text
    assert '<th>Captured reservation credit</th><td>$0.00</td>' in response.text
    assert 'routing number' not in response.text.lower()
    assert capture(client,order).status_code==200
    assert '<th>Captured reservation credit</th><td>-$250.00</td>' in client.get(path,headers=auth(order)).text


def test_canonical_capture_read_failure_does_not_invent_payment(manual):
    client,_,payments,_,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    payments.fail_capture=True
    assert capture(client,order).status_code==503
    assert current(client,order)['deposit_captured_cents']==0
    payments.fail_capture=False
    assert capture(client,order).status_code==200


def test_sdk_manual_capture_and_release_use_exact_account_and_idempotency(monkeypatch,manual):
    _,settings,_,_=manual
    provider=StripePayments(settings)
    created=Mock(return_value={'id':'cs_test_new'})
    monkeypatch.setattr(stripe.checkout.Session,'create',created)
    order={'id':'order-fixture','vin':VIN,'quote_version':1,'payment_account':'acct_fixtureDealer','payment_id':'pi_fixture','deposit_capture_method':'manual'}
    provider.create_checkout(order,{},int(time.time())+1800)
    params=created.call_args.kwargs
    assert params['payment_intent_data']['capture_method']=='manual'
    assert params['payment_intent_data']['metadata']['order_id']==order['id']
    assert params['payment_method_types']==['card']
    assert VIN not in params['line_items'][0]['price_data']['product_data']['description']
    for name,method in [('capture_authorization','capture'),('release_authorization','cancel')]:
        operation=Mock(return_value={'id':'pi_fixture'});monkeypatch.setattr(stripe.PaymentIntent,method,operation)
        getattr(provider,name)(order)
        assert operation.call_args.args==('pi_fixture',)
        assert operation.call_args.kwargs['stripe_account']=='acct_fixtureDealer'
        assert order['id'] in operation.call_args.kwargs['idempotency_key']


def test_manual_holds_cannot_use_ach_or_unknown_capture_mode(manual):
    _,settings,_,_=manual
    assert not replace(settings,payment_method_types=('us_bank_account',)).payments_ready
    assert not replace(settings,deposit_capture_method='typo').payments_ready


def test_live_manual_checkout_requires_verified_intent_write_permissions(manual):
    _,settings,payments,_=manual
    live=replace(settings,stripe_key='rk_live_fixture',stripe_publishable_key='pk_live_fixture',origin='https://example.test')
    assert not live.payments_ready
    assert replace(live,stripe_authorization_writes_verified=True).payments_ready
    blocked=TestClient(create_app(live,payments))
    checks=blocked.get('/api/admin/integrations',headers=admin()).json()['deposits']
    assert checks['enabled'] is False and 'manual_authorization_write_access' in checks['missing']


def test_capture_and_authorization_permission_gates_do_not_reclassify_legacy_deposits(manual):
    _,settings,_,_=manual
    legacy=replace(settings,deposit_capture_method='automatic',stripe_key='rk_live_fixture',stripe_publishable_key='pk_live_fixture',origin='https://example.test')
    assert legacy.payments_ready


def test_new_stock_reservation_requires_phone_and_one_identity(manual):
    client,_,_,_=manual
    body={key:value for key,value in customer().items() if key!='vin'}
    stock={'stock_id':stock_id_for(VIN)}
    for invalid in [{**body,**stock},{**body,**stock,'phone':'invalid'},
                    {**body,**stock,'vin':VIN,'phone':'+12105550123'}]:
        result=client.post('/api/requests',json=invalid,headers={'Idempotency-Key':str(uuid.uuid4())})
        assert result.status_code==422


def test_changed_seller_or_expired_source_hold_cannot_be_captured(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    with store.transaction() as c:c.execute('UPDATE source_holds SET expires_at=? WHERE order_id=?',(int(time.time())-1,order['id']))
    response=capture(client,order)
    assert response.status_code==409 and payments.capture_calls==0
    assert current(client,order)['funding_summary']['credited_deposit_cents']==0


def test_quote_can_renew_after_provider_confirmed_expiry_release(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    with store.transaction() as c:c.execute('UPDATE orders SET authorization_expires_at=?,action_due_at=? WHERE id=?',(int(time.time())-1,int(time.time())-1,order['id']))
    assert current(client,order)['state']=='quote_expired'
    renewed=approve(client,order)
    assert renewed['quote_version']==2 and renewed['deposit_status']=='unpaid'
    with store.connect() as c:
        row=c.execute('SELECT * FROM orders WHERE id=?',(order['id'],)).fetchone()
        assert row['payment_id'] is None and row['authorization_expires_at'] is None and row['deposit_released_at'] is None


@pytest.mark.parametrize('remaining',[0,24999])
def test_lender_funding_cannot_be_overcharged_by_capturing_hold(manual,remaining):
    client,_,payments,_,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    total=current(client,order)['quote']['total_cents']
    funded=client.post('/api/admin/orders/'+order['id']+'/financing',headers=admin(),json={
        'state':'lender_funded','provider':'Fixture Lender','reference':'lender:actual:'+str(uuid.uuid4()),
        'funded_amount_cents':total-remaining,'quote_version':1})
    assert funded.status_code==200,funded.text
    assert current(client,order)['funding_summary']['remaining_cents']==remaining
    assert capture(client,order).status_code==409 and payments.capture_calls==0


def test_exact_remaining_deposit_can_be_captured_after_lender_funding(manual):
    client,_,payments,_,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    total=current(client,order)['quote']['total_cents']
    funded=client.post('/api/admin/orders/'+order['id']+'/financing',headers=admin(),json={
        'state':'lender_funded','provider':'Fixture Lender','reference':'lender:actual:'+str(uuid.uuid4()),
        'funded_amount_cents':total-25000,'quote_version':1})
    assert funded.status_code==200,funded.text
    result=capture(client,order)
    assert result.status_code==200 and payments.capture_calls==1
    assert result.json()['funding_summary']['remaining_cents']==0
    assert result.json()['funding_summary']['overpaid_cents']==0


def pi_succeeded(client,payments,order,event_id=None):
    session=payments.sessions['cs_test_'+order['id']]
    session.update(status='complete',payment_status='paid')
    return client.post('/api/stripe/webhook',json={
        'id':event_id or 'evt_'+str(uuid.uuid4()),'type':'payment_intent.succeeded',
        'account':'acct_fixtureDealer','livemode':False,'data':{'object':{'id':session['payment_intent']}}},
        headers={'Stripe-Signature':'valid-test-signature'})


def test_late_capture_refund_disposition_survives_distinct_success_replays(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    intent=payments.intents['pi_'+order['id']]
    intent.update(status='succeeded',amount_capturable=0,amount_received=25000)
    with store.transaction() as c:c.execute('UPDATE orders SET authorization_expires_at=?,action_due_at=? WHERE id=?',(int(time.time())-1,int(time.time())-1,order['id']))
    assert current(client,order)['state']=='refund_pending'
    refunded=client.post('/api/admin/orders/'+order['id']+'/refund',json={},headers=admin())
    assert refunded.status_code==200 and refunded.json()['state']=='refunded'
    for _ in range(2):
        assert pi_succeeded(client,payments,order).status_code==200
        assert current(client,order)['state']=='refunded'
    assert payments.refunds==1
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM events WHERE kind='deposit_capture_recorded'").fetchone()[0]==1


def test_unexpected_capture_after_full_lender_funding_requires_refund(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    total=current(client,order)['quote']['total_cents']
    funded=client.post('/api/admin/orders/'+order['id']+'/financing',headers=admin(),json={
        'state':'lender_funded','provider':'Fixture Lender','reference':'lender:actual:'+str(uuid.uuid4()),
        'funded_amount_cents':total,'quote_version':1})
    assert funded.status_code==200
    payments.intents['pi_'+order['id']].update(status='succeeded',amount_capturable=0,amount_received=25000)
    assert pi_succeeded(client,payments,order).status_code==200
    state=current(client,order)
    assert state['state']=='refund_pending' and state['funding_summary']['credited_deposit_cents']==0
    assert payments.capture_calls==0
    refunded=client.post('/api/admin/orders/'+order['id']+'/refund',json={},headers=admin())
    assert refunded.status_code==200 and refunded.json()['state']=='refunded'
    assert refunded.json()['funding_summary']['funds_review_required'] is True
    with store.connect() as c:assert c.execute('SELECT count(*) FROM holds WHERE order_id=?',(order['id'],)).fetchone()[0]==1


def test_source_hold_expiring_during_provider_capture_does_not_credit_deposit(manual,monkeypatch):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    with store.connect() as c:
        q=json.loads(c.execute('SELECT quote FROM orders WHERE id=?',(order['id'],)).fetchone()[0])
    capture_at_provider=payments.capture_authorization
    def delayed_capture(row):
        result=capture_at_provider(row)
        monkeypatch.setattr('app.main.time.time',lambda:q['seller_hold_until']+1)
        return result
    payments.capture_authorization=delayed_capture
    result=capture(client,order)
    assert result.status_code==200,result.text
    assert result.json()['state']=='refund_pending'
    assert result.json()['funding_summary']['credited_deposit_cents']==0
    assert payments.capture_calls==1


def test_expiry_during_canonical_capture_recovery_requires_refund(manual,monkeypatch):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    with store.connect() as c:q=json.loads(c.execute('SELECT quote FROM orders WHERE id=?',(order['id'],)).fetchone()[0])
    original_read=payments.retrieve_payment_intent
    def delayed_read(*args):
        result=original_read(*args)
        result.update(status='succeeded',amount_capturable=0,amount_received=25000)
        monkeypatch.setattr('app.main.time.time',lambda:q['seller_hold_until']+1)
        return result
    payments.retrieve_payment_intent=delayed_read
    result=capture(client,order)
    assert result.status_code==200,result.text
    assert result.json()['state']=='refund_pending' and result.json()['funding_summary']['credited_deposit_cents']==0
    assert payments.capture_calls==0


def fully_fund(client,order,*,cash=False,less=0):
    total=current(client,order)['quote']['total_cents']
    if cash:
        response=client.post('/api/admin/orders/'+order['id']+'/buyer-cash-receipts',headers=admin(),json={
            'currency':'USD','quote_version':1,'dealer_id':'fixture-dealer','amount_cents':total-less,
            'receipt_reference':'cash:actual:'+str(uuid.uuid4()),'evidence_reference':'bank:settled:actual',
            'settled_at':int(time.time()),'settled':True,'excludes_reservation_deposit':True})
    else:
        response=client.post('/api/admin/orders/'+order['id']+'/financing',headers=admin(),json={
            'state':'lender_funded','provider':'Fixture Lender','reference':'lender:actual:'+str(uuid.uuid4()),
            'funded_amount_cents':total-less,'quote_version':1})
    assert response.status_code==200,response.text


@pytest.mark.parametrize('cash',[False,True])
def test_fully_funded_purchase_releases_hold_and_confirms_without_deposit_charge(manual,cash):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    fully_fund(client,order,cash=cash)
    response=client.post('/api/admin/orders/'+order['id']+'/transition',json=t_body('deposit_paid'),headers=admin())
    assert response.status_code==200,response.text
    state=response.json()
    assert state['state']=='dealer_confirmed' and state['deposit_status']=='released'
    assert state['deposit_captured_cents']==state['funding_summary']['credited_deposit_cents']==0
    assert state['funding_summary']['remaining_cents']==0 and not state['funding_summary']['funds_review_required']
    assert payments.capture_calls==payments.refunds==0 and payments.release_calls==1
    with store.connect() as c:
        assert c.execute('SELECT expires_at FROM holds WHERE order_id=?',(order['id'],)).fetchone()[0] is None
        assert c.execute("SELECT count(*) FROM events WHERE kind='deposit_paid'").fetchone()[0]==0


def test_funded_purchase_waits_for_confirmed_hold_release_and_resumes(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    fully_fund(client,order)
    payments.fail_release=True
    response=client.post('/api/admin/orders/'+order['id']+'/transition',json=t_body('deposit_paid'),headers=admin())
    assert response.status_code==202 and response.json()['state']=='authorization_release_pending'
    payments.fail_release=False
    with store.transaction() as c:c.execute('UPDATE orders SET action_due_at=? WHERE id=?',(int(time.time())-1,order['id']))
    assert client.post('/api/admin/refunds/process',json={},headers=admin()).status_code==200
    assert current(client,order)['state']=='funded_reservation'
    response=client.post('/api/admin/orders/'+order['id']+'/transition',json=t_body('deposit_paid'),headers=admin())
    assert response.status_code==200 and response.json()['state']=='dealer_confirmed'
    assert payments.capture_calls==payments.refunds==0


def test_short_funding_or_missing_contract_evidence_cannot_skip_deposit(manual):
    client,_,payments,_,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    fully_fund(client,order,less=1)
    endpoint='/api/admin/orders/'+order['id']+'/transition'
    assert client.post(endpoint,json=t_body('deposit_paid'),headers=admin()).status_code==409
    fully_fund(client,order)
    assert client.post(endpoint,json={'state':'dealer_confirmed','evidence':{'identity_check':'verified:test'}},headers=admin()).status_code==409
    assert payments.release_calls==payments.capture_calls==0


def test_expired_hold_with_settled_bank_funds_preserves_inventory_for_review(manual):
    client,_,payments,store,order=prepared(manual)
    assert authorize(client,payments,order).status_code==200
    fully_fund(client,order,cash=True)
    with store.transaction() as c:c.execute('UPDATE orders SET authorization_expires_at=?,action_due_at=? WHERE id=?',(int(time.time())-1,int(time.time())-1,order['id']))
    state=current(client,order)
    assert state['state']=='payment_review' and state['deposit_status']=='released'
    assert state['funding_summary']['funds_review_required'] is True
    with store.connect() as c:assert c.execute('SELECT count(*) FROM holds WHERE order_id=?',(order['id'],)).fetchone()[0]==1


def test_public_only_checkout_cannot_invent_private_vehicle_mapping(manual,tmp_path):
    _,settings,payments,_=manual
    catalog=tmp_path/'public-only.json'
    catalog.write_text(json.dumps({'items':[{'stock_id':stock_id_for(VIN),'masked_vin':VIN[:8]+'•'*9,'display_price':29000}]}))
    client=TestClient(create_app(replace(settings,inventory_path=catalog),payments))
    assert client.get('/inventory.json').status_code==200
    config=client.get('/api/config').json()
    assert config['payments_enabled'] is False and config['requests_enabled'] is False
    result=client.post('/api/requests',json={**customer(),'vin':VIN},headers={'Idempotency-Key':str(uuid.uuid4())})
    assert result.status_code==404 and payments.session_calls==0


def test_only_public_vehicle_images_can_be_cached_and_head_works(manual,monkeypatch):
    from starlette.responses import Response
    client,_,_,_=manual
    renderer=Mock(side_effect=lambda *a,**k:Response(b'fixture-image',media_type='image/jpeg',headers={'Cache-Control':'public, max-age=3600'}))
    monkeypatch.setattr('app.image_proxy.image_response',renderer)
    path='/api/vehicles/'+stock_id_for(VIN)+'/images/'+'a'*20
    assert client.get(path).headers['Cache-Control']=='public, max-age=3600'
    head=client.head(path)
    assert head.status_code==200 and head.content==b''
    assert client.get('/api/config').headers['Cache-Control']=='no-store'
    assert client.get(path.replace(stock_id_for(VIN),'VV-'+'0'*12)).status_code==404
    assert renderer.call_count==2
