import json
from tools.media import extract_gallery,photo_url
from tools.collect import normalized

VIN='5YJSA1S22FF087484'

def test_placeholder_paths_are_not_vehicle_photography():
    assert not photo_url('/assets/listings/sedan_default.jpg')
    assert not photo_url('https://example.test/stockimages/blue-tesla.jpg')
    assert photo_url('https://example.test/actual-car.jpg')

def test_flight_photos_are_bound_to_the_exact_vin_and_keep_condition_images():
    car={'vin':VIN,'vexVdpImageData':{'heroes':{'hero':'https://example.test/exterior.jpg'},'spins':[{'images':[{'imageUrl':'https://example.test/angle.jpg'}]}],'features':[{'imageUrl':'https://example.test/dash.jpg','title':'Dashboard','location':'interior'}],'imperfections':[{'imageUrl':'https://example.test/scratch.jpg','title':'Scratch','zoneDescription':'Rear door'}]}}
    other={'vin':'WRONGVIN','vexVdpImageData':{'heroes':{'hero':'https://example.test/wrong-car.jpg'}}}
    flight='1:'+json.dumps([car,other])+'\n'
    html='<script>self.__next_f.push('+json.dumps([1,flight])+')</script>'
    photos=extract_gallery(html,VIN)
    assert len(photos)==4
    assert photos[-1]['category']=='condition'
    assert not any('wrong-car' in x['url'] for x in photos)

def test_jsonld_gallery_arrays_are_preserved_by_collection():
    row=normalized(VIN,'Model S',2015,'70D',20000,60000,'Dealer','Austin','TX',
        ['https://example.test/front.jpg','https://example.test/rear.jpg'],'https://example.test/car')
    assert len(row['photos'])==2 and row['photo_url'].endswith('front.jpg')
    html='<script type="application/ld+json">'+json.dumps({'@type':'Vehicle','vehicleIdentificationNumber':VIN,'image':['https://example.test/front.jpg','https://example.test/rear.jpg']})+'</script>'
    assert len(extract_gallery(html,VIN))==2

def test_media_service_fetches_once_and_caches_vin_bound_gallery(tmp_path,monkeypatch):
    from app.store import Store
    from app.media import VehicleMedia
    from app import media as module
    source=tmp_path/'source.json';source.write_text(json.dumps({'items':[{'vin':VIN,'source_url':'https://www.carvana.com/vehicle/12345'}]}))
    html='<script type="application/ld+json">'+json.dumps({'@type':'Vehicle','vehicleIdentificationNumber':VIN,'image':['https://example.test/one.jpg','https://example.test/two.jpg']})+'</script>'
    calls=[]
    class Response:status_code=200;text=html
    monkeypatch.setattr(module.requests,'get',lambda *args,**kw:calls.append(args) or Response())
    service=VehicleMedia(Store(tmp_path/'db.sqlite'),source)
    for _ in range(2):assert service.gallery(VIN)['count']==2
    assert len(calls)==1


def test_blocked_detail_source_uses_known_primary_without_retrying(tmp_path,monkeypatch):
    from app.store import Store
    from app.media import VehicleMedia
    from app import media as module
    source=tmp_path/'source.json';source.write_text(json.dumps({'items':[{'vin':VIN,'source_url':'https://www.cargurus.com/Cars/details'}]}))
    def forbidden(*args,**kwargs):raise AssertionError('Blocked source should not be retried')
    monkeypatch.setattr(module.requests,'get',forbidden)
    assert VehicleMedia(Store(tmp_path/'db.sqlite'),source).gallery(VIN,'https://example.test/known.jpg')['count']==1
