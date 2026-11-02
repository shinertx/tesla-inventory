"""The public release artifact cannot expose source, private state, or VIN reports."""
import json
from pathlib import Path

import pytest

from tools.public_site import build_public_site


def write(root,name,content='public'):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content);return path


def site(root):
    for name in ['index.html','inventory.json','sitemap.xml','robots.txt','web/app.js','web/pricing.js','web/styles.css']:
        write(root,name)
    write(root,'v/VV-6C2CD3B68849.html');write(root,'browse/index.html')
    write(root,'media/49.json',json.dumps({'VV-6C2CD3B68849':[]}))
    write(root,'data/us_zip_centers.json','{}');write(root,'data/us_city_centers.json','{}')
    write(root,'google2520469431f94ebd.html','google-site-verification: google2520469431f94ebd.html')
    write(root,'.nojekyll','');write(root,'CNAME','voltsandvins.com')


def test_export_only_includes_customer_pages_assets_and_geography(tmp_path):
    source=tmp_path/'source';site(source)
    for name in ['.data/transaction_inventory.json','data/vehicle_photos.json','data/exclusions.json',
                 'docs/photo-recovery-manifest.json','app/config.py','tools/operator.py','tests/fixture.json',
                 '.env','README.md','debug.html','web/index.html','web/report.json']:
        write(source,name,'PRIVATE 7SAYGDED1RF039277')
    output=tmp_path/'public';result=build_public_site(source,output)
    actual={p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
    assert set(result['files'])==actual
    assert 'web/pricing.js' in actual and 'google2520469431f94ebd.html' in actual
    assert actual&{'data/us_zip_centers.json','data/us_city_centers.json'}=={'data/us_zip_centers.json','data/us_city_centers.json'}
    assert not any(name.startswith(('.data/','app/','tools/','docs/','tests/')) for name in actual)
    assert not (output/'data/vehicle_photos.json').exists()
    assert all('7SAYGDED1RF039277' not in p.read_text() for p in output.rglob('*') if p.is_file())


@pytest.mark.parametrize('name',['inventory.json','v/VV-6C2CD3B68849.html','media/49.json','web/app.js'])
def test_export_refuses_full_vins_in_public_assets(name,tmp_path):
    source=tmp_path/'source';site(source);write(source,name,'7SAYGDED1RF039277')
    output=tmp_path/'public'
    with pytest.raises(ValueError,match='full vehicle identity'):build_public_site(source,output)
    assert not output.exists()


def test_export_refuses_missing_assets_nonempty_destination_and_external_symlinks(tmp_path):
    source=tmp_path/'source';site(source);output=tmp_path/'public'
    (source/'web/pricing.js').unlink()
    with pytest.raises(ValueError,match='missing'):build_public_site(source,output)
    write(source,'web/pricing.js')
    write(output,'old-private-file','PRIVATE')
    with pytest.raises(ValueError,match='must be empty'):build_public_site(source,output)
    (output/'old-private-file').unlink()
    outside=write(tmp_path,'outside.js','PRIVATE')
    (source/'web/app.js').unlink();(source/'web/app.js').symlink_to(outside)
    with pytest.raises(ValueError,match='link outside'):build_public_site(source,output)
    with pytest.raises(ValueError,match='separate'):build_public_site(source,source)


def test_google_named_files_cannot_bypass_the_deployment_allowlist(tmp_path):
    source=tmp_path/'source';site(source);write(source,'googleprivate.html','PRIVATE')
    with pytest.raises(ValueError,match='unexpected content'):
        build_public_site(source,tmp_path/'public')
