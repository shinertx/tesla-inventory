"""Public stock IDs preserve private transaction identities and known title risks."""
import copy
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.catalog import (catalog_exclusions, masked_vin_for, media_shard, public_catalog, public_photo_url,
                         stock_id_for, title_risk_reasons)
from tools.build import build, migrate_public_catalog
from tools.collect import parse_source
from tools.inventory import export, ingest


VIN='5YJSA1S22FF087484'
STOCK='VV-39FE614315D1'


def row(**extra):
    return {'vin':VIN,'model':'Model S','year':2015,'trim':'70D','mileage':60000,
            'display_price':27123,'title_status':'unverified','reservable':False,
            'stock_number':'TSL-087484','photo':'https://photos.example.test/front.jpg',
            'photo_count':2,**extra}


def test_stock_identity_is_stable_distinct_and_not_a_vin_suffix():
    assert stock_id_for(VIN)==STOCK
    assert stock_id_for('7SAYGDED1RF039277')=='VV-6C2CD3B68849'
    assert media_shard(STOCK)=='51'
    assert masked_vin_for(VIN)=='5YJSA1S2'+'•'*9
    for value in ['',VIN[:-1],STOCK,'https://example.test/'+VIN]:
        with pytest.raises(ValueError):stock_id_for(value)
    with pytest.raises(ValueError):media_shard(VIN)


def test_public_projection_is_idempotent_and_never_invents_clean_history():
    data={'meta':{'count':1},'items':[row(dealer_name='PRIVATE',source_url='PRIVATE')]}
    before=copy.deepcopy(data);public=public_catalog(data)
    assert data==before and public_catalog(public)==public
    item=public['items'][0]
    assert item['stock_id']==item['stock_number']==STOCK
    assert 'vin' not in item and VIN not in json.dumps(public)
    assert item['title_status']=='unverified' and 'dealer_name' not in item
    assert public_catalog({'items':[row(title_status='clean_verified')]})['items'][0]['title_status']=='unverified'


@pytest.mark.parametrize('evidence,brand',[
    ({'title_status':'Salvage'},'salvage'),({'titleType':'REBUILT'},'rebuilt'),
    ({'title_brands':['Clean','Lemon / Manufacturer Buyback']},'lemon'),
    ({'history':{'floodDamage':True}},'flood'),({'vehicleHistory':{'isSalvage':True}},'salvage'),
    ({'titleBrand':{'name':'Reconstructed'}},'rebuilt'),({'water_damage':1},'flood'),
    ({'frameDamage':True},'structural_damage'),({'risk_flag':True},'reported_condition_risk'),
    ({'title_status':'FloodDamage'},'flood'),({'title_status':'ManufacturerBuyback'},'lemon'),
    ({'title_status':'LemonLawBuyback'},'lemon'),({'title_status':'SalvageRebuilt'},'salvage'),
    ({'title_status':'salvagerebuilt'},'rebuilt'),
])
def test_known_title_and_condition_brands_are_filtered_before_publication(evidence,brand,tmp_path):
    assert brand in title_risk_reasons(evidence)
    assert public_catalog({'items':[row(**evidence)]})['items']==[]
    now=datetime.now(timezone.utc)
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'items':[{**row(),**evidence,'dealer_trim':'70D','asking_price':27123,
        'source_url':'https://example.test/vehicle/'+VIN,'imported_at':now.isoformat()}]}))
    result=build(source,tmp_path,now)
    assert result['items']==[] and result['meta']['excluded']['title_or_condition_risk']==1
    assert json.loads((tmp_path/'inventory.json').read_text())['items']==[]


@pytest.mark.parametrize('evidence',[
    {},{'title_status':'unknown'},{'title_status':'clean_verified'},
    {'isSalvage':False,'isFlood':'false','lemon':0,'risk_flag':'false'},
    {'title_status':'Clean title; no salvage; not rebuilt'},
    {'title':'Lemon Yellow Tesla Model 3','description':'Flood light included'},
])
def test_unknowns_and_explicit_negative_flags_are_not_branded_as_risks(evidence):
    assert title_risk_reasons(evidence)==[]


def test_collector_preserves_title_risk_from_source_metadata():
    class Response:
        def json(self):return [{'vin':VIN,'price':27000,'mileage':60000,'carYear':2015,'id':123,
                              'titleStatus':'Flood','serviceProviderName':'Source'}]
    captured=parse_source('cargurus',Response(),'Model S',2015)[0]
    assert captured['risk_flag'] is True and captured['title_risk_reasons']==['flood']


def test_risky_refresh_cannot_resurrect_older_source_rows(tmp_path):
    database=tmp_path/'sources.db';snapshot=tmp_path/'source.json'
    now=datetime.now(timezone.utc).isoformat()
    assert ingest(database,[row()],'old',now)==1
    export(database,snapshot)
    assert ingest(database,[row(title_status='Rebuilt')],'new',now)==0
    # An unknown record from another source cannot silently clear documented title risk.
    assert ingest(database,[row()],'third',now)==1
    export(database,snapshot)
    assert json.loads(snapshot.read_text())['items']==[]
    with sqlite3.connect(database) as db:
        assert 'rebuilt' in db.execute('SELECT reason FROM quarantine').fetchone()[0]


