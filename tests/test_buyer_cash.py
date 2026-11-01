"""Settled cash observations reconcile funding without moving or inventing money."""
import json
import sqlite3
import time
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store
from test_transactions import setup, customer, request, approve, checkout, auth, admin, status, record_cash_balance, accept_fixture_transport
from test_funding_coverage import prepared, record_funding, advance, dispatch_body


def receipt_body(amount=400000, **changes):
    return {'currency':'USD','quote_version':1,'dealer_id':'fixture-dealer','amount_cents':amount,
        'receipt_reference':'PRIVATE-cash-'+str(uuid.uuid4()),'evidence_reference':'PRIVATE-bank-proof',
        'settled_at':int(time.time()),'settled':True,'excludes_reservation_deposit':True,**changes}


def receipt(client,order,body):
    return client.post('/api/admin/orders/'+order['id']+'/buyer-cash-receipts',json=body,headers=admin())


def reversal_body(entry,amount,**changes):
    return {'currency':'USD','quote_version':entry['quote_version'],'dealer_id':entry['dealer_id'],
        'receipt_id':entry['id'],'amount_cents':amount,'reversal_reference':'PRIVATE-return-'+str(uuid.uuid4()),
        'evidence_reference':'PRIVATE-return-proof','observed_at':int(time.time()),**changes}


def reverse(client,order,body):
    return client.post('/api/admin/orders/'+order['id']+'/buyer-cash-reversals',json=body,headers=admin())


def summary(client,order):
    return client.get('/api/orders/'+order['id'],headers=auth(order)).json()['funding_summary']


@pytest.mark.parametrize('extra',[-1,0,100])
def test_mixed_loan_and_cash_exact_short_and_overpaid(setup,extra):
    client,payments,_,order,quote=prepared(setup)
    balance=quote['balance_after_deposit_cents'];cash=400000
    record_funding(client,order,balance-cash+extra)
    body=receipt_body(cash);result=receipt(client,order,body)
    assert result.status_code==200,result.text
    funds=result.json()['funding_summary']
    assert funds['quote_version']==1 and funds['currency']=='USD'
    assert funds['credited_deposit_cents']==25000 and funds['lender_funded_cents']==balance-cash+extra
    assert funds['net_additional_cash_cents']==cash and funds['remaining_cents']==max(0,-extra)
    assert funds['overpaid_cents']==max(0,extra) and funds['coverage_complete'] is (extra>=0)
    assert type(funds['funds_review_required']) is bool and funds['balance_checkout_allowed'] is False
    assert result.json()['observational_only'] is True and result.json()['money_moved'] is False
    assert advance(client,order,'dealer_confirmed').status_code==(200 if extra>=0 else 409)
    assert payments.refunds==0 and payments.balance_calls==0


def test_conditional_approval_and_calculator_values_cannot_count_as_received(setup):
    client,_,_,order,quote=prepared(setup)
    record_funding(client,order,0,state='conditional_approval',approved_amount_cents=quote['total_cents'])
    assert receipt(client,order,receipt_body()).status_code==200
    funds=summary(client,order)
    assert funds['lender_funded_cents']==0
    assert funds['remaining_cents']==quote['balance_after_deposit_cents']-400000
    assert advance(client,order,'dealer_confirmed').status_code==409


def test_same_payload_retry_survives_restart_without_double_counting(setup):
    client,_,store,order,_=prepared(setup)
    body=receipt_body();first=receipt(client,order,body)
    restarted=TestClient(create_app(setup[1],setup[2]))
    again=receipt(restarted,order,body)
    assert again.status_code==200 and again.json()['entry']==first.json()['entry']
    assert summary(restarted,order)['net_additional_cash_cents']==body['amount_cents']
    assert receipt(restarted,order,{**body,'amount_cents':body['amount_cents']+1}).status_code==409
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM buyer_cash_entries').fetchone()[0]==1


def test_receipt_reference_cannot_be_reused_on_another_order_or_as_reversal(setup):
    client,_,store,order,_=prepared(setup)
    body=receipt_body();result=receipt(client,order,body).json();entry=result['entry']
    # A second independent order is enough to prove global reference isolation before any new receipt is written.
    other_id=str(uuid.uuid4())
    with store.transaction() as db:
        db.execute("INSERT INTO orders(id,access_hash,request_key,request_hash,vin,customer,state,created_at,updated_at,action_due_at) VALUES(?,?,?,?,?,'{}','requested',1,1,2)",
            (other_id,'fixture-access','other-key','other-hash','7SAYGDED1RF039277'))
    other={'id':other_id}
    assert receipt(client,other,body).status_code==409
    assert reverse(client,other,reversal_body(entry,1)).status_code==404
    assert reverse(client,order,reversal_body(entry,1,reversal_reference=body['receipt_reference'])).status_code==409


