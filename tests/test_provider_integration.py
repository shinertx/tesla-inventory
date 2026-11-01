"""Local integration boundaries only; no live provider calls or account approval."""
from dataclasses import replace
import json
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.providers import CarrierPriceEstimate, ProviderNotConfigured, UnsupportedRoute

VIN='7SAYGDED1RF039277'
TOKEN='operator-fixture-'+'x'*40
ADMIN={'Authorization':'Bearer '+TOKEN}


class Shipping:
    def __init__(self):self.calls=[];self.error=None
    def recommended_price(self,**payload):
        self.calls.append(payload)
        if self.error:raise self.error
        return CarrierPriceEstimate('Super Dispatch',55029,75029,69,195,int(time.time()))


def setup(tmp_path,**changes):
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps({'items':[{'vin':VIN,'display_price':29000,'model':'Model Y','year':2024,'city':'Dallas','state':'TX'}]}))
    settings=Settings(db_path=tmp_path/'orders.db',inventory_path=inventory,origin='https://voltsandvins.com',
                      admin_token=TOKEN,super_dispatch_api_key='fixture-private-key',shipping_estimates_enabled=True)
    settings=replace(settings,**changes)
    shipping=Shipping();app=create_app(settings,shipping=shipping);client=TestClient(app)
    order=client.post('/api/requests',json={'vin':VIN,'name':'Provider Fixture','email':'fixture@example.test',
        'state':'TX','zip':'78701','consent':True},headers={'Idempotency-Key':str(uuid.uuid4())}).json()
    return client,settings,shipping,app.state.store,order


def path(order):return f"/api/admin/orders/{order['id']}/shipping-estimate"


def test_private_readiness_does_not_expose_secrets_or_imply_approval(tmp_path):
    client,_,_,_,_=setup(tmp_path)
    assert client.get('/api/admin/integrations').status_code==401
    result=client.get('/api/admin/integrations',headers=ADMIN)
    assert result.status_code==200 and result.headers['cache-control']=='no-store'
    assert 'fixture-private-key' not in result.text and TOKEN not in result.text
    data=result.json()
    assert not data['deposits']['enabled']
    assert 'approved_licensed_seller' in data['deposits']['missing']
    assert 'supported_sale_states' in data['deposits']['missing']
    assert data['shipping']['configured'] and data['shipping']['enabled']
    assert not data['shipping']['binding_carrier_quotes'] and not data['shipping']['carrier_booking']
    assert not data['financing']['applications_enabled']


def test_estimate_requires_operator_and_explicit_operability(tmp_path):
    client,_,shipping,_,order=setup(tmp_path)
    assert client.post(path(order),json={'is_inoperable':False}).status_code==401
    for body in ({},{'is_inoperable':'false'},{'is_inoperable':False,'dealer_id':'invented'}):
        assert client.post(path(order),json=body,headers=ADMIN).status_code==422
    assert not shipping.calls


def test_cached_estimate_survives_restart_without_approving_or_booking(tmp_path):
    client,settings,shipping,store,order=setup(tmp_path)
    first=client.post(path(order),json={'is_inoperable':False},headers=ADMIN)
    assert first.status_code==200,first.text
    data=first.json()
    assert data['customer_estimate_cents']==75029 and data['carrier_estimate_cents']==55029
    assert not data['binding'] and not data['carrier_booked']
    assert 'quote_reference' not in data and 'delivery_window_start' not in data
    assert 'request_hash' not in data
    assert shipping.calls==[{'pickup':{'city':'Dallas','state':'TX'},'delivery':{'zip':'78701'},
                            'vehicle':{'type':'suv','make':'Tesla','model':'Model Y','year':'2024','is_inoperable':False}}]
    repeated=client.post(path(order),json={'is_inoperable':False},headers=ADMIN)
    assert repeated.json()==data and len(shipping.calls)==1
    restarted=TestClient(create_app(settings,shipping=shipping))
    assert restarted.post(path(order),json={'is_inoperable':False},headers=ADMIN).json()==data
    assert len(shipping.calls)==1
    current=client.get('/api/orders/'+order['id'],headers={'Authorization':'Bearer '+order['access_token']}).json()
    assert current['state']=='requested' and current['quote'] is None
    assert current['transport']=={'state':'unquoted'}
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM holds').fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM events WHERE kind='shipping_estimate_received'").fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM outbox WHERE kind='shipping_estimate_received'").fetchone()[0]==0


@pytest.mark.parametrize('changes',[{'shipping_estimates_enabled':False},{'super_dispatch_api_key':''}])
def test_disabled_provider_never_calls_network(tmp_path,changes):
    client,_,shipping,_,order=setup(tmp_path,**changes)
    assert client.post(path(order),json={'is_inoperable':False},headers=ADMIN).status_code==503
    assert not shipping.calls


@pytest.mark.parametrize('error,status',[(ProviderNotConfigured('authentication'),503),(UnsupportedRoute('no_route_available'),422)])
def test_provider_failure_never_creates_a_commitment(tmp_path,error,status):
    client,_,shipping,store,order=setup(tmp_path);shipping.error=error
    result=client.post(path(order),json={'is_inoperable':False},headers=ADMIN)
    assert result.status_code==status
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE kind='shipping_estimate_received'").fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM holds').fetchone()[0]==0


