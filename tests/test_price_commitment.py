"""Advertised vehicle prices become server-side ceilings, not client-controlled promises."""
import hashlib
import json
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store, SCHEMA
from test_transactions import setup, customer, request, auth, admin, approve, quote_body, VIN


@pytest.fixture
def priced(setup):
    _, settings, payments, store = setup
    catalog = {'meta': {'built_at': '2026-11-01T12:00:00Z'}, 'items': [{
        'vin': VIN, 'display_price': 29000, 'model': 'Cybertruck', 'year': 2024,
        'trim': 'AWD', 'reference_price': 31000, 'reference_sample': 8,
        'benchmark_date': '2026-11-01', 'pricing_basis': 'comparable_asking_prices',
        'savings_amount': 2000, 'source_ask': 'PRIVATE SOURCE COST',
    }]}
    settings.inventory_path.write_text(json.dumps(catalog))
    return TestClient(create_app(settings, payments)), settings, payments, store, catalog


def test_new_request_saves_server_price_revision_and_comparison(priced):
    client, settings, _, store, _ = priced
    order = request(client, body={**customer(), 'expected_vehicle_price_cents': 2900000})
    assert order['price_commitment'] == {'vehicle_price_cents': 2900000, 'scope': 'vehicle_price_only'}
    with store.connect() as db:
        snapshot = json.loads(db.execute('SELECT price_commitment FROM orders WHERE id=?', (order['id'],)).fetchone()[0])
    assert snapshot['vehicle_price_cents'] == 2900000
    assert snapshot['catalog_revision'] == hashlib.sha256(settings.inventory_path.read_bytes()).hexdigest()
    assert snapshot['catalog_built_at'] == '2026-11-01T12:00:00Z'
    assert snapshot['comparison'] == {'pricing_basis': 'comparable_asking_prices', 'reference_price': 31000,
        'reference_sample': 8, 'benchmark_date': '2026-11-01', 'savings_amount': 2000}
    assert 'PRIVATE SOURCE COST' not in json.dumps(snapshot) + json.dumps(order)


def test_price_ceiling_and_comparison_survive_catalog_change_and_idempotent_retry(priced):
    client, settings, payments, store, catalog = priced
    key = str(uuid.uuid4())
    body = {**customer(), 'expected_vehicle_price_cents': 2900000}
    order = request(client, key=key, body=body)
    catalog['items'][0].update(display_price=35000, reference_price=40000, savings_amount=5000)
    settings.inventory_path.write_text(json.dumps(catalog))
    restarted = TestClient(create_app(settings, payments))
    retried = request(restarted, key=key, body=body)
    assert retried['id'] == order['id'] and retried['price_commitment'] == order['price_commitment']
    assert retried['vehicle']['display_price'] == 29000 and retried['vehicle']['reference_price'] == 31000
    rejected = restarted.post('/api/admin/orders/' + order['id'] + '/quote',
        json=quote_body(vehicle_price_cents=2900001), headers=admin())
    assert rejected.status_code == 409 and 'exceeds the price saved' in rejected.json()['detail']
    assert restarted.get('/api/orders/' + order['id'], headers=auth(order)).json()['quote'] is None
    accepted = approve(restarted, order, vehicle_price_cents=2899900)
    assert accepted['quote']['vehicle_price_cents'] == 2899900
    assert accepted['quote']['vehicle_savings_cents'] == 200100
    assert payments.session_calls == 0
    with store.connect() as db:
        assert db.execute('SELECT quote_version FROM orders WHERE id=?', (order['id'],)).fetchone()[0] == 1


@pytest.mark.parametrize('expected', [2800000, 3000000])
def test_stale_or_client_chosen_price_cannot_create_request(priced, expected):
    client, _, payments, store, _ = priced
    response = client.post('/api/requests', json={**customer(), 'expected_vehicle_price_cents': expected},
                           headers={'Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 409 and 'Review the updated listing price' in response.json()['detail']
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
    assert payments.session_calls == 0


@pytest.mark.parametrize('expected', [0, -1, True, '2900000', 2900000.5])
def test_expected_price_requires_positive_integer_cents(priced, expected):
    client, _, _, _, _ = priced
    response = client.post('/api/requests', json={**customer(), 'expected_vehicle_price_cents': expected},
                           headers={'Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 422


def test_backward_client_gets_server_price_without_supplying_a_ceiling(priced):
    client, _, _, _, _ = priced
    assert request(client)['price_commitment']['vehicle_price_cents'] == 2900000


@pytest.mark.parametrize('price', [None, 0, True, float('inf')])
def test_missing_or_invalid_server_price_cannot_create_an_unprotected_request(priced, price):
    _, settings, payments, _, catalog = priced
    catalog['items'][0]['display_price'] = price
    settings.inventory_path.write_text(json.dumps(catalog))
    client = TestClient(create_app(settings, payments))
    response = client.post('/api/requests', json=customer(), headers={'Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 409


def test_legacy_request_has_no_fabricated_price_commitment(priced):
    client, _, payments, store, _ = priced
    order = request(client)
    with store.transaction() as db:
        db.execute('UPDATE orders SET price_commitment=NULL WHERE id=?', (order['id'],))
    response = client.get('/api/orders/' + order['id'], headers=auth(order))
    assert response.json()['price_commitment'] is None
    # Existing requests retain explicit-quote behavior rather than invented historical ceilings.
    approved = approve(client, order, vehicle_price_cents=3000000)
    assert approved['quote']['vehicle_price_cents'] == 3000000
    assert approved['price_commitment'] is None and payments.session_calls == 0
    assert client.post('/api/orders/' + order['id'] + '/cancel',
                       json={'reason': 'Changed plans'}, headers=auth(order)).status_code == 200


def test_existing_database_migration_leaves_old_rows_null(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO orders(id,access_hash,request_key,request_hash,vin,customer,state,created_at,updated_at,action_due_at) VALUES('old','h','k','r',?,'{}','requested',1,1,2)", (VIN,))
    store = Store(path)
    with store.connect() as db:
        assert db.execute("SELECT price_commitment,state FROM orders WHERE id='old'").fetchone()[:] == (None, 'requested')
