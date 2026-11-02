"""Key prefixes classify mode; they do not establish permissions or real payment readiness."""
from dataclasses import replace
import uuid

import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from test_transactions import setup, request, approve, checkout, event, auth, admin, status

PREFIXES = ('sk_test_', 'rk_test_', 'sk_live_', 'rk_live_')


def ready(prefix, **changes):
    mode = 'live' if 'live' in prefix else 'test'
    settings = Settings(stripe_key=prefix + 'fixture', stripe_publishable_key='pk_' + mode + '_fixture',
        webhook_secret='whsec_fixture', origin='https://example.test',
        platform_agreements_verified=True, checkout_enabled=True, supported_states=('TX',))
    return replace(settings, **changes)


@pytest.mark.parametrize('prefix', PREFIXES)
def test_account_secret_and_restricted_prefixes_have_the_same_mode(prefix):
    settings = ready(prefix)
    expected = 'live' if 'live' in prefix else 'test'
    assert settings.stripe_mode == expected and settings.payments_ready
    assert not settings.is_test_sandbox
    assert not replace(settings, checkout_enabled=False).payments_ready
    assert not replace(settings, webhook_secret='').payments_ready
    assert not replace(settings, stripe_publishable_key='pk_' + ('test' if expected == 'live' else 'live') + '_fixture').payments_ready
    assert not replace(settings, stripe_publishable_key='pk_' + expected + '_').payments_ready
    assert not replace(settings, stripe_publishable_key='pk_' + expected + '_fixture\n').payments_ready


@pytest.mark.parametrize('key', ['', 'pk_test_fixture', 'pk_live_fixture', 'sk_org_fixture', 'rk_fixture',
    'sk_test_', 'rk_live_', 'rk_live_fixture\n', 'unknown'])
def test_other_or_malformed_key_kinds_never_enable_payment_or_sandbox_bypass(key):
    settings = ready('sk_test_', stripe_key=key, sandbox_mode=True, platform_agreements_verified=False)
    assert settings.stripe_mode is None
    assert not settings.is_test_sandbox and not settings.agreements_gate_passed and not settings.payments_ready


@pytest.mark.parametrize('prefix', PREFIXES)
def test_only_explicit_test_keys_can_use_sandbox_agreement_bypass(prefix):
    settings = ready(prefix, sandbox_mode=True, platform_agreements_verified=False)
    test_mode = 'test' in prefix
    assert settings.is_test_sandbox is test_mode
    assert settings.agreements_gate_passed is test_mode
    assert settings.payments_ready is test_mode
    if not test_mode:
        assert not replace(settings, platform_agreements_verified=True).payments_ready
        assert not ready(prefix, origin='http://example.test').payments_ready
        assert not ready(prefix, platform_agreements_verified=False).payments_ready
    else:
        assert not replace(settings, sandbox_mode=False).agreements_gate_passed


@pytest.mark.parametrize('prefix', PREFIXES)
def test_hosted_checkout_keeps_mode_and_live_gates_without_publishable_key(prefix):
    settings = ready(prefix, checkout_ui_mode='hosted_page', stripe_publishable_key='')
    assert settings.payments_ready
    assert not replace(settings, payment_method_types=('unsupported',)).payments_ready
    assert replace(settings, balance_checkout_enabled=True).balance_payments_ready
    assert not replace(settings, balance_checkout_enabled=True, balance_payment_method_types=('card',)).balance_payments_ready
    if 'live' in prefix:
        assert not replace(settings, origin='http://example.test').payments_ready


@pytest.mark.parametrize('prefix', PREFIXES)
def test_public_readiness_robots_and_admin_classification_agree(setup, prefix):
    _, original, payments, _ = setup
    settings = replace(original, stripe_key=prefix + 'fixture', origin='https://example.test',
        stripe_publishable_key='pk_' + ('live' if 'live' in prefix else 'test') + '_fixture')
    client = TestClient(create_app(settings, payments))
    response = client.get('/api/config')
    test_mode = 'test' in prefix
    assert response.json()['test_mode'] is test_mode
    assert response.json()['payments_enabled'] is True
    assert ('X-Robots-Tag' in response.headers) is test_mode
    report = client.get('/api/admin/integrations', headers=admin()).json()['deposits']
    assert report['test_mode'] is test_mode and report['enabled'] is True and report['missing'] == []
    if test_mode:
        assert 'Disallow: /' in client.get('/robots.txt').text
        assert client.get('/sitemap.xml').status_code == 404
    assert prefix + 'fixture' not in response.text


