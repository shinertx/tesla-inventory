"""Customer support retries preserve one receipt without exposing operator data."""
from concurrent.futures import ThreadPoolExecutor
import uuid

import pytest

from test_transactions import setup, request, auth, admin


def submit(client, order, key=None, body=None):
    headers=auth(order)
    if key is not None:headers['Idempotency-Key']=key
    return client.post(f"/api/orders/{order['id']}/cases",json=body or {
        'kind':'title_delay','description':'Please confirm my title status.'},headers=headers)


def test_case_retry_reuses_receipt_and_returns_current_status(setup):
    client,_,_,store=setup;order=request(client);key=str(uuid.uuid4())
    first=submit(client,order,key);assert first.status_code==201
    receipt=first.json();assert receipt['kind']=='title_delay'
    replay=submit(client,order,key);assert replay.status_code==200 and replay.json()==receipt
    assert client.post('/api/admin/cases/'+receipt['id'],json={
        'status':'resolved','owner':'Private operator','evidence':'private:operator-record'},headers=admin()).status_code==200
    resolved=submit(client,order,key)
    assert resolved.status_code==200 and resolved.json()['id']==receipt['id']
    assert resolved.json()['status']=='resolved'
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM cases WHERE order_id=?',(order['id'],)).fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM events WHERE order_id=? AND kind='customer_case_opened'",(order['id'],)).fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM outbox WHERE order_id=? AND kind='customer_case_opened'",(order['id'],)).fetchone()[0]==1
        stored=db.execute('SELECT request_key FROM case_request_keys WHERE order_id=?',(order['id'],)).fetchone()[0]
        assert stored!=key


def test_case_key_rejects_changed_payload(setup):
    client,_,_,_=setup;order=request(client);key=str(uuid.uuid4())
    assert submit(client,order,key).status_code==201
    changed=submit(client,order,key,{'kind':'warranty','description':'A different support request.'})
    assert changed.status_code==409
    assert len(client.get(f"/api/orders/{order['id']}/cases",headers=auth(order)).json()['items'])==1


def test_case_replay_and_list_require_the_correct_order_access(setup):
    client,_,_,_=setup;first=request(client);second=request(client);key=str(uuid.uuid4())
    receipt=submit(client,first,key).json()
    path=f"/api/orders/{first['id']}/cases"
    for headers in ({},auth(second)):
        assert client.get(path,headers=headers).status_code==404
        assert client.post(path,json={'kind':'title_delay','description':'Please confirm my title status.'},
                           headers={**headers,'Idempotency-Key':key}).status_code==404
    other=submit(client,second,key)
    assert other.status_code==201 and other.json()['id']!=receipt['id']
    assert [r['id'] for r in client.get(f"/api/orders/{second['id']}/cases",headers=auth(second)).json()['items']]==[other.json()['id']]


def test_case_list_does_not_expose_operator_fields(setup):
    client,_,_,_=setup;order=request(client);receipt=submit(client,order,str(uuid.uuid4())).json()
    assert client.post('/api/admin/cases/'+receipt['id'],json={
        'status':'in_review','owner':'Private operator','evidence':'private:operator-record'},headers=admin()).status_code==200
    items=client.get(f"/api/orders/{order['id']}/cases",headers=auth(order)).json()['items']
    assert len(items)==1 and items[0]['status']=='in_review'
    assert set(items[0])=={'id','kind','description','status','created_at','due_at'}
    assert 'Private operator' not in str(items) and 'private:operator-record' not in str(items)


def test_case_submission_without_key_remains_backward_compatible(setup):
    client,_,_,_=setup;order=request(client)
    first=submit(client,order);second=submit(client,order)
    assert first.status_code==second.status_code==201
    assert first.json()['id']!=second.json()['id']


def test_open_case_cap_allows_replay_but_rejects_new_cases(setup):
    client,_,_,_=setup;order=request(client)
    keys=[str(uuid.uuid4()) for _ in range(6)]
    receipts=[submit(client,order,key).json() for key in keys[:5]]
    retry=submit(client,order,keys[0]);assert retry.status_code==200 and retry.json()['id']==receipts[0]['id']
    assert submit(client,order,keys[5]).status_code==409
    assert client.post('/api/admin/cases/'+receipts[0]['id'],json={
        'status':'resolved','owner':'Operator','evidence':'resolved:test-case'},headers=admin()).status_code==200
    assert submit(client,order,keys[5]).status_code==201


def test_concurrent_same_key_creates_one_case_and_notification(setup):
    client,_,_,store=setup;order=request(client);key=str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:submit(client,order,key),range(8)))
    assert sorted(r.status_code for r in results)==[200]*7+[201]
    assert len({r.json()['id'] for r in results})==1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM cases WHERE order_id=?',(order['id'],)).fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM outbox WHERE order_id=? AND kind='customer_case_opened'",(order['id'],)).fetchone()[0]==1


def test_concurrent_unique_keys_cannot_exceed_open_case_cap(setup):
    client,_,_,store=setup;order=request(client)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda key:submit(client,order,key),[str(uuid.uuid4()) for _ in range(8)]))
    assert sorted(r.status_code for r in results)==[201]*5+[409]*3
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM cases WHERE order_id=?',(order['id'],)).fetchone()[0]==5


@pytest.mark.parametrize('key',['too-short','x'*101,''])
def test_case_request_key_length_is_bounded(setup,key):
    client,_,_,_=setup;order=request(client)
    assert submit(client,order,key).status_code==400
    assert client.get(f"/api/orders/{order['id']}/cases",headers=auth(order)).json()=={'items':[]}
