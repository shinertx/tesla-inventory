"""Lender amounts are immutable net snapshots, with explicit correction observations."""
import json
import sqlite3
import time
import uuid

import pytest
from test_transactions import setup, admin, auth
from test_funding_coverage import prepared, record_funding, advance
from test_buyer_cash import receipt, receipt_body, summary


def funding_body(amount,reference='PRIVATE-lender-original',**changes):
    return {'state':'lender_funded','provider':'Fixture lender','reference':reference,
            'funded_amount_cents':amount,'quote_version':1,**changes}


def post_funding(client,order,body):
    return client.post('/api/admin/orders/'+order['id']+'/financing',json=body,headers=admin())


def correction_body(prior,amount,**changes):
    return {'currency':'USD','quote_version':1,'dealer_id':'fixture-dealer',
        'expected_prior_reference':prior,'correction_reference':'PRIVATE-correction-'+str(uuid.uuid4()),
        'evidence_reference':'PRIVATE-actual-return-statement','net_settled_cents':amount,
        'observed_at':int(time.time()),**changes}


def correct(client,order,body):
    return client.post('/api/admin/orders/'+order['id']+'/lender-funding-corrections',json=body,headers=admin())


def test_actual_lender_reference_is_immutable_and_cumulative_snapshots_are_not_summed(setup):
    client,_,store,order,_=prepared(setup)
    body=funding_body(100000)
    assert post_funding(client,order,body).status_code==200
    assert post_funding(client,order,body).status_code==200
    for changes in [{'funded_amount_cents':100001},{'provider':'Different lender'}]:
        assert post_funding(client,order,{**body,**changes}).status_code==409
    assert post_funding(client,order,funding_body(200000,'PRIVATE-lender-updated')).status_code==200
    assert summary(client,order)['lender_funded_cents']==200000
    assert post_funding(client,order,body).status_code==409  # Old retry cannot roll back latest net.
    assert post_funding(client,order,funding_body(199999,'PRIVATE-lender-decreased')).status_code==409
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM lender_funding_observations').fetchone()[0]==2
        with pytest.raises(sqlite3.IntegrityError,match='append-only'):
            db.execute('DELETE FROM lender_funding_observations')


def test_reference_cannot_fund_another_order_quote_seller_or_cash_receipt(setup):
    client,_,store,order,_=prepared(setup)
    body=funding_body(100000);assert post_funding(client,order,body).status_code==200
    assert receipt(client,order,receipt_body(receipt_reference=body['reference'])).status_code==409
    other_id=str(uuid.uuid4())
    with store.transaction() as db:
        original=dict(db.execute('SELECT * FROM orders WHERE id=?',(order['id'],)).fetchone())
        original.update(id=other_id,access_hash='other-access',request_key='other-key',request_hash='other-hash',
                        checkout_id=None,payment_id='pi_other_fixture',balance_checkout_id=None,balance_payment_id=None,
                        financing_state='not_requested',financing_detail=None)
        columns=list(original)
        db.execute('INSERT INTO orders('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(original[k] for k in columns))
    assert post_funding(client,{'id':other_id},body).status_code==409
    with store.transaction() as db:db.execute('UPDATE orders SET quote_version=2 WHERE id=?',(order['id'],))
    assert post_funding(client,order,{**body,'quote_version':2}).status_code==409
    funds=summary(client,order)
    assert funds['lender_funded_cents']==0 and funds['prior_quote_unallocated_lender_cents']==100000
    assert funds['funds_review_required'] is True


def test_lender_reference_cannot_reuse_cash_and_stale_version_cannot_register(setup):
    client,_,_,order,_=prepared(setup)
    cash=receipt_body();assert receipt(client,order,cash).status_code==200
    assert post_funding(client,order,funding_body(1,cash['receipt_reference'])).status_code==409
    assert post_funding(client,order,funding_body(1,quote_version=2)).status_code==409
    assert summary(client,order)['lender_funded_cents']==0


def test_correction_to_partial_then_zero_changes_net_once_and_blocks_release(setup):
    client,payments,store,order,quote=prepared(setup)
    balance=quote['balance_after_deposit_cents'];original='PRIVATE-lender-original'
    assert post_funding(client,order,funding_body(balance,original)).status_code==200
    assert summary(client,order)['coverage_complete'] is True
    body=correction_body(original,balance-1);result=correct(client,order,body)
    assert result.status_code==200 and result.json()['money_moved'] is False
    assert correct(client,order,body).status_code==200
    funds=summary(client,order)
    assert funds['lender_funded_cents']==balance-1 and funds['remaining_cents']==1
    assert funds['funds_review_required'] is True and advance(client,order,'dealer_confirmed').status_code==409
    zero=correction_body(body['correction_reference'],0)
    assert correct(client,order,zero).status_code==200
    current=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert current['financing']['funded_amount_cents']==0 and current['financing']['state']=='funding_reconciled'
    assert current['funding_summary']['lender_funded_cents']==0
    assert current['funding_summary']['remaining_cents']==balance
    assert 'PRIVATE' not in json.dumps(current) and payments.refunds==0
    with store.connect() as db:
        rows=db.execute('SELECT amount_cents FROM lender_funding_observations ORDER BY seq').fetchall()
        assert [r[0] for r in rows]==[balance,balance-1,0]


