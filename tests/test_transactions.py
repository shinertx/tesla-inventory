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
    def __init__(self):self.sessions={};self.refunds=0;self.session_calls=0;self.fail=False
    def create_checkout(self,order,quote,expires_at):
        if self.fail:raise RuntimeError('network')
        self.session_calls+=1
        sid='cs_test_'+order['id']
        session=dict(id=sid,url='https://checkout.stripe.com/c/pay/'+sid,status='open',payment_status='unpaid',amount_total=25000,currency='usd',mode='payment',livemode=False,payment_intent='pi_'+order['id'],metadata={'order_id':order['id'],'quote_version':str(order['quote_version'])})
        self.sessions[sid]=session;return session
    def retrieve_checkout(self,sid):return self.sessions[sid]
    def verify_event(self,raw,signature):
        if signature!='valid-test-signature':raise ValueError('bad signature')
        return json.loads(raw)
    def refund(self,order):
        self.refunds+=1
        return {'id':'re_'+order['id'],'amount':25000,'payment_intent':order['payment_id'],'status':'succeeded'}

@pytest.fixture
def setup(tmp_path):
    inv=tmp_path/'inventory.json';inv.write_text(json.dumps({'items':[{'vin':VIN}]}))
    settings=Settings(db_path=tmp_path/'orders.db',inventory_path=inv,admin_token=TOKEN,
        dealer_name='TEST FIXTURE DEALER',dealer_gdn='TEST-ONLY',dealer_address='TEST ONLY',dealer_license_evidence='fixture:test',dealer_verified=True,supported_states=('TX',),checkout_enabled=True,stripe_key='sk_test_fixture',webhook_secret='whsec_fixture')
    payments=Payments();app=create_app(settings,payments)
    return TestClient(app),settings,payments,app.state.store

def customer(vin=VIN):return dict(vin=vin,name='Test Buyer',email='buyer@example.test',state='TX',zip='78201',consent=True)
def request(client,key=None,body=None):
    r=client.post('/api/requests',json=body or customer(),headers={'Idempotency-Key':key or str(uuid.uuid4())});assert r.status_code==201,r.text;return r.json()
def auth(order):return {'Authorization':'Bearer '+order['access_token']}
def admin():return {'Authorization':'Bearer '+TOKEN}
def quote_body(**changes):
    refs={key:'evidence:test-document' for key in ['seller_hold_reference','title_history_reference','lien_payoff_reference','inspection_reference','equipment_reference','recall_reference','tax_quote_reference','carrier_quote_reference']}
    refs.update({key:'https://example.test/terms/'+key for key in ['buyers_guide_reference','warranty_terms_reference','return_terms_reference','deposit_terms_reference']})
    body=dict(acquisition_cents=2500000,vehicle_price_cents=2900000,tax_cents=181250,title_registration_cents=15000,documentation_cents=0,delivery_charge_cents=60000,transport_cost_cents=60000,inspection_recon_cents=35000,warranty_return_reserve_cents=50000,acquisition_marketing_cents=30000,other_cost_cents=15000,seller_hold_until=int(time.time())+7200,valid_until=int(time.time())+3600,title_status='clean_verified',condition_status='accepted',recall_disposition='clear',**refs)
    return {**body,**changes}
def approve(client,order,**changes):
    r=client.post(f"/api/admin/orders/{order['id']}/quote",json=quote_body(**changes),headers=admin());assert r.status_code==200,r.text;return r.json()
def checkout(client,order,version=1):
    return client.post(f"/api/orders/{order['id']}/checkout",json={'quote_version':version,'terms_accepted':True},headers=auth(order))
def event(client,payments,order,**changes):
    session=next(s for s in payments.sessions.values() if s['metadata']['order_id']==order['id'])
    session.update(payment_status='paid',status='complete',**changes)
    return client.post('/api/stripe/webhook',json={'id':'evt_'+str(uuid.uuid4()),'type':'checkout.session.completed','data':{'object':{'id':session['id']}}},headers={'Stripe-Signature':'valid-test-signature'})
def status(client,order):return client.get(f"/api/orders/{order['id']}",headers=auth(order)).json()['state']

def test_pending_license_collects_requests_but_blocks_quotes_and_payment(setup):
    _,s,p,_=setup;c=TestClient(create_app(replace(s,dealer_verified=False),p));o=request(c)
    assert c.get('/api/config').json()['license_status']=='pending'
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
    assert c.post(f"/api/admin/orders/{o['id']}/quote",json=quote_body(acquisition_cents=2950000),headers=admin()).status_code==409
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
        path=f"/api/admin/orders/{o['id']}/transition"
        assert c.post(path,json={'state':state,'evidence':{'none':'missing'}},headers=admin()).status_code==409
        assert c.post(path,json={'state':state,'evidence':{k:'verified:fixture' for k in keys}},headers=admin()).status_code==200
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
    assert replace(s,stripe_key='sk_live_fixture',origin='https://example.test').payments_ready

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