def test_partial_reversals_are_append_only_idempotent_and_cannot_exceed_receipt(setup):
    client,_,store,order,quote=prepared(setup)
    record_funding(client,order,quote['balance_after_deposit_cents']-400000)
    entry=receipt(client,order,receipt_body()).json()['entry']
    body=reversal_body(entry,100000);first=reverse(client,order,body)
    assert first.status_code==200 and first.json()['funding_summary']['net_additional_cash_cents']==300000
    assert reverse(client,order,body).json()['entry']==first.json()['entry']
    assert reverse(client,order,{**body,'amount_cents':100001}).status_code==409
    assert reverse(client,order,reversal_body(entry,300001)).status_code==409
    assert reverse(client,order,reversal_body(entry,300000)).status_code==200
    assert summary(client,order)['net_additional_cash_cents']==0
    assert advance(client,order,'dealer_confirmed').status_code==409
    with store.transaction() as db:
        with pytest.raises(sqlite3.IntegrityError,match='append-only'):
            db.execute('UPDATE buyer_cash_entries SET amount_cents=1 WHERE id=?',(entry['id'],))
        with pytest.raises(sqlite3.IntegrityError,match='append-only'):
            db.execute('DELETE FROM buyer_cash_entries WHERE id=?',(entry['id'],))
        assert db.execute('SELECT COUNT(*) FROM buyer_cash_entries').fetchone()[0]==3


def test_reversal_after_funding_blocks_subsequent_release_and_carrier_markers(setup):
    client,_,_,order,quote=prepared(setup)
    record_funding(client,order,quote['balance_after_deposit_cents']-400000)
    entry=receipt(client,order,receipt_body()).json()['entry']
    assert advance(client,order,'dealer_confirmed').status_code==200
    accept_fixture_transport(client,order)
    assert reverse(client,order,reversal_body(entry,1)).status_code==200
    assert advance(client,order,'dealer_funded').status_code==409
    endpoint='/api/admin/orders/'+order['id']+'/transport'
    for marker in ['dispatched','delivered']:
        assert client.post(endpoint,json={**dispatch_body(),'state':marker},headers=admin()).status_code==409


@pytest.mark.parametrize('closed',['cancelled','refunded','completed'])
def test_closed_history_allows_observed_reversal_but_no_new_cash_or_money_action(setup,closed):
    client,payments,store,order,_=prepared(setup)
    body=receipt_body();entry=receipt(client,order,body).json()['entry']
    with store.transaction() as db:db.execute('UPDATE orders SET state=? WHERE id=?',(closed,order['id']))
    assert receipt(client,order,receipt_body()).status_code==409
    assert receipt(client,order,body).status_code==200  # Durable retry, not a new observation.
    result=reverse(client,order,reversal_body(entry,400000))
    assert result.status_code==200 and result.json()['money_moved'] is False
    assert status(client,order)==closed and summary(client,order)['net_additional_cash_cents']==0
    assert payments.refunds==0


def test_quote_change_keeps_old_cash_visible_unallocated_and_never_relabels_it(setup):
    client,_,store,order,_=prepared(setup)
    entry=receipt(client,order,receipt_body()).json()['entry']
    with store.transaction() as db:db.execute('UPDATE orders SET quote_version=2 WHERE id=?',(order['id'],))
    funds=summary(client,order)
    assert funds['quote_version']==2 and funds['net_additional_cash_cents']==0
    assert funds['prior_quote_unallocated_cash_cents']==400000 and funds['funds_review_required'] is True
    assert receipt(client,order,receipt_body(quote_version=1)).status_code==409
    assert advance(client,order,'dealer_confirmed').status_code==409
    assert reverse(client,order,reversal_body(entry,1,quote_version=2)).status_code==409
    assert reverse(client,order,reversal_body(entry,1)).status_code==200
    assert summary(client,order)['prior_quote_unallocated_cash_cents']==399999


def test_changed_retail_seller_cannot_inherit_previous_seller_cash(setup):
    client,_,store,order,_=prepared(setup)
    entry=receipt(client,order,receipt_body()).json()['entry']
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT dealer_profile FROM orders WHERE id=?',(order['id'],)).fetchone()[0])
        profile['legal_name']='Different fixture retail entity'
        db.execute('UPDATE orders SET dealer_profile=? WHERE id=?',(json.dumps(profile),order['id']))
    funds=summary(client,order)
    assert funds['net_additional_cash_cents']==0 and funds['prior_quote_unallocated_cash_cents']==400000
    assert reverse(client,order,reversal_body(entry,400000)).status_code==200
    assert summary(client,order)['prior_quote_unallocated_cash_cents']==0