def test_correction_requires_latest_prior_and_unique_matching_context(setup):
    client,_,_,order,_=prepared(setup)
    original='PRIVATE-lender-original';assert post_funding(client,order,funding_body(100000,original)).status_code==200
    first=correction_body(original,90000);assert correct(client,order,first).status_code==200
    assert correct(client,order,correction_body(original,80000)).status_code==409
    assert correct(client,order,{**first,'net_settled_cents':90001}).status_code==409
    for changes in [{'quote_version':2},{'dealer_id':'another-seller'},{'observed_at':int(time.time())+1000}]:
        assert correct(client,order,correction_body(first['correction_reference'],80000,**changes)).status_code==409
    for changes in [{'currency':'EUR'},{'net_settled_cents':True},{'net_settled_cents':-1}]:
        assert correct(client,order,correction_body(first['correction_reference'],80000,**changes)).status_code==422
    assert summary(client,order)['lender_funded_cents']==90000


def test_funding_status_cannot_erase_observed_proceeds_and_cash_can_cover_corrected_shortfall(setup):
    client,_,_,order,quote=prepared(setup)
    original='PRIVATE-lender-original';balance=quote['balance_after_deposit_cents']
    assert post_funding(client,order,funding_body(balance,original)).status_code==200
    declined={'state':'declined','provider':'Fixture lender','reference':'PRIVATE-status-regression'}
    assert post_funding(client,order,declined).status_code==409
    assert correct(client,order,correction_body(original,balance-400000)).status_code==200
    assert receipt(client,order,receipt_body(400000)).status_code==200
    assert summary(client,order)['coverage_complete'] is True
    assert advance(client,order,'dealer_confirmed').status_code==200


@pytest.mark.parametrize('closed',['cancelled','refunded','completed'])
def test_observed_lender_return_after_closure_preserves_order_and_history(setup,closed):
    client,payments,store,order,_=prepared(setup)
    original='PRIVATE-lender-original';assert post_funding(client,order,funding_body(100000,original)).status_code==200
    with store.transaction() as db:db.execute('UPDATE orders SET state=? WHERE id=?',(closed,order['id']))
    assert correct(client,order,correction_body(original,0)).status_code==200
    current=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert current['state']==closed and current['financing']['funded_amount_cents']==0
    assert payments.refunds==0


def test_lender_history_is_private_and_legacy_observations_are_not_fabricated(setup):
    client,_,store,order,quote=prepared(setup)
    amount=quote['balance_after_deposit_cents']
    # Actual old API event ordering can support a legacy observation without inventing registry history.
    detail={'state':'lender_funded','provider':'Fixture lender','reference':'PRIVATE-legacy-lender',
            'funded_amount_cents':amount,'approved_amount_cents':0,'stipulations':[],'application_url':''}
    with store.transaction() as db:
        db.execute("UPDATE orders SET financing_state='lender_funded',financing_detail=? WHERE id=?",(json.dumps(detail),order['id']))
        store.event(db,order['id'],'financing_lender_funded',detail)
    assert summary(client,order)['lender_funded_cents']==amount
    endpoint='/api/admin/orders/'+order['id']+'/lender-funding-observations'
    assert client.get(endpoint).status_code==401
    assert client.get(endpoint,headers=admin()).json()['observations']==[]
    assert advance(client,order,'dealer_confirmed').status_code==200


def test_historical_lender_correction_updates_only_old_unallocated_context(setup):
    client,_,store,order,_=prepared(setup)
    old_reference='PRIVATE-old-seller-funding'
    assert post_funding(client,order,funding_body(100000,old_reference)).status_code==200
    with store.transaction() as db:
        profile=json.loads(db.execute('SELECT dealer_profile FROM orders WHERE id=?',(order['id'],)).fetchone()[0])
        profile['legal_name']='New quoted fixture retail seller'
        db.execute('UPDATE dealers SET profile=? WHERE id=?',(json.dumps(profile),'fixture-dealer'))
        db.execute('UPDATE orders SET quote_version=2,dealer_profile=? WHERE id=?',(json.dumps(profile),order['id']))
    assert post_funding(client,order,funding_body(500000,'PRIVATE-current-seller-funding',quote_version=2)).status_code==200
    before=summary(client,order)
    assert before['lender_funded_cents']==500000 and before['prior_quote_unallocated_lender_cents']==100000
    with store.connect() as db:
        current_detail=db.execute('SELECT financing_detail FROM orders WHERE id=?',(order['id'],)).fetchone()[0]
    body=correction_body(old_reference,25000)
    assert correct(client,order,body).status_code==200
    assert correct(client,order,body).status_code==200
    after=summary(client,order)
    assert after['lender_funded_cents']==500000 and after['prior_quote_unallocated_lender_cents']==25000
    assert correct(client,order,correction_body(old_reference,0)).status_code==409
    assert correct(client,order,correction_body(body['correction_reference'],0,quote_version=2)).status_code==409
    with store.connect() as db:
        assert db.execute('SELECT financing_detail FROM orders WHERE id=?',(order['id'],)).fetchone()[0]==current_detail
    current=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert current['financing']['funded_amount_cents']==500000
    assert current['financing']['state']=='lender_funded'


