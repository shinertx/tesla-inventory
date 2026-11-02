"""Explicit local platform-collection fixtures; no accounts, charges, or network."""
from dataclasses import replace
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import Dealer
from test_transactions import (setup, Payments, request, approve, quote_body, checkout,
                               auth, admin, status)

PIN = 'acct_fixturePlatform'
NAME = 'JENNI PRO INC'
AUTHORIZATION = 'fixture:signed-seller-collection-authorization'


class PlatformPayments(Payments):
    def __init__(self):
        super().__init__();self.retrievals=0
    def retrieve_checkout(self,sid,account):
        self.retrievals+=1
        return super().retrieve_checkout(sid,account)
    def dealer_can_charge(self, account):
        assert account == PIN
        return True


@pytest.fixture
def platform_setup(tmp_path):
    _, original, _, store = setup.__wrapped__(tmp_path)
    settings = replace(original, deposit_collection_mode='platform', stripe_platform_account=PIN,
        platform_collection_legal_name=NAME, balance_checkout_enabled=True, stripe_key='rk_test_fixture')
    payments = PlatformPayments(); client = TestClient(create_app(settings, payments))
    with store.connect() as db: profile = json.loads(db.execute('SELECT profile FROM dealers').fetchone()[0])
    profile.update(stripe_account=PIN, payment_account_role='platform',
                   collection_authorization_reference=AUTHORIZATION, collection_legal_name=NAME)
    assert client.put('/api/admin/dealers/fixture-dealer', json=profile, headers=admin()).status_code == 200
    return client, settings, payments, store, profile


def opened(fixture):
    client, _, payments, _, _ = fixture
    order = request(client); approve(client, order)
    response = checkout(client, order)
    assert response.status_code == 200, response.text
    assert response.json()['account'] is None
    return order, payments.sessions['cs_test_' + order['id']]


def webhook(client, session, *, kind='checkout.session.completed', account=None, include_account=False,
            event_id=None, live=False, obj=None):
    payload = {'id':event_id or 'evt_' + str(uuid.uuid4()), 'type':kind, 'livemode':live,
               'data':{'object':obj or {'id':session['id']}}}
    if include_account: payload['account'] = account
    return client.post('/api/stripe/webhook', json=payload, headers={'Stripe-Signature':'valid-test-signature'})


def test_platform_readiness_requires_explicit_identity_pin_and_agreements():
    base = Settings(checkout_enabled=True, platform_agreements_verified=True,
        stripe_key='rk_test_fixture', stripe_publishable_key='pk_test_fixture', webhook_secret='whsec_fixture',
        origin='https://example.test', deposit_collection_mode='platform',
        stripe_platform_account=PIN, platform_collection_legal_name=NAME, balance_checkout_enabled=True)
    assert base.payments_ready and not base.balance_payments_ready
    for changes in ({'stripe_platform_account':''}, {'stripe_platform_account':'invalid'},
                    {'platform_collection_legal_name':''}, {'platform_agreements_verified':False},
                    {'deposit_collection_mode':'unknown'}):
        assert not replace(base, **changes).payments_ready
    assert not replace(base, sandbox_mode=True, platform_agreements_verified=False).payments_ready


def test_collection_environment_is_explicit(monkeypatch):
    monkeypatch.setenv('DEPOSIT_COLLECTION_MODE','platform')
    monkeypatch.setenv('STRIPE_PLATFORM_ACCOUNT',PIN)
    monkeypatch.setenv('PLATFORM_COLLECTION_LEGAL_NAME',NAME)
    settings = Settings.from_env()
    assert (settings.deposit_collection_mode,settings.stripe_platform_account,settings.platform_collection_legal_name)==('platform',PIN,NAME)


def test_own_deposit_uses_real_seller_snapshot_and_private_collection_authority(platform_setup):
    client, settings, _, store, profile = platform_setup
    order, _ = opened(platform_setup)
    public = client.get('/api/orders/'+order['id'], headers=auth(order))
    assert public.json()['quote']['seller']['legal_name'] == profile['legal_name']
    assert public.json()['deposit_collection_mode']=='platform'
    assert public.json()['deposit_collector_legal_name']==NAME
    assert AUTHORIZATION not in public.text and PIN not in public.text
    with store.connect() as db:
        saved = json.loads(db.execute('SELECT dealer_profile FROM orders WHERE id=?',(order['id'],)).fetchone()[0])
        assert saved['payment_account_role']=='platform' and saved['collection_authorization_reference']==AUTHORIZATION
    renamed = TestClient(create_app(replace(settings,platform_collection_legal_name='Different current name'),platform_setup[2]))
    assert renamed.get('/api/orders/'+order['id'],headers=auth(order)).json()['deposit_collector_legal_name']==NAME


