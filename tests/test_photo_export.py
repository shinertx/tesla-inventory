import copy
import pytest
from tools.export_photo_recovery import project_photos,nonphoto_catalog

VIN='5YJ3E1EA8SF921313'
OTHER='7SAYGDED1RF039277'
PHOTO='https://images.example.test/real-vin-photo.jpg'
MORE='https://images.example.test/second-real-photo.jpg'
STOCK='https://static.tcimg.net/vehicles/primary/render/2023-Tesla-Model_3.png'

def catalog():
    return {'meta':{'built_at':'2026-10-31T10:00:00Z','count':2,'reservable_count':0,
                    'media_version':'before','partner_onboarding_status':'pending'},
            'items':[{'vin':VIN,'photo':'','photo_count':0,'display_price':27123,
                      'reference_price':28000,'savings_amount':877,'availability':'unverified',
                      'expires_at':'2026-11-07T10:00:00Z','reservable':False},
                     {'vin':OTHER,'photo':PHOTO,'photo_count':2,'display_price':45678,
                      'reference_sample':8,'source_observed_at':None}]}

def test_photo_export_preserves_prices_flags_clock_order_and_full_gallery():
    original=catalog();unchanged=copy.deepcopy(original)
    key=format(int(OTHER[-3:])%128,'02x')
    shards={key:{OTHER:[{'url':PHOTO,'title':'Exterior','category':'photos'},
                       {'url':MORE,'title':'Interior','category':'photos'}]}}
    updated,published,changed=project_photos(original,shards,{VIN:[PHOTO]})
    assert original==unchanged
    assert nonphoto_catalog(updated)==nonphoto_catalog(original)
    assert updated['items'][0]['photo']==PHOTO
    assert updated['items'][0]['photo_count']==1
    assert published[key][OTHER]==shards[key][OTHER]
    assert changed==[VIN]
    again,again_shards,again_changed=project_photos(updated,published,{VIN:[PHOTO]})
    assert again==updated and again_shards==published and again_changed==[]

def test_photo_export_removes_stock_without_inventing_or_repricing():
    original=catalog();original['items']=original['items'][:1]
    original['items'][0].update(photo=STOCK,photo_count=1)
    updated,shards,_=project_photos(original,{}, {})
    assert updated['items'][0]['photo']=='' and updated['items'][0]['photo_count']==0
    assert nonphoto_catalog(updated)==nonphoto_catalog(original)
    assert not shards

def test_photo_export_refuses_missing_existing_gallery_and_foreign_delta():
    with pytest.raises(ValueError,match='gallery is missing'):
        project_photos(catalog(),{}, {})
    with pytest.raises(ValueError,match='unpublished VIN'):
        project_photos(catalog(),{}, {'7G2CEHED5RA040513':[PHOTO]})