def test_missing_sale_states_prevent_readiness_even_with_stripe_and_seller(tmp_path):
    client,_,_,store,_=setup(tmp_path,stripe_key='sk_test_fixture',stripe_publishable_key='pk_test_fixture',
        webhook_secret='whsec_fixture',checkout_enabled=True,platform_agreements_verified=True)
    with store.transaction() as db:
        db.execute('INSERT INTO dealers VALUES(?,?,?)',('fixture',json.dumps({'verified':True}),int(time.time())))
    data=client.get('/api/admin/integrations',headers=ADMIN).json()['deposits']
    assert data['enabled'] is False and data['missing']==['supported_sale_states']
    assert client.get('/api/config').json()['payments_enabled'] is False


def test_invalid_stripe_configuration_has_an_actionable_missing_gate(tmp_path):
    client,_,_,store,_=setup(tmp_path,stripe_key='invalid',stripe_publishable_key='invalid',webhook_secret='fixture',
        checkout_enabled=True,platform_agreements_verified=True,supported_states=('TX',))
    with store.transaction() as db:
        db.execute('INSERT INTO dealers VALUES(?,?,?)',('fixture',json.dumps({'verified':True}),int(time.time())))
    data=client.get('/api/admin/integrations',headers=ADMIN).json()['deposits']
    assert not data['enabled'] and 'stripe_secret_key' in data['missing'] and 'stripe_publishable_key' in data['missing']


def test_customer_receives_only_fresh_private_order_shipping_projection(tmp_path):
    client,settings,shipping,_,order=setup(tmp_path)
    assert client.post(path(order),json={'is_inoperable':False},headers=ADMIN).status_code==200
    public_path='/api/orders/'+order['id']
    access={'Authorization':'Bearer '+order['access_token']}
    assert client.get(public_path).status_code==404
    assert client.get(public_path,headers={'Authorization':'Bearer wrong'}).status_code==404
    result=client.get(public_path,headers=access).json()
    estimate=result['shipping_estimate']
    assert set(estimate)=={'provider','customer_estimate_cents','observed_at','cache_expires_at','binding','carrier_booked','notice'}
    assert estimate['customer_estimate_cents']==75029
    assert estimate['provider']=='Super Dispatch' and not estimate['binding'] and not estimate['carrier_booked']
    assert result['state']=='requested' and result['quote'] is None and result['transport']=={'state':'unquoted'}
    assert 'fixture-private-key' not in json.dumps(result) and 'carrier_estimate_cents' not in json.dumps(estimate)
    assert len(shipping.calls)==1  # Reading status never calls the paid provider.
    restarted=TestClient(create_app(settings,shipping=shipping))
    assert restarted.get(public_path,headers=access).json()['shipping_estimate']==estimate
    disabled=TestClient(create_app(replace(settings,shipping_estimates_enabled=False),shipping=shipping))
    assert disabled.get(public_path,headers=access).json()['shipping_estimate'] is None
    assert len(shipping.calls)==1


@pytest.mark.parametrize('change',[
    {'observed_at':0,'cache_expires_at':1},
    {'observed_at':4102444800,'cache_expires_at':4102445700},
    {'customer_estimate_cents':True},
    {'customer_estimate_cents':0},
    {'customer_estimate_cents':2000001},
    {'binding':True},
    {'carrier_booked':True},
    {'request_hash':'wrong-route'},
    {'cache_expires_at':4102444800},
])
def test_invalid_or_expired_provider_receipt_never_reaches_customer(tmp_path,change):
    client,_,shipping,store,order=setup(tmp_path)
    client.post(path(order),json={'is_inoperable':True},headers=ADMIN)
    with store.transaction() as db:
        receipt=json.loads(db.execute("SELECT detail FROM events WHERE kind='shipping_estimate_received'").fetchone()[0])
        receipt.update(change)
        db.execute("UPDATE events SET detail=? WHERE kind='shipping_estimate_received'",(json.dumps(receipt),))
    result=client.get('/api/orders/'+order['id'],headers={'Authorization':'Bearer '+order['access_token']})
    assert result.status_code==200 and result.json()['shipping_estimate'] is None
    assert len(shipping.calls)==1


def test_changed_route_does_not_reuse_customer_shipping_estimate(tmp_path):
    client,settings,shipping,_,order=setup(tmp_path)
    client.post(path(order),json={'is_inoperable':False},headers=ADMIN)
    catalog=json.loads(settings.inventory_path.read_text());catalog['items'][0]['city']='Houston'
    settings.inventory_path.write_text(json.dumps(catalog))
    restarted=TestClient(create_app(settings,shipping=shipping))
    result=restarted.get('/api/orders/'+order['id'],headers={'Authorization':'Bearer '+order['access_token']})
    assert result.status_code==200 and result.json()['shipping_estimate'] is None
    assert len(shipping.calls)==1


def test_corrupt_shipping_receipt_does_not_break_request_status(tmp_path):
    client,_,shipping,store,order=setup(tmp_path)
    client.post(path(order),json={'is_inoperable':False},headers=ADMIN)
    with store.transaction() as db:db.execute("UPDATE events SET detail='broken-json' WHERE kind='shipping_estimate_received'")
    result=client.get('/api/orders/'+order['id'],headers={'Authorization':'Bearer '+order['access_token']})
    assert result.status_code==200 and result.json()['state']=='requested' and result.json()['shipping_estimate'] is None
    assert len(shipping.calls)==1