def test_migration_keeps_prices_full_gallery_and_private_vin_without_source_calls(tmp_path):
    photos=[{'url':'https://photos.example.test/front.jpg','title':'Front','category':'exterior'},
            {'url':'https://photos.example.test/rear.jpg','title':'Rear','category':'exterior'}]
    raw={'meta':{'count':1,'built_at':'2026-11-01T00:00:00Z','media_version':'old'},'items':[row()]}
    before=copy.deepcopy(raw)
    old={'01':{VIN:photos}}
    first=migrate_public_catalog(raw,tmp_path,shards=old)
    assert raw==before and first['public']['items'][0]['display_price']==27123
    assert first['shards']=={'51':{STOCK:photos}}
    private=json.loads((tmp_path/'.data/transaction_inventory.json').read_text())
    assert private['items'][0]['vin']==VIN and private['items'][0]['photos']==photos
    assert (tmp_path/'.data/transaction_inventory.json').stat().st_mode & 0o777==0o600
    public=json.loads((tmp_path/'inventory.json').read_text())
    assert VIN not in json.dumps(public) and public['items'][0]['photo_count']==2
    assert VIN not in (tmp_path/'media/51.json').read_text()
    second=migrate_public_catalog(public,tmp_path)
    assert second['public']==first['public'] and second['shards']==first['shards']
    assert second['private']['items'][0]['vin']==VIN


def test_missing_gallery_or_private_identity_stops_migration(tmp_path):
    with pytest.raises(ValueError,match='gallery is missing'):
        migrate_public_catalog({'items':[row()]},tmp_path,shards={})
    assert not (tmp_path/'inventory.json').exists()
    with pytest.raises(ValueError,match='Private transaction identity'):
        migrate_public_catalog(public_catalog({'items':[row()]}),tmp_path,shards={})


def test_migration_proxies_vin_urls_and_labels_but_preserves_private_images(tmp_path):
    url='https://photos.example.test/'+VIN.lower()+'/front.jpg'
    original=[{'url':url,'title':'Exterior '+VIN,'category':'photos'}]
    result=migrate_public_catalog({'items':[row(photo=url,photo_count=1)]},tmp_path,
                                  shards={'00':{VIN:original}})
    assert result['private']['items'][0]['photos']==original
    assert result['private']['items'][0]['photo']==url
    assert result['public']['items'][0]['photo']==public_photo_url(VIN,url)
    assert result['shards']['51'][STOCK][0]['url']==public_photo_url(VIN,url)
    assert VIN.lower() not in json.dumps(result['public']).lower()
    assert VIN.lower() not in json.dumps(result['shards']).lower()
    repeated=migrate_public_catalog(result['public'],tmp_path)
    assert repeated['private']['items'][0]['photo']==url
    assert repeated['private']['items'][0]['photos']==original
    assert repeated['public']==result['public'] and repeated['shards']==result['shards']


def test_private_inventory_still_uses_public_root_exclusions(tmp_path):
    data=tmp_path/'data';data.mkdir();(data/'exclusions.json').write_text(json.dumps({VIN:'Reported title risk'}))
    assert catalog_exclusions(tmp_path/'.data/transaction_inventory.json')=={VIN:'Reported title risk'}
    result=migrate_public_catalog({'items':[row(photo_count=1)]},tmp_path,shards={})
    assert result['public']['items']==[] and result['private']['items']==[]


def test_clean_verified_without_history_document_does_not_make_listing_reservable(tmp_path):
    now=datetime.now(timezone.utc)
    candidate={**row(),'dealer_trim':'70D','asking_price':27123,'source_url':'https://example.test/'+VIN,
               'imported_at':now.isoformat(),'title_status':'clean_verified',
               'agreed_dealer_net_cents':2500000,'configuration_evidence_reference':'equipment:fixture',
               'supplier_commitment_reference':'supplier:fixture','seller_hold_until':int(now.timestamp())+14400}
    source=tmp_path/'source.json';source.write_text(json.dumps({'items':[candidate]}))
    result=build(source,tmp_path,now)
    assert result['items'][0]['reservable'] is False
    assert result['items'][0]['title_status']=='unverified'


def test_dynamic_catalog_omits_inline_galleries_and_keeps_live_holds(tmp_path):
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient
    import time
    photos=[{'url':'https://photos.example.test/'+VIN+'/front.jpg','title':'Front','category':'exterior'}]
    source={'meta':{'count':1},'items':[row(photos=photos)]}
    path=tmp_path/'inventory.json';path.write_text(json.dumps(source))
    application=create_app(Settings(inventory_path=path,db_path=tmp_path/'orders.db'))
    client=TestClient(application)
    response=client.get('/inventory.json')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    item=response.json()['items'][0]
    assert item['stock_id']==STOCK and 'photos' not in item and VIN not in response.text
    assert json.loads(path.read_text())['items'][0]['photos']==photos
    # Cached browsing must still respect newly created inventory locks.
    order=client.post('/api/requests',json={'stock_id':STOCK,'name':'Fixture Buyer','email':'fixture@example.test','phone':'2105550100','state':'TX','zip':'78201','consent':True},headers={'Idempotency-Key':'fixture-private-catalog'})
    assert order.status_code==201,order.text
    with application.state.store.transaction() as c:
        c.execute('INSERT INTO holds(vin,order_id,expires_at) VALUES(?,?,?)',(VIN,order.json()['id'],int(time.time())+600))
    assert client.get('/inventory.json').json()['items']==[]
    with application.state.store.transaction() as c:c.execute('DELETE FROM holds WHERE vin=?',(VIN,))
    restored=client.get('/inventory.json').json()
    assert restored['items'][0]['stock_id']==STOCK and restored['meta']['count']==1
