from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,sqlite3
from tools.inventory import valid_vin,ingest,export
from tools.build import build
from tools.collect import parse_source,SourceError
import pytest

VIN='5YJSA1S22FF087484'
def candidate(**kw):
    return dict(vin=VIN,model='Model S',year=2015,dealer_trim='70D',asking_price=20000,mileage=60000,dealer_name='Test source',city='Austin',state='TX',photo_url='',source_url='https://example.test/car/'+VIN,risk_flag=False,imported_at=datetime.now(timezone.utc).isoformat(),observed_at=None,**kw)
def write_source(tmp,items):
    p=tmp/'source.json';p.write_text(json.dumps({'items':items}));return p

def test_vin_checksum_does_not_repair_identity():
    assert valid_vin(VIN)
    assert not valid_vin(VIN[:-1]+'9')
    assert not valid_vin(VIN.replace('0','O'))

def test_expired_and_risky_candidates_are_not_published(tmp_path):
    now=datetime.now(timezone.utc)
    for row,reason in [({**candidate(),'risk_flag':True},'title_or_condition_risk'),({**candidate(),'imported_at':(now-timedelta(days=8)).isoformat()},'expired_snapshot')]:
        result=build(write_source(tmp_path,[row]),tmp_path,now)
        assert result['items']==[];assert result['meta']['excluded'][reason]==1

def test_hardware_inspection_and_title_are_not_invented(tmp_path):
    result=build(write_source(tmp_path,[candidate()]),tmp_path)
    x=result['items'][0]
    assert x['hardware'] is None
    assert x['inspection_status']=='not_verified'
    assert x['title_status']=='unverified'
    assert x['availability']=='unverified'
    assert x['display_price']==20000
    assert not ({'asking_price','service_fee','dealer','source_url','source'} & x.keys())
    sitemap=(tmp_path/'sitemap.xml').read_text()
    assert '?vin=' not in sitemap
    category=(tmp_path/'models/model-s.html').read_text()
    assert '$20,000' in category
    assert '97.4%' not in category

def test_source_refresh_updates_price_and_preserves_original_observations(tmp_path):
    db=tmp_path/'inv.db';now=datetime.now(timezone.utc).isoformat()
    assert ingest(db,[candidate()],'test',now)==1
    assert ingest(db,[{**candidate(),'asking_price':21000}],'test',now)==1
    export(db,tmp_path/'snapshot.json')
    assert json.loads((tmp_path/'snapshot.json').read_text())['items'][0]['asking_price']==21000
    c=sqlite3.connect(db);assert c.execute('SELECT count(*) FROM observations').fetchone()[0]==2

def test_invalid_vin_is_quarantined_without_silent_correction(tmp_path):
    db=tmp_path/'inv.db';now=datetime.now(timezone.utc).isoformat()
    assert ingest(db,[{**candidate(),'vin':VIN[:-1]+'9'}],'test',now)==0
    c=sqlite3.connect(db);assert c.execute('SELECT count(*) FROM quarantine').fetchone()[0]==1

def test_snapshot_cannot_be_reimported_as_live_observation(tmp_path):
    with pytest.raises(ValueError):ingest(tmp_path/'inv.db',[candidate()],'test',(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())

def test_missing_source_shape_is_a_visible_failure():
    class Response:
        text='<html>captcha</html>'
        def json(self):return {'not':'listings'}
    for source in ('autolist','cargurus','truecar','carvana'):
        with pytest.raises(SourceError):parse_source(source,Response())

def test_cargurus_query_supplies_model_when_response_omits_it():
    class Response:
        def json(self):return [{'vin':VIN,'price':20000,'mileage':60000,'carYear':2015,'id':123,'serviceProviderName':'Dealer'}]
    rows=parse_source('cargurus',Response(),'Model S',2015)
    assert rows[0]['model']=='Model S'
    assert '123' in rows[0]['source_url']

def test_source_jsonld_mileage_is_normalized():
    class Response:
        text='<script type="application/ld+json">'+json.dumps({'@type':'Vehicle','vehicleIdentificationNumber':VIN,'model':'Model S','modelDate':'2015','mileageFromOdometer':{'value':60000},'offers':{'price':'20000','url':'https://example.test/car/'+VIN}})+'</script>'
    row=parse_source('carvana',Response())[0]
    assert row['mileage']==60000;assert row['asking_price']==20000

def test_partial_refresh_retains_other_source_candidates(tmp_path):
    db=tmp_path/'inv.db';out=tmp_path/'snapshot.json';now=datetime.now(timezone.utc).isoformat()
    legacy={**candidate(),'source':'legacy_snapshot'}
    out.write_text(json.dumps({'items':[legacy]}))
    other={**candidate(),'vin':'7G2CEHED5RA040513','model':'Cybertruck','year':2024}
    ingest(db,[other],'test',now);export(db,out)
    assert len(json.loads(out.read_text())['items'])==2

def test_public_candidate_has_expiration(tmp_path):
    result=build(write_source(tmp_path,[candidate()]),tmp_path)
    assert datetime.fromisoformat(result['items'][0]['expires_at'])>datetime.now(timezone.utc)

def test_customer_export_never_contains_private_supplier_commercial_data(tmp_path):
    build(write_source(tmp_path,[candidate()]),tmp_path)
    payload=json.loads((tmp_path/'inventory.json').read_text())
    text=json.dumps(payload)
    assert 'Test source' not in text and 'example.test/car' not in text
    assert not {'dealer','asking_price','service_fee','source_url'}&payload['items'][0].keys()
    from app.catalog import public_catalog
    assert public_catalog({'items':[{'vin':VIN,'dealer':'PRIVATE','asking_price':1,'source_url':'PRIVATE'}]})['items']==[{'vin':VIN}]

def test_supplier_description_cannot_leak_raw_price_through_trim(tmp_path):
    row={**candidate(),'dealer_trim':'Used 2015 Tesla Model S 70D with 60000 miles - $20,000'}
    result=build(write_source(tmp_path,[row]),tmp_path)
    assert result['items'][0]['trim']=='70D'
    assert '$20,000' not in (tmp_path/'inventory.json').read_text()