def test_accountless_own_completion_replay_and_refund_after_collection_disabled(platform_setup):
    client, settings, payments, store, _ = platform_setup
    order, session = opened(platform_setup); session.update(status='complete',payment_status='paid')
    disabled = TestClient(create_app(replace(settings,checkout_enabled=False), payments))
    event_id = 'evt_platform_completed'
    assert webhook(client,session,event_id=event_id).status_code==200
    assert webhook(disabled,session,event_id=event_id).status_code==200
    assert status(disabled,order)=='deposit_paid'
    with store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE order_id=? AND kind='deposit_paid'",(order['id'],)).fetchone()[0]==1
        db.execute("UPDATE orders SET state='refund_pending' WHERE id=?",(order['id'],))
    obj={'id':'re_platform_fixture','payment_intent':session['payment_intent'],'amount':25000,'status':'succeeded'}
    assert webhook(disabled,session,kind='refund.updated',obj=obj).status_code==200
    assert status(disabled,order)=='refunded' and payments.refunds==0


@pytest.mark.parametrize('account', [PIN,'acct_wrong',''])
def test_platform_rejects_claimed_connected_account_even_matching_pin(platform_setup, account):
    client, _, _, _, _=platform_setup;order,session=opened(platform_setup)
    session.update(status='complete',payment_status='paid')
    assert webhook(client,session,include_account=True,account=account).status_code==409
    assert status(client,order)=='checkout_pending'


@pytest.mark.parametrize('kind', ['checkout.session.completed','checkout.session.expired','checkout.session.async_payment_failed'])
def test_wrong_platform_pin_or_signed_mode_cannot_mutate_order(platform_setup, kind):
    client, settings, payments, _, _=platform_setup;order,session=opened(platform_setup)
    session.update(status='complete',payment_status='paid')
    wrong_pin=TestClient(create_app(replace(settings,stripe_platform_account='acct_wrong'),payments))
    assert webhook(wrong_pin,session,kind=kind).status_code==409
    assert webhook(client,session,kind=kind,live=True).status_code==409
    assert status(client,order)=='checkout_pending'


@pytest.mark.parametrize('kind', ['checkout.session.expired','checkout.session.async_payment_failed'])
def test_own_expiry_and_failure_still_reconcile_with_checkout_disabled(platform_setup, kind):
    client, settings, payments, _, _=platform_setup;order,session=opened(platform_setup)
    disabled=TestClient(create_app(replace(settings,checkout_enabled=False),payments))
    assert webhook(disabled,session,kind=kind).status_code==200
    assert status(disabled,order)=='quote_expired'


def test_own_dispute_matches_saved_account_with_checkout_disabled(platform_setup):
    client, settings, payments, _, _=platform_setup;order,session=opened(platform_setup)
    session.update(status='complete',payment_status='paid');assert webhook(client,session).status_code==200
    disabled=TestClient(create_app(replace(settings,checkout_enabled=False),payments))
    obj={'id':'dp_fixture','payment_intent':session['payment_intent']}
    assert webhook(disabled,session,kind='charge.dispute.created',obj=obj,include_account=True,account=PIN).status_code==409
    assert webhook(disabled,session,kind='charge.dispute.created',obj=obj).status_code==200
    assert status(disabled,order)=='payment_review'


def test_accountless_event_cannot_impersonate_direct_seller_order(setup):
    client, _, payments, _=setup;order=request(client);approve(client,order);assert checkout(client,order).status_code==200
    session=payments.sessions['cs_test_'+order['id']];session.update(status='complete',payment_status='paid')
    assert webhook(client,session).status_code==409
    assert webhook(client,session,include_account=True,account='acct_fixtureDealer').status_code==200


@pytest.mark.parametrize('changes', [{'payment_account_role':'seller'}, {'stripe_account':'acct_wrong'},
    {'collection_legal_name':'Different collector'}, {'verified':False}])
def test_platform_quote_rejects_wrong_role_pin_identity_or_unverified_seller(platform_setup, changes):
    client, _, _, _, profile=platform_setup
    profile={**profile,**changes};assert client.put('/api/admin/dealers/fixture-dealer',json=profile,headers=admin()).status_code==200
    order=request(client)
    response=client.post('/api/admin/orders/'+order['id']+'/quote',json=quote_body(),headers=admin())
    assert response.status_code==409
    assert client.get('/api/config').json()['payments_enabled'] is False


def test_platform_profile_without_authorization_is_rejected(platform_setup):
    client, _, _, _, profile=platform_setup
    for field in ('collection_authorization_reference','collection_legal_name'):
        assert client.put('/api/admin/dealers/fixture-dealer',json={**profile,field:''},headers=admin()).status_code==422