@pytest.mark.parametrize('changes',[{'amount_cents':True},{'amount_cents':1.5},{'amount_cents':0},
    {'currency':'EUR'},{'settled':False},{'settled':1},{'excludes_reservation_deposit':False},
    {'quote_version':True},{'evidence_reference':'  '}])
def test_cash_observation_models_require_explicit_usd_integer_settlement_proof(setup,changes):
    client,_,_,order,_=prepared(setup)
    assert receipt(client,order,receipt_body(**changes)).status_code==422


def test_stale_seller_future_timestamps_and_reserved_funding_namespaces_are_rejected(setup):
    client,_,store,order,_=prepared(setup)
    assert receipt(client,order,receipt_body(dealer_id='another-seller')).status_code==409
    assert receipt(client,order,receipt_body(settled_at=int(time.time())+3600)).status_code==409
    with store.connect() as db:payment_id=db.execute('SELECT payment_id FROM orders WHERE id=?',(order['id'],)).fetchone()[0]
    assert receipt(client,order,receipt_body(receipt_reference=payment_id)).status_code==409
    record_funding(client,order,1,reference='PRIVATE_FUNDING_REFERENCE')
    assert receipt(client,order,receipt_body(receipt_reference='PRIVATE_FUNDING_REFERENCE')).status_code==409
    entry=receipt(client,order,receipt_body()).json()['entry']
    assert reverse(client,order,reversal_body(entry,1,observed_at=int(time.time())+3600)).status_code==409
    assert reverse(client,order,reversal_body(entry,1,dealer_id='another-seller')).status_code==409


def test_early_receipts_are_rejected_and_historical_unallocated_cash_blocks_new_deposit(setup):
    client,_,store,order,_=prepared(setup)
    assert receipt(client,order,receipt_body()).status_code==200
    with store.transaction() as db:db.execute("UPDATE orders SET state='quoted',quote_version=2,checkout_id=NULL WHERE id=?",(order['id'],))
    calls=setup[2].session_calls
    assert receipt(client,order,receipt_body(quote_version=2)).status_code==409
    response=client.post('/api/orders/'+order['id']+'/checkout',json={'quote_version':2,'terms_accepted':True},headers=auth(order))
    assert response.status_code==409 and setup[2].session_calls==calls


def test_partial_cash_and_lender_funding_disable_full_balance_route_and_portal_only(setup):
    client,payments,store,order,_=prepared(setup,financed=False)
    with store.transaction() as db:
        for kind in ['pay_balance','submit_title_documents']:
            db.execute('INSERT INTO online_actions VALUES(?,?,?,?)',(order['id'],kind,'https://portal.example.test/'+kind,'fixture:evidence'))
    assert summary(client,order)['balance_checkout_allowed'] is True
    entry=receipt(client,order,receipt_body()).json()['entry']
    current=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert current['funding_summary']['balance_checkout_allowed'] is False
    assert [a['kind'] for a in current['online_actions']]==['submit_title_documents']
    endpoint='/api/orders/'+order['id']+'/balance-checkout'
    assert client.post(endpoint,json={'quote_version':1,'terms_accepted':True},headers=auth(order)).status_code==409
    assert payments.balance_calls==0
    assert reverse(client,order,reversal_body(entry,400000)).status_code==200
    assert summary(client,order)['balance_checkout_allowed'] is True
    record_funding(client,order,1)
    assert summary(client,order)['balance_checkout_allowed'] is False
    assert client.post(endpoint,json={'quote_version':1,'terms_accepted':True},headers=auth(order)).status_code==409
    assert payments.balance_calls==0


def test_private_receipt_data_never_enters_customer_projection_and_history_requires_admin(setup):
    client,_,_,order,_=prepared(setup)
    body=receipt_body();result=receipt(client,order,body)
    assert result.status_code==200
    endpoint='/api/admin/orders/'+order['id']+'/buyer-cash-receipts'
    assert client.get(endpoint).status_code==401
    assert client.post(endpoint,json=receipt_body()).status_code==401
    assert client.post('/api/admin/orders/'+order['id']+'/buyer-cash-reversals',
        json=reversal_body(result.json()['entry'],1)).status_code==401
    history=client.get(endpoint,headers=admin()).json()
    assert history['entries'][0]['reference']==body['receipt_reference']
    public=client.get('/api/orders/'+order['id'],headers=auth(order))
    assert 'PRIVATE' not in public.text and 'evidence_reference' not in public.text
    funds=public.json()['funding_summary']
    assert all(type(funds[k]) is bool for k in ['coverage_complete','funds_review_required','balance_checkout_allowed'])
    assert 'receipt_reference' not in json.dumps(funds)


