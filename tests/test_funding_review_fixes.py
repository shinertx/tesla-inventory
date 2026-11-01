"""Finite review regressions: closure meaning, legacy contexts, and canonical IDs."""
import json
import time
import uuid

import pytest
from app.funding import seller_key
from test_transactions import setup, request, customer, approve, auth, admin
from test_funding_coverage import prepared, record_funding
from test_buyer_cash import receipt_body, receipt, reversal_body, reverse, summary
from test_lender_observations import funding_body, post_funding, correction_body, correct, clone_order


def legacy_funding(store,order,amount,reference):
    detail={'state':'lender_funded','provider':'Fixture lender','reference':reference,
            'funded_amount_cents':amount,'approved_amount_cents':0,'stipulations':[],'application_url':''}
    with store.transaction() as db:
        db.execute("UPDATE orders SET financing_state='lender_funded',financing_detail=? WHERE id=?",(json.dumps(detail),order['id']))
        store.event(db,order['id'],'financing_lender_funded',detail)
    return detail


def test_completed_valid_cash_is_clear_but_later_shortfall_requires_informational_review(setup):
    client,payments,store,order,quote=prepared(setup,financed=False)
    entry=receipt(client,order,receipt_body(quote['balance_after_deposit_cents'])).json()['entry']
    with store.transaction() as db:db.execute("UPDATE orders SET state='completed' WHERE id=?",(order['id'],))
    funds=summary(client,order)
    assert funds['coverage_complete'] is True and funds['funds_review_required'] is False
    assert funds['balance_checkout_allowed'] is False
    assert reverse(client,order,reversal_body(entry,1)).status_code==200
    after=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert after['state']=='completed' and after['funding_summary']['remaining_cents']==1
    assert after['funding_summary']['funds_review_required'] is True
    assert after['funding_summary']['balance_checkout_allowed'] is False and payments.refunds==0


@pytest.mark.parametrize('closed',['cancelled','refunded','refund_pending'])
def test_cancelled_retained_lender_funds_review_clears_after_observed_return(setup,closed):
    client,_,store,order,quote=prepared(setup)
    reference='wire:retained-lender'
    assert post_funding(client,order,funding_body(quote['balance_after_deposit_cents'],reference)).status_code==200
    with store.transaction() as db:db.execute('UPDATE orders SET state=? WHERE id=?',(closed,order['id']))
    assert summary(client,order)['funds_review_required'] is True
    assert correct(client,order,correction_body(reference,0)).status_code==200
    current=client.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert current['state']==closed and current['funding_summary']['lender_funded_cents']==0
    assert current['funding_summary']['funds_review_required'] is False
    assert current['funding_summary']['balance_checkout_allowed'] is False


def test_cancelled_retained_cash_and_bank_funds_are_reviewable(setup):
    client,_,store,order,quote=prepared(setup,financed=False)
    entry=receipt(client,order,receipt_body()).json()['entry']
    with store.transaction() as db:db.execute("UPDATE orders SET state='cancelled' WHERE id=?",(order['id'],))
    assert summary(client,order)['funds_review_required'] is True
    assert reverse(client,order,reversal_body(entry,400000)).status_code==200
    assert summary(client,order)['funds_review_required'] is False
    with store.transaction() as db:
        db.execute("UPDATE orders SET balance_payment_state='paid',balance_payment_id='pi_recorded_balance' WHERE id=?",(order['id'],))
        store.event(db,order['id'],'balance_payment_settled',{'balance_payment_id':'pi_recorded_balance','amount_cents':quote['balance_after_deposit_cents']})
    assert summary(client,order)['funds_review_required'] is True


def test_legacy_prior_quote_survives_new_registry_and_cumulative_history_is_not_summed(setup):
    client,_,_,store=setup
    order=request(client,body={**customer(),'payment_preference':'partner_financing'})
    approve(client,order)
    legacy_funding(store,order,100000,'wire:legacy-first')
    legacy_funding(store,order,200000,'wire:legacy-latest')
    approve(client,order)  # An actual second approval event, not an invented version.
    before=summary(client,order)
    assert before['prior_quote_unallocated_lender_cents']==200000 and before['funds_review_required'] is True
    assert post_funding(client,order,funding_body(3156250,'wire:quote-two',quote_version=2)).status_code==200
    funds=summary(client,order)
    assert funds['lender_funded_cents']==3156250
    assert funds['prior_quote_unallocated_lender_cents']==200000 and funds['funds_review_required'] is True
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM lender_funding_observations').fetchone()[0]==1


def test_registry_snapshot_replaces_older_cumulative_history_in_same_provable_context(setup):
    client,_,_,store=setup
    order=request(client);approve(client,order)
    legacy_funding(store,order,100000,'wire:old-current-context')
    assert post_funding(client,order,funding_body(200000,'wire:new-current-net')).status_code==200
    funds=summary(client,order)
    assert funds['lender_funded_cents']==200000 and funds['prior_quote_unallocated_lender_cents']==0
    assert funds['funds_review_required'] is False