def test_platform_does_not_create_or_bypass_missing_seller(platform_setup):
    client, _, _, store, _=platform_setup
    with store.transaction() as db:db.execute('DELETE FROM dealers')
    order=request(client)
    assert client.post('/api/admin/orders/'+order['id']+'/quote',json=quote_body(),headers=admin()).status_code==409
    assert not client.get('/api/config').json()['payments_enabled']


def test_changed_collection_authority_cannot_replace_order_snapshot(platform_setup):
    client, _, payments, _, profile=platform_setup
    order=request(client);approve(client,order)
    changed={**profile,'collection_authorization_reference':'fixture:different-authorization'}
    assert client.put('/api/admin/dealers/fixture-dealer',json=changed,headers=admin()).status_code==200
    assert checkout(client,order).status_code==409 and payments.session_calls==0


def test_direct_mode_rejects_platform_profile_for_new_collection(platform_setup):
    _, settings, payments, _, _=platform_setup
    direct=TestClient(create_app(replace(settings,deposit_collection_mode='dealer_direct'),payments))
    order=request(direct)
    assert direct.post('/api/admin/orders/'+order['id']+'/quote',json=quote_body(),headers=admin()).status_code==409


def test_platform_mode_cannot_enable_full_balance_even_with_explicit_switch(platform_setup):
    client, _, payments, store, _=platform_setup;order,session=opened(platform_setup)
    session.update(status='complete',payment_status='paid');assert webhook(client,session).status_code==200
    with store.transaction() as db:db.execute("UPDATE orders SET state='dealer_confirmed' WHERE id=?",(order['id'],))
    cfg=client.get('/api/config').json()
    assert cfg['balance_checkout_enabled'] is False and cfg['ach_enabled'] is False
    assert client.post('/api/orders/'+order['id']+'/balance-checkout',json={'quote_version':1,'terms_accepted':True},headers=auth(order)).status_code==409
    assert client.get('/api/orders/'+order['id'],headers=auth(order)).json()['funding_summary']['balance_checkout_allowed'] is False
    assert payments.balance_calls==0


def test_first_late_own_payment_after_disable_preserves_existing_refund_queue_policy(platform_setup):
    client,settings,payments,store,_=platform_setup;order,session=opened(platform_setup)
    session.update(status='complete',payment_status='paid')
    disabled=TestClient(create_app(replace(settings,checkout_enabled=False),payments))
    assert webhook(disabled,session).status_code==200
    assert status(disabled,order)=='refund_pending'
    with store.connect() as db:
        assert db.execute('SELECT payment_id FROM orders WHERE id=?',(order['id'],)).fetchone()[0]==session['payment_intent']
    assert payments.refunds==0


def test_changed_authority_after_checkout_does_not_approve_new_payment(platform_setup):
    client,_,payments,_,profile=platform_setup;order,session=opened(platform_setup)
    changed={**profile,'collection_authorization_reference':'fixture:replacement-authority'}
    assert client.put('/api/admin/dealers/fixture-dealer',json=changed,headers=admin()).status_code==200
    session.update(status='complete',payment_status='paid')
    assert webhook(client,session).status_code==200
    assert status(client,order)=='refund_pending' and payments.refunds==0


@pytest.mark.parametrize('kind', ['checkout.session.completed','checkout.session.async_payment_succeeded',
    'checkout.session.expired','checkout.session.async_payment_failed','refund.created','refund.updated','charge.dispute.created'])
def test_unrelated_signed_jenni_event_is_ignored_without_provider_or_ledger_effect(platform_setup, kind):
    client,_,payments,store,_=platform_setup;order,session=opened(platform_setup)
    obj={'id':'unrelated-jenni-object','payment_intent':'pi_unrelated_jenni'}
    result=webhook(client,session,kind=kind,obj=obj)
    assert result.status_code==200 and result.json()=={'received':True,'ignored':True}
    assert status(client,order)=='checkout_pending'
    assert payments.retrievals==0 and payments.refunds==0 and payments.session_calls==1
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM stripe_events').fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM events WHERE detail LIKE '%unrelated-jenni%' OR detail LIKE '%pi_unrelated%' ").fetchone()[0]==0


@pytest.mark.parametrize('kind', ['checkout.session.completed','checkout.session.async_payment_succeeded',
    'checkout.session.expired','checkout.session.async_payment_failed'])
def test_recorded_historical_session_is_not_silently_ignored_after_binding_clears(platform_setup, kind):
    client,_,payments,store,_=platform_setup;order,session=opened(platform_setup)
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='quote_expired',checkout_id=NULL WHERE id=?",(order['id'],))
    result=webhook(client,session,kind=kind)
    assert result.status_code==409 and 'reconciliation' in result.text
    assert payments.retrievals==0 and payments.refunds==0
    with store.connect() as db:assert db.execute('SELECT COUNT(*) FROM stripe_events').fetchone()[0]==0
