"""Own-account deposit scope, identity, and branding; SDK calls are mocked."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import stripe
from app.payments import StripePayments

PIN='acct_fixturePlatform'
ORDER={'id':'fixture-order','vin':'5YJ3E1EA8SF921313','quote_version':2,'payment_account':PIN,'payment_id':'pi_fixture'}


def settings(**changes):
    return SimpleNamespace(deposit_collection_mode='platform',stripe_platform_account=PIN,
        stripe_key='sk_test_fixture',checkout_ui_mode='embedded_page',origin='https://example.test',
        payment_method_types=('card',),platform_collection_legal_name='JENNI PRO INC',**changes)


@pytest.fixture
def sdk(monkeypatch):
    calls={}
    for name,target,method,result in [
        ('account',stripe.Account,'retrieve',{'id':PIN,'charges_enabled':True,'details_submitted':True}),
        ('create',stripe.checkout.Session,'create',{'id':'cs_fixture'}),
        ('retrieve',stripe.checkout.Session,'retrieve',{'id':'cs_fixture'}),
        ('expire',stripe.checkout.Session,'expire',{'id':'cs_fixture','status':'expired'}),
        ('refund',stripe.Refund,'create',{'id':'re_fixture'})]:
        calls[name]=Mock(return_value=result);monkeypatch.setattr(target,method,calls[name])
    return calls


def test_platform_deposit_identity_scope_amount_and_session_branding(sdk):
    provider=StripePayments(settings());provider.create_checkout(ORDER,{},4102444800)
    sdk['account'].assert_called_once_with(api_key='sk_test_fixture')
    params=sdk['create'].call_args.kwargs
    assert 'stripe_account' not in params
    assert params['line_items'][0]['price_data']['unit_amount']==25000
    assert params['line_items'][0]['quantity']==1 and params['payment_method_types']==['card']
    assert params['branding_settings']=={'display_name':'Volts & VINs'}
    assert 'Volts & VINs' in params['line_items'][0]['price_data']['product_data']['name']
    assert 'JENNI PRO INC' in params['custom_text']['submit']['message']
    assert 'refundable under the accepted reservation terms' in params['custom_text']['submit']['message']
    assert params['metadata']=={'order_id':'fixture-order','quote_version':'2','vin':ORDER['vin'],'payment_stage':'deposit','brand':'Volts & VINs'}
    assert not {'on_behalf_of','transfer_data','application_fee_amount'} & params.keys()


@pytest.mark.parametrize('response',[{'id':'acct_wrong','charges_enabled':True,'details_submitted':True},
    {'id':PIN,'charges_enabled':False,'details_submitted':True},
    {'id':PIN,'charges_enabled':True,'details_submitted':False},
    {'id':PIN,'charges_enabled':'true','details_submitted':True}])
def test_platform_new_checkout_fails_closed_on_wrong_identity_or_capabilities(sdk,response):
    sdk['account'].return_value=response
    with pytest.raises(ValueError,match='identity or charging capability'):
        StripePayments(settings()).create_checkout(ORDER,{},4102444800)
    sdk['create'].assert_not_called()


@pytest.mark.parametrize('account',['acct_wrong','',None,' acct_fixturePlatform','acct_'])
def test_platform_wrong_checkout_pin_cannot_reach_sdk(sdk,account):
    with pytest.raises(ValueError):StripePayments(settings()).create_checkout({**ORDER,'payment_account':account},{},4102444800)
    sdk['account'].assert_not_called();sdk['create'].assert_not_called()


def test_platform_historical_outcomes_keep_own_scope_without_capability_lookup(sdk):
    provider=StripePayments(settings());sdk['account'].side_effect=AssertionError('No new checkout capability check for historical outcomes')
    provider.retrieve_checkout('cs_fixture',PIN);provider.expire_checkout('cs_fixture',PIN);provider.refund(ORDER)
    for operation in ('retrieve','expire','refund'):assert 'stripe_account' not in sdk[operation].call_args.kwargs
    assert sdk['refund'].call_args.kwargs['amount']==25000


def test_platform_preserves_bound_historical_connected_dealer_outcomes(sdk):
    provider=StripePayments(settings());account='acct_historicalDealer'
    provider.retrieve_checkout('cs_old',account);provider.expire_checkout('cs_old',account);provider.refund({**ORDER,'payment_account':account})
    for operation in ('retrieve','expire','refund'):assert sdk[operation].call_args.kwargs['stripe_account']==account
    sdk['account'].assert_not_called()


def test_platform_never_creates_vehicle_balance(sdk):
    with pytest.raises(ValueError,match='does not support vehicle balance'):
        StripePayments(settings()).create_balance_ach_checkout(ORDER,{'total_cents':3000000},4102444800)
    sdk['create'].assert_not_called();sdk['account'].assert_not_called()


def test_dealer_direct_behavior_keeps_connected_scope(sdk):
    config=settings();config.deposit_collection_mode='dealer_direct'
    provider=StripePayments(config);order={**ORDER,'payment_account':'acct_seller'}
    assert provider.dealer_can_charge('acct_seller')
    sdk['account'].assert_called_once_with('acct_seller',api_key='sk_test_fixture')
    provider.create_checkout(order,{},4102444800)
    assert sdk['create'].call_args.kwargs['stripe_account']=='acct_seller'
    assert 'branding_settings' not in sdk['create'].call_args.kwargs


@pytest.mark.parametrize('pin',['','acct_','bad_pin',' acct_fixturePlatform'])
def test_malformed_platform_pin_never_falls_back_to_own_account(sdk,pin):
    config=settings();config.stripe_platform_account=pin
    with pytest.raises(ValueError):StripePayments(config).retrieve_checkout('cs_fixture',PIN)
    sdk['retrieve'].assert_not_called()


def test_historical_platform_scope_survives_switch_to_dealer_direct(sdk):
    config=settings();config.deposit_collection_mode='dealer_direct'
    provider=StripePayments(config)
    provider.retrieve_checkout('cs_platform_history',PIN)
    provider.expire_checkout('cs_platform_history',PIN)
    provider.refund(ORDER)
    for operation in ('retrieve','expire','refund'):
        assert 'stripe_account' not in sdk[operation].call_args.kwargs
    sdk['account'].assert_not_called()
    with pytest.raises(ValueError,match='cannot charge the platform'):
        provider.create_checkout(ORDER,{},4102444800)
    with pytest.raises(ValueError,match='cannot charge the platform'):
        provider.create_balance_ach_checkout(ORDER,{'total_cents':3000000},4102444800)
    sdk['create'].assert_not_called()


def test_other_historical_account_never_becomes_own_scope_after_mode_change(sdk):
    config=settings();config.deposit_collection_mode='dealer_direct'
    provider=StripePayments(config);other='acct_otherHistorical'
    provider.retrieve_checkout('cs_old',other);provider.expire_checkout('cs_old',other)
    provider.refund({**ORDER,'payment_account':other})
    for operation in ('retrieve','expire','refund'):
        assert sdk[operation].call_args.kwargs['stripe_account']==other


def test_platform_submit_copy_uses_configured_legal_name(sdk):
    config=settings();config.platform_collection_legal_name='OTHER VERIFIED LEGAL ENTITY'
    StripePayments(config).create_checkout(ORDER,{},4102444800)
    message=sdk['create'].call_args.kwargs['custom_text']['submit']['message']
    assert 'OTHER VERIFIED LEGAL ENTITY' in message and 'JENNI PRO INC' not in message


@pytest.mark.parametrize('name',['','   ',None])
def test_platform_missing_legal_name_fails_before_new_checkout(sdk,name):
    config=settings();config.platform_collection_legal_name=name
    with pytest.raises(ValueError,match='legal name'):
        StripePayments(config).create_checkout(ORDER,{},4102444800)
    sdk['create'].assert_not_called();sdk['account'].assert_not_called()