def clone_order(store,order):
    other_id=str(uuid.uuid4())
    with store.transaction() as db:
        original=dict(db.execute('SELECT * FROM orders WHERE id=?',(order['id'],)).fetchone())
        original.update(id=other_id,access_hash='other-access-'+other_id,request_key='other-key-'+other_id,request_hash='other-hash',
                        checkout_id=None,payment_id='pi_other_'+other_id,balance_checkout_id=None,balance_payment_id=None,
                        financing_state='not_requested',financing_detail=None)
        columns=list(original)
        db.execute('INSERT INTO orders('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(original[k] for k in columns))
    return {'id':other_id}


def test_cross_kind_and_processor_reference_reuse_is_rejected_across_orders(setup):
    client,_,store,order,_=prepared(setup)
    loan=funding_body(100000);assert post_funding(client,order,loan).status_code==200
    other=clone_order(store,order)
    assert receipt(client,other,receipt_body(receipt_reference=loan['reference'])).status_code==409
    cash=receipt_body();assert receipt(client,order,cash).status_code==200
    assert post_funding(client,other,funding_body(1,cash['receipt_reference'])).status_code==409
    with store.transaction() as db:
        payment_id=db.execute('SELECT payment_id FROM orders WHERE id=?',(order['id'],)).fetchone()[0]
        db.execute("UPDATE orders SET balance_payment_id='pi_existing_full_balance' WHERE id=?",(order['id'],))
    for reserved in [payment_id,'pi_existing_full_balance']:
        assert receipt(client,other,receipt_body(receipt_reference=reserved)).status_code==409
        assert post_funding(client,other,funding_body(1,reserved)).status_code==409


def test_legacy_reference_cannot_be_mutated_or_reused_after_mutable_status_changes(setup):
    client,_,store,order,_=prepared(setup)
    original='PRIVATE-historical-bank-wire'
    detail={'state':'lender_funded','provider':'Fixture lender','reference':original,'funded_amount_cents':100000}
    with store.transaction() as db:
        store.event(db,order['id'],'financing_lender_funded',detail)
        db.execute("UPDATE orders SET financing_state='declined',financing_detail=? WHERE id=?",(json.dumps({**detail,'state':'declined','reference':'PRIVATE-later-status'}),order['id']))
    assert receipt(client,order,receipt_body(receipt_reference=original)).status_code==409
    assert post_funding(client,order,funding_body(100001,original)).status_code==409
    other=clone_order(store,order)
    assert post_funding(client,other,funding_body(100000,original)).status_code==409


def test_new_reference_fields_reject_rotating_urls(setup):
    client,_,_,order,_=prepared(setup)
    assert post_funding(client,order,funding_body(100000,'https://example.test/rotating-proof')).status_code==422
    assert receipt(client,order,receipt_body(receipt_reference='https://example.test/rotating-proof')).status_code==422


def test_closed_legacy_funding_can_be_corrected_by_linking_real_event_without_backfill(setup):
    client,payments,store,order,quote=prepared(setup)
    original='PRIVATE-authentic-legacy-event'
    detail={'state':'lender_funded','provider':'Fixture lender','reference':original,
            'funded_amount_cents':quote['balance_after_deposit_cents'],'approved_amount_cents':0,
            'stipulations':[],'application_url':''}
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='completed',financing_state='lender_funded',financing_detail=? WHERE id=?",(json.dumps(detail),order['id']))
        store.event(db,order['id'],'financing_lender_funded',detail)
        event_id=db.execute('SELECT MAX(id) FROM events WHERE order_id=?',(order['id'],)).fetchone()[0]
    body=correction_body(original,0)
    assert correct(client,order,body).status_code==200
    assert correct(client,order,body).status_code==200
    current=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert current['state']=='completed' and current['funding_summary']['lender_funded_cents']==0
    assert current['financing']['state']=='funding_reconciled'
    with store.connect() as db:
        observations=db.execute('SELECT kind,legacy_prior_event_id FROM lender_funding_observations').fetchall()
        assert [tuple(row) for row in observations]==[('correction',event_id)]
    assert correct(client,order,correction_body(original,100)).status_code==409
    assert payments.refunds==0