def test_reversal_model_requires_usd_and_strict_amounts(setup):
    client,_,_,order,_=prepared(setup)
    entry=receipt(client,order,receipt_body()).json()['entry']
    for changes in [{'currency':'EUR'},{'amount_cents':True},{'amount_cents':0},{'quote_version':1.5}]:
        assert reverse(client,order,reversal_body(entry,1,**changes)).status_code==422


def test_migration_adds_empty_ledger_without_inventing_historical_cash(tmp_path):
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE orders(id TEXT PRIMARY KEY,access_hash TEXT NOT NULL,request_key TEXT UNIQUE NOT NULL,request_hash TEXT NOT NULL,vin TEXT NOT NULL,customer TEXT NOT NULL,state TEXT NOT NULL,quote TEXT,quote_version INTEGER NOT NULL DEFAULT 0,checkout_id TEXT UNIQUE,payment_id TEXT UNIQUE,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,action_due_at INTEGER NOT NULL)')
        db.execute("INSERT INTO orders(id,access_hash,request_key,request_hash,vin,customer,state,created_at,updated_at,action_due_at) VALUES('old','h','k','r','7SAYGDED1RF039277','{}','cancelled',1,1,2)")
    store=Store(path)
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM buyer_cash_entries').fetchone()[0]==0
        assert db.execute("SELECT state FROM orders WHERE id='old'").fetchone()[0]=='cancelled'


@pytest.mark.parametrize('outcome',['failed','paid'])
def test_in_flight_full_balance_conflict_preserves_session_and_reconciles_outcome(setup,outcome):
    client,payments,store,order,quote=prepared(setup,financed=False)
    endpoint='/api/orders/'+order['id']+'/balance-checkout'
    assert client.post(endpoint,json={'quote_version':1,'terms_accepted':True},headers=auth(order)).status_code==200
    with store.connect() as db:session_id=db.execute('SELECT balance_checkout_id FROM orders WHERE id=?',(order['id'],)).fetchone()[0]
    record_funding(client,order,quote['balance_after_deposit_cents']-400000)
    assert receipt(client,order,receipt_body()).status_code==200
    funds=summary(client,order)
    assert funds['coverage_complete'] is True and funds['in_flight_balance_conflict'] is True
    assert funds['funds_review_required'] is True and funds['balance_checkout_allowed'] is False
    assert advance(client,order,'dealer_confirmed').status_code==409
    assert client.post(endpoint,json={'quote_version':1,'terms_accepted':True},headers=auth(order)).status_code==409
    with store.connect() as db:
        row=db.execute('SELECT balance_checkout_id,balance_payment_state FROM orders WHERE id=?',(order['id'],)).fetchone()
        assert row['balance_checkout_id']==session_id and row['balance_payment_state']=='checkout_open'
        events=db.execute("SELECT detail FROM events WHERE order_id=? AND kind='funding_payment_conflict'",(order['id'],)).fetchall()
        assert events and all(json.loads(x[0])['provider_session_cancelled'] is False for x in events)
    with store.transaction() as db:
        db.execute("UPDATE orders SET balance_payment_state='ach_processing',balance_payment_id='pi_fixture_pending_balance' WHERE id=?",(order['id'],))
    assert summary(client,order)['in_flight_balance_conflict'] is True
    with store.transaction() as db:
        db.execute('UPDATE orders SET balance_payment_state=? WHERE id=?',(outcome,order['id']))
        if outcome=='paid':store.event(db,order['id'],'balance_payment_settled',{
            'balance_payment_id':'pi_fixture_pending_balance','amount_cents':quote['balance_after_deposit_cents']})
    final=summary(client,order)
    assert final['in_flight_balance_conflict'] is False
    if outcome=='paid':
        assert final['overpaid_cents']==quote['balance_after_deposit_cents'] and final['funds_review_required'] is True
    else:
        assert final['overpaid_cents']==0 and final['coverage_complete'] is True
        assert advance(client,order,'dealer_confirmed').status_code==200
    assert payments.balance_calls==1 and payments.refunds==0
