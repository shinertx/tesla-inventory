import copy
import json
import uuid
from datetime import datetime, timezone

import pytest

from tools.quarantine_inventory import quarantine
from app.catalog import catalog_exclusions
from tools.build import build
from test_transactions import setup, request, auth, admin, approve, quote_body, customer, VIN as API_VIN

VIN = '7G2CEHED8SA058834'
OTHER = '5YJ3E1EA8SF921313'
REASON = 'Reported title risk; quarantined pending authentic history review. Not a proven salvage determination.'


def fixture():
    return ({'meta': {'count': 2, 'reservable_count': 1, 'built_at': '2026-11-01T00:00:00Z',
                      'media_version': 'old', 'availability_note': 'unchanged'},
             'items': [{'vin': VIN, 'display_price': 62000, 'reservable': True},
                       {'vin': OTHER, 'display_price': 27431, 'reference_price': 31000,
                        'expires_at': '2026-11-07', 'hardware': None}]},
            {'01': {VIN: [{'url': 'https://example.test/review.jpg'}],
                    OTHER: [{'url': 'https://example.test/other.jpg'}]}, '02': {}},
            {OTHER: 'Existing exclusion remains unchanged'})


def test_quarantine_preserves_every_other_field_and_is_idempotent():
    catalog, shards, blocked = fixture()
    originals = copy.deepcopy((catalog, shards, blocked))
    after, media, exclusions, removed = quarantine(catalog, shards, blocked, VIN, REASON)
    assert removed == 1
    assert after['items'] == [catalog['items'][1]]
    assert after['meta'] == {**catalog['meta'], 'count': 1, 'reservable_count': 0,
                             'media_version': after['meta']['media_version']}
    assert after['meta']['media_version'] != 'old'
    assert media == {'01': {OTHER: shards['01'][OTHER]}, '02': {}}
    assert exclusions == {**blocked, VIN: REASON}
    assert (catalog, shards, blocked) == originals
    assert quarantine(after, media, exclusions, VIN, REASON) == (after, media, exclusions, 0)


def test_exclusion_blocks_absent_listing_without_changing_catalog_or_media():
    catalog, shards, blocked = fixture()
    catalog['items'] = [catalog['items'][1]]
    del shards['01'][VIN]
    after, media, exclusions, removed = quarantine(catalog, shards, blocked, VIN, REASON)
    assert removed == 0 and after == catalog and media == shards
    assert exclusions[VIN] == REASON


@pytest.mark.parametrize('vin,reason', [('invalid', REASON), (VIN, ''), (VIN, '   ')])
def test_invalid_quarantine_refused(vin, reason):
    with pytest.raises(ValueError):
        quarantine(*fixture(), vin, reason)


def test_future_build_cannot_reimport_quarantined_vin(tmp_path):
    source = tmp_path / 'source.json'
    now = datetime.now(timezone.utc)
    source.write_text(json.dumps({'items': [dict(vin=VIN, model='Cybertruck', year=2025,
        dealer_trim='Crew Cab AWD', asking_price=62000, mileage=11542, city='San Bernardino',
        state='CA', source_url='https://example.test/vehicle/' + VIN, risk_flag=False,
        imported_at=now.isoformat(), title_status='clean_verified',
        configuration_evidence_reference='stale-private-commitment')]}))
    result = build(source, tmp_path, now)
    assert result['items'] == []
    assert result['meta']['excluded']['title_or_condition_risk'] == 1


def exclusions_file(settings, content):
    path = settings.inventory_path.parent / 'data' / 'exclusions.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(content)


def test_running_api_blocks_excluded_vin_before_provider_calls_and_keeps_recovery(setup, monkeypatch):
    client, settings, payments, store = setup
    order = request(client)
    approve(client, order)
    # The app already loaded its stale inventory and approved private quote.
    exclusions_file(settings, json.dumps({API_VIN: REASON}))
    monkeypatch.setattr(payments, 'dealer_can_charge', lambda *a: pytest.fail('Provider called for excluded VIN'))
    assert client.post('/api/requests', json=customer(),
                       headers={'Idempotency-Key': str(uuid.uuid4())}).status_code == 409
    assert client.get('/api/vehicles/' + API_VIN + '/photos').status_code == 409
    assert client.post('/api/admin/orders/' + order['id'] + '/quote',
                       json=quote_body(), headers=admin()).status_code == 409
    acceptance = {'quote_version': 1, 'terms_accepted': True}
    assert client.post('/api/orders/' + order['id'] + '/checkout',
                       json=acceptance, headers=auth(order)).status_code == 409
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='dealer_confirmed' WHERE id=?", (order['id'],))
    assert client.post('/api/orders/' + order['id'] + '/balance-checkout',
                       json=acceptance, headers=auth(order)).status_code == 409
    assert payments.session_calls == payments.balance_calls == 0
    assert client.get('/api/orders/' + order['id'], headers=auth(order)).status_code == 200
    assert client.post('/api/orders/' + order['id'] + '/cases', json={
        'kind': 'other', 'description': 'Please review the vehicle history.'},
        headers={**auth(order), 'Idempotency-Key': str(uuid.uuid4())}).status_code in (200, 201)
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='quoted' WHERE id=?", (order['id'],))
    assert client.post('/api/orders/' + order['id'] + '/cancel',
                       json={'reason': 'History review pending'}, headers=auth(order)).status_code == 200


@pytest.mark.parametrize('raw', ['{broken', '[]', '{"VIN": null}'])
def test_present_malformed_exclusions_fail_closed(setup, raw):
    client, settings, payments, _ = setup
    exclusions_file(settings, raw)
    assert client.post('/api/requests', json=customer(),
                       headers={'Idempotency-Key': str(uuid.uuid4())}).status_code == 503
    assert payments.session_calls == payments.balance_calls == 0


def test_fixture_root_can_omit_exclusion_file(tmp_path):
    assert catalog_exclusions(tmp_path / 'inventory.json') == {}
