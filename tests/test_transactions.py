from dataclasses import replace
import hashlib,hmac,json,time,uuid
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app,TRANSITIONS
from app.payments import StripePayments

VIN='7G2CEHED5RA040513'
TOKEN='operator-test-only-'+'x'*40

class Payments:
    def __init__(self):self.sessions={};self.refunds=0;self.session_calls=0;self.balance_calls=0;self.fail=False
    def create_checkout(self,order,quote,expires_at):
        if self.fail:raise RuntimeError('network')
        self.session_calls+=1
        sid='cs_test_'+order['id']
        session=dict(account=order['payment_account'],id=sid,client_secret=sid+'_secret_fixture',url='https://checkout.stripe.com/c/pay/'+sid,status='open',payment_status='unpaid',amount_total=25000,currency='usd',mode='payment',livemode=False,payment_intent='pi_'+order['id'],metadata={'order_id':order['id'],'quote_version':str(order['quote_version']),'payment_stage':'deposit'})
        self.sessions[sid]=session;return session
    def create_balance_ach_checkout(self,order,quote,expires_at):
        if self.fail:raise RuntimeError('network')
        self.balance_calls+=1
        sid='cs_bal_'+order['id']+'_'+str(self.balance_calls)
        balance_cents=max(0,quote.total_cents-25000)
        session=dict(account=order['payment_account'],id=sid,client_secret=sid+'_secret_fixture',url='https://checkout.stripe.com/c/pay/'+sid,status='open',payment_status='unpaid',amount_total=balance_cents,currency='usd',mode='payment',livemode=False,payment_intent='pi_bal_'+order['id']+'_'+str(self.balance_calls),metadata={'order_id':order['id'],'quote_version':str(order['quote_version']),'payment_stage':'balance_ach'})
        self.sessions[sid]=session;return session
    def retrieve_checkout(self,sid,account):
        assert self.sessions[sid]['account']==account
        return self.sessions[sid]
    def dealer_can_charge(self,account):return account=='acct_fixtureDealer'
    def verify_event(self,raw,signature):
        if signature!='valid-test-signature':raise ValueError('bad signature')
        return json.loads(raw)
    def refund(self,order):
        self.refunds+=1
        return {'id':'re_'+order['id'],'amount':25000,'payment_intent':order['payment_id'],'status':'succeeded'}

@pytest.fixture
def setup(tmp_path):
    inv=tmp_path/'inventory.json';inv.write_text(json.dumps({'items':[{'vin':VIN,'display_price':29000}]}))
    settings=Settings(db_path=tmp_path/'orders.db',inventory_path=inv,admin_token=TOKEN,
        platform_agreements_verified=True,supported_states=('TX',),checkout_enabled=True,stripe_key='sk_test_fixture',stripe_publishable_key='pk_test_fixture',webhook_secret='whsec_fixture')
    payments=Payments();app=create_app(settings,payments)
    profile=dict(id='fixture-dealer',legal_name='FIXTURE FULFILLING DEALER',license_number='TEST-LICENSE',address='TEST ADDRESS',supported_states=['TX'],stripe_account='acct_fixtureDealer',agreement_reference='agreement:fixture',license_evidence='license:fixture',verified=True)
    with app.state.store.transaction() as db:db.execute('INSERT INTO dealers VALUES(?,?,?)',(profile['id'],json.dumps(profile),int(time.time())))
    return TestClient(app),settings,payments,app.state.store

def customer(vin=VIN):return dict(vin=vin,name='Test Buyer',email='buyer@example.test',state='TX',zip='78201',consent=True)
def request(client,key=None,body=None):
    r=client.post('/api/requests',json=body or customer(),headers={'Idempotency-Key':key or str(uuid.uuid4())});assert r.status_code==201,r.text;return r.json()
def auth(order):return {'Authorization':'Bearer '+order['access_token']}
def admin():return {'Authorization':'Bearer '+TOKEN}
def quote_body(**changes):
    refs={key:'evidence:test-document' for key in ['supplier_commitment_reference','spread_agreement_reference','seller_hold_reference','title_history_reference','lien_payoff_reference','inspection_reference','equipment_reference','recall_reference','tax_quote_reference','carrier_quote_reference']}
    refs.update({key:'https://example.test/terms/'+key for key in ['buyers_guide_reference','warranty_terms_reference','return_terms_reference','deposit_terms_reference']})
    body=dict(dealer_id="fixture-dealer",dealer_vehicle_net_cents=2500000,vehicle_price_cents=2900000,tax_cents=181250,title_registration_cents=15000,documentation_cents=0,delivery_charge_cents=60000,demand_cost_cents=30000,platform_service_cost_cents=35000,platform_risk_reserve_cents=50000,platform_payment_cost_cents=15000,other_platform_cost_cents=0,seller_hold_until=int(time.time())+7200,valid_until=int(time.time())+3600,title_status='clean_verified',condition_status='accepted',recall_disposition='clear',**refs)
    return {**body,**changes}
def approve(client,order,**changes):
    r=client.post(f"/api/admin/orders/{order['id']}/quote",json=quote_body(**changes),headers=admin());assert r.status_code==200,r.text;return r.json()
def checkout(client,order,version=1):
    return client.post(f"/api/orders/{order['id']}/checkout",json={'quote_version':version,'terms_accepted':True},headers=auth(order))
