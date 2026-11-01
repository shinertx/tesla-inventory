"""The static storefront uses the same private order API as the hosted app."""
import json
import uuid

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ORIGIN = 'https://voltsandvins.com'
VIN = '7SAYGDED1RF039277'


def configured(tmp_path):
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({'items': [{'vin': VIN}]}))
    return Settings(origin=ORIGIN, inventory_path=inventory,
                    db_path=tmp_path / 'orders.db')


def test_storefront_preflight_allows_required_headers_only(tmp_path):
    client = TestClient(create_app(configured(tmp_path)))
    response = client.options('/api/requests', headers={
        'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,idempotency-key,authorization'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == ORIGIN
    assert 'access-control-allow-credentials' not in response.headers
    assert 'Origin' in response.headers['vary']
    denied = client.options('/api/requests', headers={
        'Origin': 'https://untrusted.example', 'Access-Control-Request-Method': 'POST'})
    assert denied.status_code == 400
    assert 'access-control-allow-origin' not in denied.headers


def test_cross_origin_request_survives_restart_without_enabling_payment(tmp_path):
    settings = configured(tmp_path)
    client = TestClient(create_app(settings))
    response = client.post('/api/requests', json={
        'vin': VIN, 'name': 'Integration Test', 'email': 'test@example.test',
        'zip': '78701', 'state': 'TX', 'consent': True}, headers={
            'Origin': ORIGIN, 'Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 201
    assert response.headers['access-control-allow-origin'] == ORIGIN
    order = response.json()
    restarted = TestClient(create_app(settings))
    path = '/api/orders/' + order['id']
    headers = {'Origin': ORIGIN, 'Authorization': 'Bearer ' + order['access_token']}
    assert restarted.get(path, headers=headers).json()['state'] == 'requested'
    assert restarted.get(path, headers={'Origin': ORIGIN}).status_code == 404
    assert restarted.get('/api/admin/orders', headers={'Origin': ORIGIN}).status_code == 401
    assert restarted.get('/api/config').json()['payments_enabled'] is False
    assert restarted.get('/api/config').json()['ach_enabled'] is False
    assert restarted.post(path + '/checkout', headers=headers,
                          json={'quote_version': 1, 'terms_accepted': True}).status_code == 409


def test_untrusted_origin_cannot_create_request(tmp_path):
    app = create_app(configured(tmp_path))
    client = TestClient(app)
    response = client.post('/api/requests', json={}, headers={
        'Origin': 'https://untrusted.example', 'Idempotency-Key': str(uuid.uuid4())})
    assert response.status_code == 403
    assert 'access-control-allow-origin' not in response.headers
    with app.state.store.connect() as database:
        assert database.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 0