def configured_client(setup, prefix):
    _, original, payments, store = setup
    mode = 'live' if 'live' in prefix else 'test'
    settings = replace(original, stripe_key=prefix + 'fixture', stripe_publishable_key='pk_' + mode + '_fixture',
                       origin='https://example.test')
    return TestClient(create_app(settings, payments)), payments, store, mode == 'live'


@pytest.mark.parametrize('prefix', PREFIXES)
def test_canonical_deposit_session_rejects_opposite_mode_then_accepts_matching_mode(setup, prefix):
    client, payments, _, live = configured_client(setup, prefix)
    order = request(client); approve(client, order); assert checkout(client, order).status_code == 200
    assert event(client, payments, order, livemode=not live).status_code == 409
    assert status(client, order) == 'checkout_pending'
    assert event(client, payments, order, livemode=live).status_code == 200
    assert status(client, order) == 'deposit_paid'


@pytest.mark.parametrize('invalid', [None, 0, 1, 'false', 'true'])
def test_canonical_mode_must_be_a_boolean(setup, invalid):
    client, payments, _, _ = configured_client(setup, 'rk_test_')
    order = request(client); approve(client, order); checkout(client, order)
    assert event(client, payments, order, livemode=invalid).status_code == 409
    assert status(client, order) == 'checkout_pending'


@pytest.mark.parametrize('prefix', ('rk_test_', 'rk_live_'))
def test_canonical_balance_and_signed_refund_modes_remain_separate(setup, prefix):
    client, payments, store, live = configured_client(setup, prefix)
    order = request(client); approve(client, order); checkout(client, order)
    assert event(client, payments, order, livemode=live).status_code == 200
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='dealer_confirmed' WHERE id=?", (order['id'],))
    result = client.post('/api/orders/' + order['id'] + '/balance-checkout',
                        json={'quote_version': 1, 'terms_accepted': True}, headers=auth(order))
    assert result.status_code == 200
    session = next(s for s in payments.sessions.values() if s['metadata'].get('payment_stage') == 'balance_ach')
    session.update(status='complete', payment_status='paid', livemode=not live)
    def balance_event():
        return client.post('/api/stripe/webhook', json={'id': 'evt_' + str(uuid.uuid4()),
            'type': 'checkout.session.completed', 'account': session['account'],
            'data': {'object': {'id': session['id']}}}, headers={'Stripe-Signature': 'valid-test-signature'})
    assert balance_event().status_code == 409
    session['livemode'] = live
    assert balance_event().status_code == 200
    assert client.get('/api/orders/' + order['id'], headers=auth(order)).json()['balance_payment_state'] == 'paid'
    # A signed refund event has its own mode. No Stripe API request is made here.
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='refund_pending' WHERE id=?", (order['id'],))
    payload = {'id': 'evt_refund_' + str(uuid.uuid4()), 'type': 'refund.updated',
        'livemode': not live, 'account': 'acct_fixtureDealer', 'data': {'object': {
            'id': 're_fixture', 'payment_intent': 'pi_' + order['id'], 'amount': 25000, 'status': 'succeeded'}}}
    assert client.post('/api/stripe/webhook', json=payload, headers={'Stripe-Signature': 'valid-test-signature'}).status_code == 409
    assert status(client, order) == 'refund_pending'
    payload['livemode'] = live
    assert client.post('/api/stripe/webhook', json=payload, headers={'Stripe-Signature': 'valid-test-signature'}).status_code == 200
    assert status(client, order) == 'refunded'
    assert payments.refunds == 0


@pytest.mark.parametrize('prefix', PREFIXES)
def test_balance_collection_is_independent_and_disabled_by_default(prefix):
    settings = ready(prefix)
    assert settings.payments_ready and not settings.balance_checkout_enabled
    assert not settings.balance_payments_ready
    assert replace(settings, balance_checkout_enabled=True).balance_payments_ready
    # Invalid balance setup cannot disable or silently expand deposit acceptance.
    invalid = replace(settings, balance_checkout_enabled=True, balance_payment_method_types=('card',))
    assert invalid.payments_ready and not invalid.balance_payments_ready
    assert not replace(settings, balance_checkout_enabled=True, checkout_enabled=False).balance_payments_ready