def event(client,payments,order,**changes):
    session=next(s for s in payments.sessions.values() if s['metadata']['order_id']==order['id'])
    session.update(payment_status='paid',status='complete',**changes)
    return client.post('/api/stripe/webhook',json={'id':'evt_'+str(uuid.uuid4()),'type':'checkout.session.completed','account':session['account'],'data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
def status(client,order):return client.get(f"/api/orders/{order['id']}",headers=auth(order)).json()['state']

def record_cash_balance(client,order,amount=None):
    current=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    result=client.post('/api/admin/orders/'+order['id']+'/buyer-cash-receipts',json={
        'currency':'USD','quote_version':current['quote_version'],'dealer_id':'fixture-dealer',
        'amount_cents':amount if amount is not None else current['quote']['balance_after_deposit_cents'],
        'receipt_reference':'cash:fixture:'+str(uuid.uuid4()),'evidence_reference':'bank:settlement:fixture',
        'settled_at':int(time.time()),'settled':True,'excludes_reservation_deposit':True},headers=admin())
    assert result.status_code==200,result.text
    return result.json()


def accept_fixture_transport(client,order):
    now=int(time.time())
    result=client.post('/api/admin/orders/'+order['id']+'/transport',json={
        'state':'carrier_accepted','provider':'Fixture carrier','quote_reference':'fixture:carrier-quote',
        'rate_cents':60000,'quote_expires_at':now+86400,'pickup_window_start':now+3600,
        'pickup_window_end':now+7200,'carrier_acceptance_reference':'fixture:carrier-acceptance'},headers=admin())
    assert result.status_code==200,result.text
    return result.json()

def test_pending_platform_agreements_collect_requests_but_block_transactions(setup):
    _,s,p,_=setup;c=TestClient(create_app(replace(s,platform_agreements_verified=False),p));o=request(c)
    assert c.get('/api/config').json()['partner_onboarding_status']=='pending'
    assert c.post(f"/api/admin/orders/{o['id']}/quote",json=quote_body(),headers=admin()).status_code==409
    assert checkout(c,o).status_code==409

def test_requests_are_idempotent_and_bound_to_body(setup):
    c,_,_,_=setup;key=str(uuid.uuid4());a=request(c,key);b=request(c,key)
    assert (a['id'],a['access_token'])==(b['id'],b['access_token'])
    assert c.post('/api/requests',json={**customer(),'name':'Other Buyer'},headers={'Idempotency-Key':key}).status_code==409

def test_private_order_and_operator_queue_require_auth(setup):
    c,_,_,_=setup;o=request(c)
    assert c.get('/api/orders/'+o['id']).status_code==404
    assert c.get('/api/admin/orders').status_code==401
    assert c.get('/api/admin/orders',headers=admin()).status_code==200
    assert c.get('/.data/orders.db').status_code==404
    assert c.get('/.env').status_code==404

def test_forged_success_url_never_pays(setup):
    c,_,_,_=setup;o=request(c)
    assert c.get('/?reservation=success&vin='+VIN).status_code==200
    assert status(c,o)=='requested'
    assert c.post('/api/stripe/webhook',json={},headers={'Stripe-Signature':'fake'}).status_code==400

def test_quote_requires_documents_supported_state_and_real_margin(setup):
    c,_,_,_=setup;o=request(c)
    assert c.post(f"/api/admin/orders/{o['id']}/quote",json=quote_body(inspection_reference=''),headers=admin()).status_code==422
    assert c.post(f"/api/admin/orders/{o['id']}/quote",json=quote_body(dealer_vehicle_net_cents=2850000),headers=admin()).status_code==409
    other=request(c,body={**customer(),'state':'CA'})
    assert c.post(f"/api/admin/orders/{other['id']}/quote",json=quote_body(),headers=admin()).status_code==409
    assert c.post(f"/api/admin/orders/{o['id']}/quote",json=quote_body(return_terms_reference='internal:file'),headers=admin()).status_code==422

def test_checkout_requires_current_quote_acceptance_and_is_idempotent(setup):
    c,_,p,_=setup;o=request(c)
    assert checkout(c,o).status_code==409
    approve(c,o)
    assert checkout(c,o,2).status_code==409
    assert c.post(f"/api/orders/{o['id']}/checkout",json={'quote_version':1,'terms_accepted':False},headers=auth(o)).status_code==422
    assert checkout(c,o).status_code==200
    assert checkout(c,o).status_code==200
    assert p.session_calls==1

def test_one_vin_cannot_have_two_active_customer_holds(setup):
    c,_,_,_=setup;a=request(c);b=request(c);approve(c,a);approve(c,b)
    assert checkout(c,a).status_code==200
    assert checkout(c,b).status_code==409

def test_signed_verified_payment_advances_once(setup):
    c,_,p,store=setup;o=request(c);approve(c,o);checkout(c,o)
    assert event(c,p,o).status_code==200
    assert event(c,p,o).status_code==200
    assert status(c,o)=='deposit_paid'
    with store.connect() as db:
        assert db.execute("select count(*) from events where kind='deposit_paid'").fetchone()[0]==1
        assert db.execute('select expires_at from holds').fetchone()[0] is None

@pytest.mark.parametrize('changes',[{'amount_total':24999},{'currency':'eur'},{'livemode':True},{'metadata':{'order_id':'wrong','quote_version':'1'}}])
def test_payment_must_match_amount_currency_mode_and_order(setup,changes):
    c,_,p,_=setup;o=request(c);approve(c,o);checkout(c,o)
    assert event(c,p,o,**changes).status_code==409
    assert status(c,o)=='checkout_pending'

def test_payment_after_cancel_is_refund_pending(setup):
    c,_,p,_=setup;o=request(c);approve(c,o);checkout(c,o)
    assert c.post(f"/api/orders/{o['id']}/cancel",json={'reason':'Changed plans'},headers=auth(o)).status_code==200
    assert event(c,p,o).status_code==200
    assert status(c,o)=='refund_pending'

def test_expired_hold_payment_cannot_displace_next_customer(setup):
    c,_,p,store=setup;a=request(c);approve(c,a);checkout(c,a)
    with store.transaction() as db:db.execute('update holds set expires_at=?',(int(time.time())-1,))
    b=request(c);approve(c,b);assert checkout(c,b).status_code==200
    assert event(c,p,a).status_code==200
    assert status(c,a)=='refund_pending'
    with store.connect() as db:assert db.execute('select order_id from holds').fetchone()[0]==b['id']

def test_provider_failure_rolls_back_hold(setup):
    c,_,p,store=setup;o=request(c);approve(c,o);p.fail=True
    assert checkout(c,o).status_code==503
    assert status(c,o)=='quoted'
    with store.connect() as db:assert db.execute('select count(*) from holds').fetchone()[0]==0

def test_refund_retries_do_not_repeat_completed_refund(setup):
    c,_,p,_=setup;o=request(c);approve(c,o);checkout(c,o);event(c,p,o)
    c.post(f"/api/orders/{o['id']}/cancel",json={'reason':'Changed plans'},headers=auth(o))
    assert status(c,o)=='refund_pending'
    for _ in range(2):assert c.post(f"/api/admin/orders/{o['id']}/refund",json={},headers=admin()).status_code==200
    assert status(c,o)=='refunded';assert p.refunds==1

def test_full_fulfillment_requires_evidence_in_order(setup):
    c,_,p,_=setup;o=request(c);approve(c,o);checkout(c,o);event(c,p,o)
    for old,(state,keys) in TRANSITIONS.items():
        if state=='dealer_funded':record_cash_balance(c,o)
        if state=='in_transit':accept_fixture_transport(c,o)
        path=f"/api/admin/orders/{o['id']}/transition"
        assert c.post(path,json={'state':state,'evidence':{'none':'missing'}},headers=admin()).status_code==409
        assert c.post(path,json={'state':state,'evidence':{k:'verified:fixture' for k in keys}},headers=admin()).status_code==200
    assert status(c,o)=='settlement_pending'
    settlement=dict(received_cents=400000,adjustment_cents=0,actual_platform_cost_cents=100000,dealer_statement_reference='dealer:statement',receipt_reference='bank:receipt',adjustment_reference='adjustment:none')
    assert c.post(f"/api/admin/orders/{o['id']}/settle",json=settlement,headers=admin()).status_code==200
    assert status(c,o)=='completed'

def test_origin_protection_and_notification_outbox(setup):
    c,_,_,_=setup
    r=c.post('/api/requests',json=customer(),headers={'Origin':'https://attacker.test','Idempotency-Key':str(uuid.uuid4())});assert r.status_code==403
    o=request(c);events=c.get('/api/admin/outbox',headers=admin()).json();assert events[0]['order_id']==o['id']
    assert c.post(f"/api/admin/outbox/{events[0]['id']}/ack",json={},headers=admin()).status_code==200
    assert c.get('/api/admin/outbox',headers=admin()).json()==[]

def test_privacy_request_and_inactive_lead_retention(setup):
    c,_,_,store=setup;o=request(c)
    assert c.post(f"/api/orders/{o['id']}/privacy",json={},headers=auth(o)).status_code==200
    with store.transaction() as db:db.execute('update orders set updated_at=?',(int(time.time())-100*86400,))
    assert c.post('/api/admin/privacy/purge',json={},headers=admin()).json()['anonymized']==1
    assert c.get('/api/orders/'+o['id'],headers=auth(o)).status_code==404

def test_real_stripe_signature_validation(setup):
    _,s,_,_=setup;provider=StripePayments(s);raw=b'{"id":"evt_test","type":"ping","data":{"object":{}}}'
    stamp=int(time.time());sig=hmac.new(s.webhook_secret.encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    assert provider.verify_event(raw,f't={stamp},v1={sig}')['id']=='evt_test'
    with pytest.raises(Exception):provider.verify_event(raw+b' ',f't={stamp},v1={sig}')

def test_reserved_vin_is_removed_from_live_catalog_and_blocks_new_requests(setup):
    c,_,_,_=setup;o=request(c);approve(c,o);checkout(c,o)
    assert c.get('/inventory.json').json()['items']==[]
    assert c.post('/api/requests',json=customer(),headers={'Idempotency-Key':str(uuid.uuid4())}).status_code==409

def test_source_hold_must_be_reconfirmed_before_further_commitments(setup):
    c,_,p,store=setup;o=request(c);approve(c,o);checkout(c,o);event(c,p,o)
    with store.transaction() as db:db.execute('UPDATE source_holds SET expires_at=?',(int(time.time())-1,))
    rule=TRANSITIONS['deposit_paid'];body={'state':rule[0],'evidence':{k:'verified:fixture' for k in rule[1]}}
    path=f"/api/admin/orders/{o['id']}"
    assert c.post(path+'/transition',json=body,headers=admin()).status_code==409
    assert c.post(path+'/hold',json={'expires_at':int(time.time())+3600,'reference':'seller:new-hold'},headers=admin()).status_code==200
    assert c.post(path+'/transition',json=body,headers=admin()).status_code==200

def test_customer_cases_have_owner_and_resolution_evidence(setup):
    c,_,_,_=setup;o=request(c)
    case=c.post(f"/api/orders/{o['id']}/cases",json={'kind':'title_delay','description':'Please confirm the title processing status.'},headers=auth(o));assert case.status_code==201
    case_id=case.json()['id'];assert c.get('/api/admin/cases',headers=admin()).json()[0]['id']==case_id
    assert c.post('/api/admin/cases/'+case_id,json={'status':'resolved','owner':'Operator','evidence':'title:record-123'},headers=admin()).status_code==200

def test_live_keys_require_https_origin(setup):
    _,s,_,_=setup
    assert not replace(s,stripe_key='sk_live_fixture').payments_ready
    assert replace(s,stripe_key='sk_live_fixture',stripe_publishable_key='pk_live_fixture',origin='https://example.test').payments_ready

def test_verified_operator_recovery_rotates_customer_access(setup):
    c,_,_,_=setup;o=request(c)
    path=f"/api/admin/orders/{o['id']}/access"
    assert c.post(path,json={'verification_reference':'identity:verified'}).status_code==401
    recovery=c.post(path,json={'verification_reference':'identity:verified'},headers=admin());assert recovery.status_code==200
    assert c.get('/api/orders/'+o['id'],headers=auth(o)).status_code==404
    assert c.get('/api/orders/'+o['id'],headers={'Authorization':'Bearer '+recovery.json()['access_token']}).status_code==200

def test_payment_after_checkout_is_disabled_enters_refund_queue(setup):
    c,s,p,_=setup;o=request(c);approve(c,o);checkout(c,o)
    closed=TestClient(create_app(replace(s,checkout_enabled=False),p))
    assert event(closed,p,o).status_code==200
    assert status(closed,o)=='refund_pending'

def test_webhook_cannot_run_without_configured_verification_secret(setup):
    _,s,p,_=setup;c=TestClient(create_app(replace(s,webhook_secret=''),p))
    assert c.post('/api/stripe/webhook',json={'id':'event','type':'ping','data':{'object':{}}},headers={'Stripe-Signature':'valid-test-signature'}).status_code==503

def test_dealer_owns_inventory_and_appears_only_on_accepted_quote(setup):
    c,s,p,_=setup;o=request(c)
    assert not hasattr(s,'dealer_gdn')
    assert c.get('/api/config').json()['mode']=='dealer_fulfillment'
    approved=approve(c,o)
    assert approved['quote']['seller']['legal_name']=='FIXTURE FULFILLING DEALER'
    assert approved['quote']['inventory_owner']=='fulfilling_dealer'
    assert 'dealer_vehicle_net_cents' not in approved['quote']
    assert checkout(c,o).status_code==200
    assert next(iter(p.sessions.values()))['account']=='acct_fixtureDealer'


def test_quote_requires_approved_specific_fulfilling_dealer(setup):
    c,_,_,store=setup;o=request(c)
    assert c.post(f"/api/admin/orders/{o['id']}/quote",json=quote_body(dealer_id='missing-dealer'),headers=admin()).status_code==409
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT profile FROM dealers').fetchone()[0]);profile['verified']=False
        db.execute('UPDATE dealers SET profile=?',(json.dumps(profile),))
    assert c.post(f"/api/admin/orders/{o['id']}/quote",json=quote_body(),headers=admin()).status_code==409


def test_other_dealer_webhook_cannot_confirm_or_expire_order(setup):
    c,_,p,_=setup;o=request(c);approve(c,o);checkout(c,o);session=next(iter(p.sessions.values()))
    for kind in ('checkout.session.completed','checkout.session.expired'):
        response=c.post('/api/stripe/webhook',json={'id':'event-'+kind,'type':kind,'account':'acct_other','data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
        assert response.status_code==409
    assert status(c,o)=='checkout_pending'


def test_spread_is_not_earned_from_deposit_and_requires_settlement(setup):
    c,_,p,_=setup;o=request(c,body={**customer(),'demand_channel':'search','campaign_id':'tesla-y'});approve(c,o);checkout(c,o);event(c,p,o)
    assert c.get('/api/admin/economics',headers=admin()).json()['channels']=={}
    settlement=dict(received_cents=400000,adjustment_cents=0,actual_platform_cost_cents=125000,dealer_statement_reference='dealer:statement',receipt_reference='bank:receipt',adjustment_reference='adjustment:none')
    path=f"/api/admin/orders/{o['id']}/settle"
    assert c.post(path,json=settlement,headers=admin()).status_code==409
    for _,(state,keys) in TRANSITIONS.items():
        if state=='dealer_funded':record_cash_balance(c,o)
        if state=='in_transit':accept_fixture_transport(c,o)
        assert c.post(f"/api/admin/orders/{o['id']}/transition",json={'state':state,'evidence':{key:'evidence:dealer' for key in keys}},headers=admin()).status_code==200
    assert c.post(path,json={**settlement,'received_cents':399999},headers=admin()).status_code==409
    assert c.post(path,json=settlement,headers=admin()).status_code==200
    assert c.post(path,json=settlement,headers=admin()).status_code==200
    stats=c.get('/api/admin/economics',headers=admin()).json()['channels']['search'];assert stats['contribution_cents']==275000
    reversal={'amount_cents':100000,'reference':'return:clawback-1'}
    for _ in range(2):assert c.post(f"/api/admin/orders/{o['id']}/settlement-reversal",json=reversal,headers=admin()).status_code==200
    stats=c.get('/api/admin/economics',headers=admin()).json()['channels']['search'];assert stats['net_spread_cents']==300000 and stats['contribution_cents']==175000


def test_old_resale_order_is_quarantined_without_becoming_dealer_owned(setup):
    c,s,p,store=setup;o=request(c)
    with store.transaction() as db:
        db.execute("UPDATE orders SET workflow_model='legacy_resale',state='purchased',quote=? WHERE id=?",(json.dumps({'acquisition_cents':2500000}),o['id']))
    migrated=TestClient(create_app(s,p))
    r=migrated.get('/api/orders/'+o['id'],headers=auth(o)).json()
    assert r['state']=='model_review' and r['quote'] is None
    assert migrated.post(f"/api/admin/orders/{o['id']}/refund",json={},headers=admin()).status_code==409


def test_private_supplier_terms_need_operator_auth(setup):
    c,s,_,_=setup
    s.sourcing_path.parent.mkdir(exist_ok=True)
    # This fixture uses a private temporary file, not the actual source snapshot.
    from dataclasses import replace
    path=s.db_path.parent/'suppliers.json';path.write_text(json.dumps({'items':[{'vin':VIN,'dealer_name':'Private Dealer','asking_price':25000,'source_url':'https://private.test/car'}]}))
    private=TestClient(create_app(replace(s,sourcing_path=path)))
    assert private.get('/api/admin/sourcing').status_code==401
    assert private.get('/api/admin/sourcing',headers=admin()).json()['items'][0]['asking_price']==25000
    assert private.get('/data/source_snapshot.json').status_code==404
    assert private.get('/.data/source_snapshot.json').status_code==404


def test_real_payment_adapter_scopes_deposit_and_refund_to_dealer(setup,monkeypatch):
    _,s,_,_=setup;provider=StripePayments(s);calls=[]
    import stripe
    monkeypatch.setattr(stripe.checkout.Session,'create',lambda **kw:calls.append(kw) or {'id':'cs_fixture'})
    order={'id':'fixture-order','vin':VIN,'quote_version':1,'payment_account':'acct_fixtureDealer','payment_id':'pi_fixture'}
    provider.create_checkout(order,quote_body(),int(time.time())+1800)
    assert calls[0]['stripe_account']=='acct_fixtureDealer'
    assert 'application_fee_amount' not in calls[0].get('payment_intent_data',{})
    monkeypatch.setattr(stripe.Refund,'create',lambda **kw:calls.append(kw) or {'id':'re_fixture'})
    provider.refund(order);assert calls[-1]['stripe_account']=='acct_fixtureDealer'

def test_dealer_revocation_routes_late_deposit_to_refund_review(setup):
    c,_,p,store=setup;o=request(c);approve(c,o);checkout(c,o)
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT profile FROM dealers').fetchone()[0]);profile['verified']=False
        db.execute('UPDATE dealers SET profile=?',(json.dumps(profile),))
    assert event(c,p,o).status_code==200
    assert status(c,o)=='refund_pending'


def test_provider_capability_is_checked_before_dealer_deposit(setup):
    c,_,p,store=setup;o=request(c);approve(c,o)
    p.dealer_can_charge=lambda account:False
    assert checkout(c,o).status_code==409
    with store.connect() as db:assert db.execute('SELECT count(*) FROM holds').fetchone()[0]==0

@pytest.mark.parametrize('change',[{'supported_states':['CA']},{'legal_name':'DIFFERENT LEGAL SELLER'}])
def test_checkout_cannot_ignore_changed_seller_or_destination_authority(setup,change):
    c,_,_,store=setup;o=request(c);approve(c,o)
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT profile FROM dealers').fetchone()[0]);profile.update(change)
        db.execute('UPDATE dealers SET profile=?',(json.dumps(profile),))
    assert checkout(c,o).status_code==409

def test_online_purchase_steps_are_dealer_bound_and_do_not_fake_completion(setup):
    c,_,p,store=setup;o=request(c);approve(c,o)
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT profile FROM dealers').fetchone()[0]);profile['online_portal_hosts']=['secure.example.test']
        db.execute('UPDATE dealers SET profile=?',(json.dumps(profile),))
    path=f"/api/admin/orders/{o['id']}/online-actions"
    action={'kind':'sign_contract','url':'https://secure.example.test/sign/123','evidence_reference':'provider:contract'}
    assert c.post(path,json=action,headers=admin()).status_code==409
    checkout(c,o);event(c,p,o)
    assert c.post(path,json={**action,'url':'https://wrong.example.test/sign'},headers=admin()).status_code==409
    assert c.post(path,json=action,headers=admin()).status_code==200
    response=c.get('/api/orders/'+o['id'],headers=auth(o)).json()
    assert response['online_actions'][0]['kind']=='sign_contract'
    assert response['state']=='deposit_paid'


def test_embedded_checkout_requires_matching_public_key(setup):
    _,settings,_,_=setup
    assert not replace(settings,stripe_publishable_key='').payments_ready
    assert not replace(settings,stripe_publishable_key='pk_live_wrong_mode').payments_ready
    assert not replace(settings,checkout_ui_mode='invalid').payments_ready


def test_embedded_checkout_secret_is_authenticated_and_reused(setup):
    client,_,payments,_=setup;order=request(client);approve(client,order)
    assert client.post(f"/api/orders/{order['id']}/checkout",json={'quote_version':1,'terms_accepted':True}).status_code==404
    first=checkout(client,order);second=checkout(client,order)
    assert first.status_code==second.status_code==200
    assert first.json()==second.json()
    assert first.json()['mode']=='embedded_page'
    assert first.json()['account']=='acct_fixtureDealer'
    assert first.json()['publishable_key']=='pk_test_fixture'
    assert first.json()['client_secret'].endswith('_secret_fixture')
    assert 'url' not in first.json() and payments.session_calls==1
    assert status(client,order)=='checkout_pending'
    public_order=client.get(f"/api/orders/{order['id']}",headers=auth(order)).json()
    assert 'client_secret' not in json.dumps(public_order)


def test_embedded_provider_does_not_redirect_or_charge_spread_on_deposit(setup,monkeypatch):
    _,settings,_,_=setup;calls=[]
    import stripe
    monkeypatch.setattr(stripe.checkout.Session,'create',lambda **kw:calls.append(kw) or {'id':'cs_fixture'})
    StripePayments(settings).create_checkout({'id':'fixture','vin':VIN,'quote_version':1,'payment_account':'acct_fixtureDealer'},quote_body(),int(time.time())+1800)
    params=calls[0]
    assert params['ui_mode']=='embedded_page' and params['redirect_on_completion']=='never'
    assert 'success_url' not in params and 'cancel_url' not in params
    assert params['line_items'][0]['price_data']['unit_amount']==25000
    assert 'application_fee_amount' not in params.get('payment_intent_data',{})


def test_stripe_ach_and_card_payment_methods_and_balance_ach(setup,monkeypatch):
    client,settings,payments,_=setup;calls=[]
    import stripe
    monkeypatch.setattr(stripe.checkout.Session,'create',lambda **kw:calls.append(kw) or {'id':'cs_fixture'})
    provider=StripePayments(settings)
    order={'id':'fixture','vin':VIN,'quote_version':1,'payment_account':'acct_fixtureDealer'}
    q=quote_body()
    provider.create_checkout(order,q,int(time.time())+1800)
    assert calls[0]['payment_method_types']==['card']
    assert 'payment_method_options' not in calls[0]
    ach_provider=StripePayments(replace(settings,payment_method_types=('card','us_bank_account')))
    ach_provider.create_checkout(order,q,int(time.time())+1800)
    assert calls[1]['payment_method_types']==['card','us_bank_account']
    assert calls[1]['payment_method_options']['us_bank_account']['financial_connections']['permissions']==['payment_method']
    from app.models import Quote
    parsed_q=Quote.model_validate(q)
    provider.create_balance_ach_checkout(order,parsed_q,int(time.time())+1800)
    assert calls[2]['payment_method_types']==['us_bank_account']
    assert calls[2]['line_items'][0]['price_data']['unit_amount']==parsed_q.total_cents-25000
    cfg=client.get('/api/config').json()
    assert cfg['ach_enabled'] is True and cfg['payment_methods']==['card'] and cfg['balance_payment_methods']==['us_bank_account']
    o=request(client);approve(client,o);checkout(client,o)
    session=next(s for s in payments.sessions.values() if s['metadata']['order_id']==o['id'])
    res=client.post('/api/stripe/webhook',json={'id':'evt_ach_fail','type':'checkout.session.async_payment_failed','account':session['account'],'data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert res.status_code==200 and status(client,o)=='quote_expired'


def t_body(old):
    state,keys=TRANSITIONS[old]
    return {'state':state,'evidence':{k:'verified:fixture' for k in keys}}


def test_delayed_bank_deposit_processing_and_settlement(setup):
    client,_,payments,_=setup
    o=request(client);approve(client,o);checkout(client,o)
    session=next(s for s in payments.sessions.values() if s['metadata']['order_id']==o['id'])
    session.update(status='complete',payment_status='unpaid')
    res=client.post('/api/stripe/webhook',json={'id':'evt_dep_pending','type':'checkout.session.completed','account':session['account'],'data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert res.status_code==200 and status(client,o)=='deposit_processing'
    # Cannot transition to dealer_confirmed while deposit is still processing
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('deposit_paid'),headers=admin()).status_code==409
    session.update(status='complete',payment_status='paid')
    res2=client.post('/api/stripe/webhook',json={'id':'evt_dep_paid','type':'checkout.session.async_payment_succeeded','account':session['account'],'data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert res2.status_code==200 and status(client,o)=='deposit_paid'


def test_balance_ach_checkout_idempotency_delayed_settlement_and_guards(setup):
    client,_,payments,_=setup
    o=request(client);approve(client,o);checkout(client,o);event(client,payments,o)
    assert status(client,o)=='deposit_paid'
    # Balance checkout not allowed before dealer_confirmed
    assert client.post(f"/api/orders/{o['id']}/balance-checkout",json={'quote_version':1,'terms_accepted':True},headers=auth(o)).status_code==409
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('deposit_paid'),headers=admin()).status_code==200
    b1=client.post(f"/api/orders/{o['id']}/balance-checkout",json={'quote_version':1,'terms_accepted':True},headers=auth(o))
    b2=client.post(f"/api/orders/{o['id']}/balance-checkout",json={'quote_version':1,'terms_accepted':True},headers=auth(o))
    assert b1.status_code==b2.status_code==200 and b1.json()==b2.json() and payments.balance_calls==1
    pub=client.get(f"/api/orders/{o['id']}",headers=auth(o)).json()
    assert pub['balance_payment_state']=='checkout_open'
    bal_session=payments.sessions['cs_bal_'+o['id']+'_1']
    # Bank linked, ACH initiated (payment_status == 'unpaid'): must NOT release vehicle or allow dealer_funded
    bal_session.update(status='complete',payment_status='unpaid')
    w1=client.post('/api/stripe/webhook',json={'id':'evt_bal_pending','type':'checkout.session.completed','account':bal_session['account'],'data':{'object':{'id':bal_session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert w1.status_code==200
    assert client.get(f"/api/orders/{o['id']}",headers=auth(o)).json()['balance_payment_state']=='ach_processing'
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_confirmed'),headers=admin()).status_code==409
    # Simulate ACH failure -> resets balance_checkout_id so buyer can retry
    w_fail=client.post('/api/stripe/webhook',json={'id':'evt_bal_fail','type':'checkout.session.async_payment_failed','account':bal_session['account'],'data':{'object':{'id':bal_session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert w_fail.status_code==200
    assert client.get(f"/api/orders/{o['id']}",headers=auth(o)).json()['balance_payment_state']=='failed'
    b3=client.post(f"/api/orders/{o['id']}/balance-checkout",json={'quote_version':1,'terms_accepted':True},headers=auth(o))
    assert b3.status_code==200 and payments.balance_calls==2
    bal_session_2=payments.sessions['cs_bal_'+o['id']+'_2']
    bal_session_2.update(status='complete',payment_status='paid')
    w_paid=client.post('/api/stripe/webhook',json={'id':'evt_bal_paid','type':'checkout.session.async_payment_succeeded','account':bal_session_2['account'],'data':{'object':{'id':bal_session_2['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert w_paid.status_code==200
    assert client.get(f"/api/orders/{o['id']}",headers=auth(o)).json()['balance_payment_state']=='paid'
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_confirmed'),headers=admin()).status_code==200


def test_partner_financing_prequalification_cannot_unlock_dealer_funded(setup):
    client,_,payments,_=setup
    o=request(client,body={**customer(),'payment_preference':'partner_financing'})
    assert o['payment_preference']=='partner_financing'
    approve(client,o);checkout(client,o);event(client,payments,o)
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('deposit_paid'),headers=admin()).status_code==200
    # Prequalified is NOT funded proceeds
    r_pre=client.post(f"/api/admin/orders/{o['id']}/financing",json={'state':'prequalified','provider':'Partner Credit Union','reference':'evidence:prequal','approved_amount_cents':2875000},headers=admin())
    assert r_pre.status_code==200 and r_pre.json()['financing']['state']=='prequalified'
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_confirmed'),headers=admin()).status_code==409
    # Conditional approval is NOT funded proceeds
    r_cond=client.post(f"/api/admin/orders/{o['id']}/financing",json={'state':'conditional_approval','provider':'Partner Credit Union','reference':'evidence:cond','stipulations':['proof_of_income']},headers=admin())
    assert r_cond.status_code==200
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_confirmed'),headers=admin()).status_code==409
    # Settled lender proceeds must cover the complete balance before dealer_funded
    r_funded=client.post(f"/api/admin/orders/{o['id']}/financing",json={'state':'lender_funded','provider':'Partner Credit Union','reference':'evidence:wire-settled','funded_amount_cents':3131250},headers=admin())
    assert r_funded.status_code==200 and r_funded.json()['financing']['state']=='lender_funded'
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_confirmed'),headers=admin()).status_code==200


def test_transport_rate_quote_cannot_unlock_in_transit(setup):
    client,_,payments,_=setup
    o=request(client);approve(client,o);checkout(client,o);event(client,payments,o)
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('deposit_paid'),headers=admin()).status_code==200
    record_cash_balance(client,o)
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_confirmed'),headers=admin()).status_code==200
    now=int(time.time())
    # Carrier rate quote alone cannot unlock in_transit
    r_quote=client.post(f"/api/admin/orders/{o['id']}/transport",json={'state':'quoted','provider':'Montway Auto Transport','quote_reference':'evidence:rate-quote','rate_cents':60000,'quote_expires_at':now+86400},headers=admin())
    assert r_quote.status_code==200 and r_quote.json()['transport']['state']=='quoted'
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_funded'),headers=admin()).status_code==409
    # Carrier acceptance requires carrier_acceptance_reference + pickup window, and unlocks in_transit
    r_accept=client.post(f"/api/admin/orders/{o['id']}/transport",json={'state':'carrier_accepted','provider':'Montway Auto Transport','quote_reference':'evidence:rate-quote','rate_cents':60000,'quote_expires_at':now+86400,'pickup_window_start':now+3600,'pickup_window_end':now+86400,'delivery_window_start':now+86400,'delivery_window_end':now+172800,'carrier_acceptance_reference':'dispatch:montway-123'},headers=admin())
    assert r_accept.status_code==200 and r_accept.json()['transport']['state']=='carrier_accepted'
    assert client.post(f"/api/admin/orders/{o['id']}/transition",json=t_body('dealer_funded'),headers=admin()).status_code==200


@pytest.mark.parametrize('first_kind,late_kind',[
    ('checkout.session.async_payment_succeeded','checkout.session.completed'),
    ('checkout.session.completed','checkout.session.async_payment_succeeded'),
])
def test_distinct_deposit_success_events_preserve_advanced_order(setup,first_kind,late_kind):
    client,_,payments,store=setup
    order=request(client);approve(client,order);assert checkout(client,order).status_code==200
    session=next(iter(payments.sessions.values()))
    session.update(status='complete',payment_status='paid')
    def deliver(event_id,kind):
        return client.post('/api/stripe/webhook',json={'id':event_id,'type':kind,'account':session['account'],
            'data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert deliver('evt_first_success',first_kind).status_code==200
    keys=TRANSITIONS['deposit_paid'][1]
    assert client.post(f"/api/admin/orders/{order['id']}/transition",json={'state':'dealer_confirmed',
        'evidence':{key:'verified:fixture' for key in keys}},headers=admin()).status_code==200
    assert deliver('evt_distinct_late_success',late_kind).status_code==200
    assert status(client,order)=='dealer_confirmed'
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE order_id=? AND kind='deposit_paid'",(order['id'],)).fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM stripe_events WHERE id IN ('evt_first_success','evt_distinct_late_success')").fetchone()[0]==2
        assert db.execute('SELECT expires_at FROM holds WHERE order_id=?',(order['id'],)).fetchone()[0] is None


def test_distinct_deposit_success_does_not_reopen_completed_refund(setup):
    client,_,payments,store=setup
    order=request(client);approve(client,order);checkout(client,order);assert event(client,payments,order).status_code==200
    assert client.post(f"/api/orders/{order['id']}/cancel",json={'reason':'Cancel test purchase'},headers=auth(order)).status_code==200
    assert client.post(f"/api/admin/orders/{order['id']}/refund",json={},headers=admin()).status_code==200
    assert status(client,order)=='refunded'
    assert event(client,payments,order).status_code==200
    assert status(client,order)=='refunded'
    assert payments.refunds==1


@pytest.mark.parametrize('mismatch',['amount','account','payment'])
def test_distinct_deposit_success_still_validates_provider_data(setup,mismatch):
    client,_,payments,_=setup
    order=request(client);approve(client,order);checkout(client,order);assert event(client,payments,order).status_code==200
    session=next(iter(payments.sessions.values()))
    if mismatch=='amount':session['amount_total']=24999
    if mismatch=='account':session['account']='acct_other'
    if mismatch=='payment':session['payment_intent']='pi_different'
    assert event(client,payments,order).status_code==409
    assert status(client,order)=='deposit_paid'


def test_first_paid_event_after_processing_expiry_still_requires_refund(setup):
    client,_,payments,store=setup
    order=request(client);approve(client,order);checkout(client,order)
    session=next(iter(payments.sessions.values()))
    session.update(status='complete',payment_status='unpaid')
    pending=client.post('/api/stripe/webhook',json={'id':'evt_initial_processing','type':'checkout.session.completed',
        'account':session['account'],'data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
    assert pending.status_code==200 and status(client,order)=='deposit_processing'
    with store.transaction() as db:
        q=json.loads(db.execute('SELECT quote FROM orders WHERE id=?',(order['id'],)).fetchone()[0])
        q['valid_until']=int(time.time())-1
        db.execute('UPDATE orders SET quote=? WHERE id=?',(json.dumps(q),order['id']))
    assert event(client,payments,order).status_code==200
    assert status(client,order)=='refund_pending'
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE order_id=? AND kind='deposit_paid'",(order['id'],)).fetchone()[0]==0


def test_auto_refund_on_cancel_and_durable_refund_worker_with_pending_webhook(tmp_path):
    inv=tmp_path/'inventory.json'
    inv.write_text(json.dumps({'items':[{'vin':VIN,'year':2023,'model':'Model Y','trim':'Long Range AWD','mileage':18500,'display_price':29000,'reference_price':30200,'reference_sample':8,'benchmark_date':'2026-10-31','photo':'https://example.test/car.jpg','city':'Austin','state':'TX'}]}))
    settings=Settings(db_path=tmp_path/'orders.db',inventory_path=inv,admin_token=TOKEN,
        platform_agreements_verified=True,supported_states=('TX',),checkout_enabled=True,
        stripe_key='sk_test_fixture',stripe_publishable_key='pk_test_fixture',webhook_secret='whsec_fixture',
        auto_refund_enabled=True)
    payments=Payments()
    app=create_app(settings,payments)
    profile=dict(id='fixture-dealer',legal_name='FIXTURE FULFILLING DEALER',license_number='TEST-LICENSE',
        address='TEST ADDRESS',supported_states=['TX'],stripe_account='acct_fixtureDealer',
        agreement_reference='agreement:fixture',license_evidence='license:fixture',verified=True)
    with app.state.store.transaction() as db:
        db.execute('INSERT INTO dealers VALUES(?,?,?)',(profile['id'],json.dumps(profile),int(time.time())))
    client=TestClient(app)

    # Case 1: Immediate succeeded refund on customer cancel
    o1=request(client);q1=approve(client,o1);checkout(client,o1);assert event(client,payments,o1).status_code==200
    assert q1['vehicle']['model']=='Model Y'
    assert q1['quote']['vehicle_savings_cents']==120000
    assert q1['quote']['balance_after_deposit_cents']==q1['quote']['total_cents']-25000
    c1=client.post(f"/api/orders/{o1['id']}/cancel",json={'reason':'Immediate auto refund'},headers=auth(o1))
    assert c1.status_code==200 and c1.json()['state']=='refunded' and c1.json()['refund_submitted'] is True

    # Case 2: Transient provider failure on cancel stays refund_pending, then durable worker retries; pending status waits for webhook
    o2=request(client);approve(client,o2);checkout(client,o2);assert event(client,payments,o2).status_code==200
    def fail_refund(order):raise RuntimeError('provider timeout')
    payments.refund=fail_refund
    c2=client.post(f"/api/orders/{o2['id']}/cancel",json={'reason':'Transient failure'},headers=auth(o2))
    assert c2.status_code==200 and c2.json()['state']=='refund_pending' and c2.json()['refund_submitted'] is False

    # Worker retries when provider returns status='pending': stores refund_id, keeps refund_pending, does not double-submit
    pending_calls=[]
    def pending_refund(order):
        pending_calls.append(order['id'])
        return {'id':'re_pending_'+order['id'],'amount':25000,'payment_intent':order['payment_id'],'status':'pending'}
    payments.refund=pending_refund
    w1=client.post('/api/admin/refunds/process',json={},headers=admin())
    assert w1.status_code==200 and w1.json()['pending']==[o2['id']]
    assert status(client,o2)=='refund_pending'
    assert client.get(f"/api/orders/{o2['id']}",headers=auth(o2)).json()['refund_submitted'] is True
    # Calling admin refund or worker again while refund_id is already pending does not create a duplicate refund
    assert client.post(f"/api/admin/orders/{o2['id']}/refund",json={},headers=admin()).status_code==200
    assert client.post('/api/admin/refunds/process',json={},headers=admin()).json()['processed']==0
    assert len(pending_calls)==1

    # Webhook refund.updated marks order refunded
    pi='pi_'+o2['id']
    rw=client.post('/api/stripe/webhook',json={'id':'evt_refund_settled','type':'refund.updated','account':'acct_fixtureDealer',
        'data':{'object':{'id':'re_pending_'+o2['id'],'payment_intent':pi,'amount':25000,'status':'succeeded'}}},
        headers={'Stripe-Signature':'valid-test-signature'})
    assert rw.status_code==200 and status(client,o2)=='refunded'


def test_financing_application_url_and_transport_tracking_url_require_https(setup):
    client,_,payments,store=setup
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT profile FROM dealers').fetchone()[0]);profile['online_portal_hosts']=['lender.example.test']
        db.execute('UPDATE dealers SET profile=?',(json.dumps(profile),))
    o=request(client,body={**customer(),'payment_preference':'partner_financing'})
    approve(client,o);checkout(client,o);event(client,payments,o)
    assert client.post(f"/api/admin/orders/{o['id']}/financing",json={'state':'prequalified','provider':'Partner Credit Union','reference':'evidence:prequal','approved_amount_cents':2875000,'application_url':'http://insecure.example.test/apply'},headers=admin()).status_code==422
    r_fin=client.post(f"/api/admin/orders/{o['id']}/financing",json={'state':'prequalified','provider':'Partner Credit Union','reference':'evidence:prequal','approved_amount_cents':2875000,'application_url':'https://lender.example.test/apply/123'},headers=admin())
    assert r_fin.status_code==200 and r_fin.json()['financing']['application_url']=='https://lender.example.test/apply/123'
    now=int(time.time())
    assert client.post(f"/api/admin/orders/{o['id']}/transport",json={'state':'quoted','provider':'Montway','quote_reference':'evidence:rate','rate_cents':60000,'quote_expires_at':now+86400,'tracking_url':'http://insecure.example.test/track'},headers=admin()).status_code==422
    r_tr=client.post(f"/api/admin/orders/{o['id']}/transport",json={'state':'quoted','provider':'Montway','quote_reference':'evidence:rate','rate_cents':60000,'quote_expires_at':now+86400,'tracking_url':'https://carrier.example.test/track/123'},headers=admin())
    assert r_tr.status_code==200 and r_tr.json()['transport']['tracking_url']=='https://carrier.example.test/track/123'


def test_lender_application_can_be_ready_without_claiming_prequalification(setup):
    client,_,payments,store=setup
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT profile FROM dealers').fetchone()[0]);profile['online_portal_hosts']=['lender.example.test']
        db.execute('UPDATE dealers SET profile=?',(json.dumps(profile),))
    order=request(client,body={**customer(),'payment_preference':'partner_financing'})
    approve(client,order)
    endpoint=f"/api/admin/orders/{order['id']}/financing"
    body={'state':'application_ready','provider':'Fixture lender','reference':'approved-hosted-session-fixture','application_url':'https://lender.example.test/apply/fixture'}
    assert client.post(endpoint,json=body).status_code==401
    assert client.post(endpoint,json={**body,'application_url':'https://unapproved.example.test/apply'},headers=admin()).status_code==409
    assert client.post(endpoint,json={**body,'application_url':''},headers=admin()).status_code==422
    assert client.post(endpoint,json={**body,'approved_amount_cents':100},headers=admin()).status_code==422
    result=client.post(endpoint,json=body,headers=admin())
    assert result.status_code==200,result.text
    finance=result.json()['financing']
    assert finance['state']=='application_ready' and finance['approved_amount_cents']==0 and finance['funded_amount_cents']==0
    assert result.json()['state']=='quoted'
    assert payments.session_calls==0 and payments.balance_calls==0
    result=client.post(endpoint,json={**body,'state':'application_submitted','reference':'actual-provider-submission-fixture'},headers=admin())
    assert result.status_code==200 and result.json()['financing']['state']=='application_submitted'
    assert payments.session_calls==0