def test_corrected_legacy_context_is_not_resurrected_as_prior_funds(setup):
    client,_,_,store=setup
    order=request(client);approve(client,order)
    legacy_funding(store,order,100000,'wire:old-cumulative-one')
    legacy_funding(store,order,200000,'wire:old-cumulative-two')
    assert correct(client,order,correction_body('wire:old-cumulative-two',0)).status_code==200
    approve(client,order)
    assert post_funding(client,order,funding_body(100000,'wire:new-quote-net',quote_version=2)).status_code==200
    funds=summary(client,order)
    assert funds['lender_funded_cents']==100000 and funds['prior_quote_unallocated_lender_cents']==0


def test_ambiguous_legacy_binding_stays_reviewable_after_new_observation(setup):
    client,_,_,store=setup
    order=request(client)
    legacy_funding(store,order,100000,'wire:before-any-known-quote')
    approve(client,order)
    assert post_funding(client,order,funding_body(200000,'wire:known-current-quote')).status_code==200
    assert summary(client,order)['funds_review_required'] is True


def test_trimmed_receipt_and_reversal_retries_are_idempotent_without_changing_id_case(setup):
    client,_,store,order,_=prepared(setup)
    raw=receipt_body(receipt_reference=' \tWire-AbC 123\n',evidence_reference=' \t proof:AbC \n')
    first=receipt(client,order,raw)
    assert first.status_code==200,first.text
    canonical={**raw,'receipt_reference':'Wire-AbC 123','evidence_reference':'proof:AbC'}
    assert receipt(client,order,canonical).json()['entry']==first.json()['entry']
    body=reversal_body(first.json()['entry'],1,reversal_reference=' \tReturn-AbC\n',evidence_reference=' proof:Return ')
    reversed_once=reverse(client,order,body)
    assert reversed_once.status_code==200
    assert reverse(client,order,{**body,'reversal_reference':'Return-AbC','evidence_reference':'proof:Return'}).json()['entry']==reversed_once.json()['entry']
    with store.connect() as db:
        assert [r[0] for r in db.execute('SELECT reference FROM buyer_cash_entries ORDER BY kind')]==['Wire-AbC 123','Return-AbC']
        assert db.execute('SELECT COUNT(*) FROM buyer_cash_entries').fetchone()[0]==2


def test_padded_lender_correction_and_expected_prior_are_canonical_before_hashing(setup):
    client,_,store,order,_=prepared(setup)
    body=funding_body(100000,' \tLoan-AbC\n')
    assert post_funding(client,order,body).status_code==200
    assert post_funding(client,order,{**body,'reference':'Loan-AbC'}).status_code==200
    correction=correction_body(' \tLoan-AbC\n',99999,correction_reference=' \tCorrection-AbC\n',evidence_reference=' proof:correct ')
    assert correct(client,order,correction).status_code==200
    assert correct(client,order,{**correction,'expected_prior_reference':'Loan-AbC','correction_reference':'Correction-AbC','evidence_reference':'proof:correct'}).status_code==200
    with store.connect() as db:assert db.execute('SELECT COUNT(*) FROM lender_funding_observations').fetchone()[0]==2


def test_padded_references_cannot_be_reused_across_orders_or_as_urls(setup):
    client,_,store,order,_=prepared(setup)
    body=receipt_body(receipt_reference='Wire-12345');assert receipt(client,order,body).status_code==200
    other=clone_order(store,order)
    assert receipt(client,other,receipt_body(receipt_reference=' \tWire-12345\n')).status_code==409
    assert post_funding(client,other,funding_body(1,' \tWire-12345\n')).status_code==409
    assert receipt(client,order,receipt_body(receipt_reference=' \thttps://example.test/rotating \n')).status_code==422
    assert post_funding(client,order,funding_body(1,' \thttps://example.test/rotating \n')).status_code==422
    assert receipt(client,order,receipt_body(evidence_reference=' \t \n ')).status_code==422
    assert correct(client,order,correction_body('Wire-12345',0,evidence_reference=' \t \n ')).status_code==422


def test_historical_padded_ids_are_compared_canonically_without_rewriting_history(setup):
    client,_,store,order,_=prepared(setup)
    raw=' \tHistorical-Wire-123\n'
    with store.transaction() as db:
        row=db.execute('SELECT * FROM orders WHERE id=?',(order['id'],)).fetchone()
        db.execute('INSERT INTO buyer_cash_entries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
            str(uuid.uuid4()),raw,'receipt',order['id'],1,'fixture-dealer',seller_key(row),100000,'USD',None,
            'proof:historical',int(time.time()),int(time.time()),'original-legacy-payload-hash'))
    other=clone_order(store,order)
    assert receipt(client,other,receipt_body(receipt_reference='Historical-Wire-123')).status_code==409
    assert post_funding(client,other,funding_body(1,'Historical-Wire-123')).status_code==409
    with store.connect() as db:assert db.execute('SELECT reference FROM buyer_cash_entries').fetchone()[0]==raw
    old=legacy_funding(store,order,100000,' \tHistorical-Loan-123\n')
    assert receipt(client,other,receipt_body(receipt_reference='Historical-Loan-123')).status_code==409
    with store.connect() as db:
        saved=json.loads(db.execute("SELECT detail FROM events WHERE kind='financing_lender_funded' ORDER BY id DESC LIMIT 1").fetchone()[0])
        assert saved['reference']==old['reference']