def test_balance_switch_from_env_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv('BALANCE_CHECKOUT_ENABLED', raising=False)
    assert Settings.from_env().balance_checkout_enabled is False
    monkeypatch.setenv('BALANCE_CHECKOUT_ENABLED', 'true')
    assert Settings.from_env().balance_checkout_enabled is True


@pytest.mark.parametrize('prefix', ('rk_test_', 'rk_live_'))
def test_deposit_only_blocks_balance_and_stale_external_collection(setup, prefix):
    _, settings, payments, store = setup
    live = 'live' in prefix
    client = TestClient(create_app(replace(settings, stripe_key=prefix+'fixture',
        stripe_publishable_key='pk_'+('live' if live else 'test')+'_fixture',
        origin='https://example.test', balance_checkout_enabled=False), payments))
    config = client.get('/api/config').json()
    assert config['payments_enabled'] is True and config['payment_methods'] == ['card']
    assert config['balance_checkout_enabled'] is False and config['ach_enabled'] is False
    integrations = client.get('/api/admin/integrations', headers=admin()).json()
    assert integrations['deposits']['enabled'] is True and not integrations['balance']['enabled']
    order = request(client); approve(client, order)
    assert checkout(client, order).status_code == 200
    assert event(client, payments, order, livemode=live).status_code == 200
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='dealer_confirmed' WHERE id=?", (order['id'],))
        db.execute('INSERT INTO online_actions VALUES(?,?,?,?)',
            (order['id'], 'pay_balance', 'https://example.test/stale-payment', 'fixture:prior-approved-portal'))
    result = client.get('/api/orders/'+order['id'], headers=auth(order)).json()
    assert result['funding_summary']['balance_checkout_allowed'] is False
    assert all(a['kind'] != 'pay_balance' for a in result['online_actions'])
    before = payments.balance_calls
    denied = client.post('/api/orders/'+order['id']+'/balance-checkout',
        json={'quote_version':1,'terms_accepted':True}, headers=auth(order))
    assert denied.status_code == 409 and payments.balance_calls == before
    denied = client.post('/api/admin/orders/'+order['id']+'/online-actions', headers=admin(),
        json={'kind':'pay_balance','url':'https://example.test/new-payment','evidence_reference':'fixture:portal'})
    assert denied.status_code == 409
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM online_actions WHERE order_id=? AND kind='pay_balance'",(order['id'],)).fetchone()[0] == 1
    assert payments.session_calls == 1 and payments.refunds == 0


def test_disabled_balance_switch_still_reconciles_historical_balance_and_refund(setup):
    _, settings, payments, store = setup
    enabled = TestClient(create_app(replace(settings, balance_checkout_enabled=True), payments))
    order = request(enabled); approve(enabled, order); assert checkout(enabled, order).status_code == 200
    assert event(enabled, payments, order).status_code == 200
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='dealer_confirmed' WHERE id=?", (order['id'],))
    assert enabled.post('/api/orders/'+order['id']+'/balance-checkout',
        json={'quote_version':1,'terms_accepted':True}, headers=auth(order)).status_code == 200
    session = next(s for s in payments.sessions.values() if s['metadata'].get('payment_stage') == 'balance_ach')
    session.update(status='complete', payment_status='paid')
    disabled = TestClient(create_app(replace(settings, balance_checkout_enabled=False), payments))
    payload = {'id':'evt_balance_after_disable','type':'checkout.session.async_payment_succeeded',
        'account':session['account'],'data':{'object':{'id':session['id']}}}
    assert disabled.post('/api/stripe/webhook',json=payload,headers={'Stripe-Signature':'valid-test-signature'}).status_code == 200
    result = disabled.get('/api/orders/'+order['id'],headers=auth(order)).json()
    assert result['balance_payment_state'] == 'paid' and result['funding_summary']['settled_balance_cents'] > 0
    assert not result['funding_summary']['balance_checkout_allowed']
    with store.transaction() as db:
        db.execute("UPDATE orders SET state='refund_pending' WHERE id=?", (order['id'],))
    refund = {'id':'evt_refund_after_disable','type':'refund.updated','livemode':False,
        'account':'acct_fixtureDealer','data':{'object':{'id':'re_historical','payment_intent':'pi_'+order['id'],
        'amount':25000,'status':'succeeded'}}}
    assert disabled.post('/api/stripe/webhook',json=refund,headers={'Stripe-Signature':'valid-test-signature'}).status_code == 200
    assert status(disabled,order) == 'refunded' and payments.balance_calls == 1 and payments.refunds == 0
