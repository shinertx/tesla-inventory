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


def test_all_spin_sets_and_fragmented_flight_records_are_collected():
    car={'vin':VIN,'vexVdpImageData':{'spins':[
        {'images':[{'imageUrl':'https://example.test/front.jpg'}]},
        {'location':'interior','images':[{'imageUrl':'https://example.test/cabin.jpg'}]}]}}
    flight='1:'+json.dumps(car)+'\n';cut=len(flight)//2
    html=''.join('<script>self.__next_f.push('+json.dumps([1,part])+')</script>' for part in [flight[:cut],flight[cut:]])
    photos=extract_gallery(html,VIN)
    assert [p['url'] for p in photos]==['https://example.test/front.jpg','https://example.test/cabin.jpg']
    assert photos[1]['category']=='interior'


def test_published_gallery_supersedes_stale_single_photo_cache(tmp_path):
    from app.store import Store
    from app.media import VehicleMedia
    service=VehicleMedia(Store(tmp_path/'db.sqlite'),tmp_path/'absent.json')
    assert service.gallery(VIN,'https://example.test/old.jpg')['count']==1
    photos=[{'url':'https://example.test/front.jpg'},{'url':'https://example.test/back.jpg'}]
    result=service.gallery(VIN,published=photos)
    assert result['count']==2 and result['status']=='ready'


def test_photo_feed_normalization_excludes_private_fields_and_duplicates():
    from tools.media import normalize_photos
    photos=normalize_photos([{'url':'https://example.test/front.jpg','dealer_name':'Private Dealer','asking_price':25000},
        'https://example.test/front.jpg','https://example.test/no-image.jpg',{'url':'https://example.test/back.jpg'}])
    assert len(photos)==2 and all(set(p)=={'url','title','category'} for p in photos)


def test_single_imported_photo_does_not_prevent_full_gallery_lookup(tmp_path,monkeypatch):
    from app.store import Store
    from app.media import VehicleMedia
    from app import media as module
    source=tmp_path/'source.json';source.write_text(json.dumps({'items':[{'vin':VIN,'source_url':'https://www.carvana.com/vehicle/12345','photos':[{'url':'https://example.test/front.jpg'}]}]}))
    html='<script type="application/ld+json">'+json.dumps({'vin':VIN,'image':['https://example.test/front.jpg','https://example.test/rear.jpg']})+'</script>'
    class Response:status_code=200;text=html
    monkeypatch.setattr(module.requests,'get',lambda *a,**kw:Response())
    assert VehicleMedia(Store(tmp_path/'db.sqlite'),source).gallery(VIN)['count']==2


def test_backfill_stops_blocked_hosts_and_preserves_supplier_feed(tmp_path,monkeypatch):
    from tools import enrich_photos
    source=tmp_path/'source.json';source.write_text(json.dumps({'items':[{'vin':v,'source_url':'https://www.carvana.com/vehicle/12345'} for v in [VIN,'5YJ3E1EA8KF413066','7SAYGDED1RF039277']]}))
    feed=tmp_path/'feed.json';feed.write_text(json.dumps({'7SAYGDED1RF039277':['https://example.test/front.jpg','https://example.test/rear.jpg']}))
    calls=[]
    class Blocked:status_code=403
    monkeypatch.setattr(enrich_photos.requests,'get',lambda *a,**kw:calls.append(a) or Blocked())
    out=tmp_path/'photos.json';result=enrich_photos.collect(source,out,tmp_path/'report.json',feed,pause=0)
    assert len(calls)==1 and result['blocked_hosts']==['www.carvana.com']
    assert len(json.loads(out.read_text())['7SAYGDED1RF039277'])==2


def test_raw_json_api_gallery_binds_to_requested_vin():
    payload=json.dumps({'records':[
        {'vin':VIN,'photo_urls':[
            'https://static.cargurus.com/images/forsale/car-pic-1-1024x768.jpeg?io=true&width=320&format=jpeg',
            'https://static.cargurus.com/images/forsale/car-pic-1-1024x768.jpeg',
            'https://static.cargurus.com/images/forsale/car-pic-2-1024x768.jpeg?io=true&width=320&format=jpeg',
            '/assets/listings/wagon_default.jpg',
        ]},
        {'vin':'WRONGVIN000000000','photo_urls':['https://example.test/wrong.jpg']},
    ]})
    photos=extract_gallery(payload,VIN)
    assert [p['url'] for p in photos]==[
        'https://static.cargurus.com/images/forsale/car-pic-1-1024x768.jpeg',
        'https://static.cargurus.com/images/forsale/car-pic-2-1024x768.jpeg',
    ]


def test_generic_truecar_render_is_not_vin_photography():
    from tools.media import photo_url, normalize_photos
    stock = 'https://static.tcimg.net/vehicles/primary/example/2023-Tesla-Model_3-black-full_color-driver_side_front_quarter.png'
    actual = 'https://listings-prod.tcimg.net/listings/16761/34/05/5YJ3E1EA0KF410534/001_2026080706.jpg'
    assert photo_url(stock) == ''
    assert photo_url(actual) == actual
    assert [x['url'] for x in normalize_photos([stock, actual])] == [actual]


def test_observed_unavailable_photos_are_not_published():
    from tools.media import photo_url, EXCLUDED_PHOTO_URLS
    assert EXCLUDED_PHOTO_URLS
    for url in EXCLUDED_PHOTO_URLS:
        assert photo_url(url) == ''
