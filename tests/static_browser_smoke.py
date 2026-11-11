"""Exercise the actual GitHub Pages subpath, without an API or mocked vehicle images."""
import functools,json,sys,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.catalog import stock_id_for
class PagesHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/tesla-inventory/'):self.path=self.path[len('/tesla-inventory'):]
        return super().do_GET()
    def log_message(self,*args):pass

def open_details(page, selector):
    details=page.locator(selector)
    details.wait_for(state='attached')
    if not details.evaluate('(el)=>el.open'):
        details.locator('summary').click()


def main(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(PagesHandler,directory=str(ROOT)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    result={'api_present':False,'mock_images':False,'named_galleries':{},'javascript_errors':[]}
    try:
        with sync_playwright() as p:
            b=p.chromium.launch();page=b.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:result['javascript_errors'].append(str(e)))
            v_page=next(iter(sorted((ROOT/'v').glob('*.html'))),None)
            if v_page:
                page.goto(base+'v/'+v_page.name)
                page.locator('#vehicle-dialog[open]').wait_for()
                assert v_page.stem in page.locator('#vehicle-panel').inner_text()
                assert page.url.endswith('/v/'+v_page.name)
                result['static_vdp_bootstrap']=True
            if v_page:
                page.goto(base+'v/'+v_page.name+'?utm_source=google&utm_campaign=seo-check')
                page.locator('#vehicle-dialog[open]').wait_for()
                page.locator('[data-close=vehicle-dialog]').click()
                other=page.locator(f'.card-main:not([data-open="{v_page.stem}"])').first
                next_url=other.get_attribute('href')
                other.click();page.wait_for_url(next_url)
                page.locator('#vehicle-dialog[open]').wait_for()
                canonical=page.locator('link[rel=canonical]').get_attribute('href')
                assert canonical.endswith('/v/'+urlsplit(page.url).path.split('/')[-1])
                assert page.locator('body').get_attribute('data-initial-stock-id')==urlsplit(page.url).path.split('/')[-1][:-5]
                assert 'utm_source=google' in page.url and 'utm_campaign=seo-check' in page.url
                assert '?' not in canonical
                assert '?' not in page.locator('#dynamic-vehicle-schema').inner_text()
                result['cross_vin_canonical_document_navigation']=True
                result['campaign_attribution_preserved']=True
            known_vp={stock_id_for(v):v for v in json.loads((ROOT/'data/vehicle_photos.json').read_text())}
            media_counts={sid:len(arr) for mf in (ROOT/'media').glob('*.json') for sid,arr in json.loads(mf.read_text()).items()}
            inv_items=json.loads((ROOT/'inventory.json').read_text())['items']
            other_gal=[(known_vp[x['stock_id']],x['stock_id'],media_counts[x['stock_id']]) for x in inv_items if x.get('curated') and x.get('model')!='Model 3' and x['stock_id'] in known_vp and media_counts.get(x['stock_id'],0)>=30]
            m3_gal=[(known_vp[x['stock_id']],x['stock_id'],media_counts[x['stock_id']]) for x in inv_items if x.get('curated') and x.get('model')=='Model 3' and x['stock_id'] in known_vp and media_counts.get(x['stock_id'],0)>=30]
            vin1,sid1,cnt1=other_gal[0]
            vin2,sid2,cnt2=other_gal[1]
            vin3,sid3,cnt3=m3_gal[0]
            nojs=b.new_context(java_script_enabled=False)
            crawl=nojs.new_page();crawl.goto(base+'browse/index.html',wait_until='domcontentloaded')
            assert crawl.locator('a[href^="../v/"]').count()==100
            crawl.goto(base+'v/'+sid2+'.html',wait_until='domcontentloaded')
            assert crawl.locator('h1').count()==1 and sid2 in crawl.locator('h1').inner_text()
            assert 'Vehicle price' in crawl.locator('.category-intro').inner_text()
            result['discovery_works_without_javascript']=True
            nojs.close()
            for vin,count in [(vin1,cnt1),(vin2,cnt2),(vin3,cnt3)]:
                page.goto(base+'?vin='+vin);page.wait_for_function('(n)=>document.querySelectorAll(".gallery-thumb").length===n',arg=count)
                page.wait_for_function('()=>document.querySelector("#gallery-stage img")?.naturalWidth>0')
                assert page.locator('#vehicle-request').is_enabled()
                assert page.locator('#vehicle-request').inner_text()=='Review price'
                page.locator('.gallery-thumb').last.click();page.wait_for_function('()=>document.querySelector("#gallery-stage img")?.naturalWidth>0')
                result['named_galleries'][vin]={'count':count,'first_and_last_rendered':True}
            page.locator('#vehicle-request').click();page.locator('#deal-zip').fill('78201');page.locator('#deal-continue').click()
            page.get_by_text('Price saved on this device. No request or reservation has been placed.').wait_for()
            assert page.evaluate('JSON.parse(localStorage.getItem("marketplace_deal")).vin')==sid3
            page.goto(base);page.wait_for_selector('.card');page.locator('#order-button').click();page.locator('#deal-dialog[open]').wait_for()
            assert page.locator('#deal-zip').input_value()=='78201'
            assert 'Model 3' in page.locator('#deal-summary').inner_text()
            result['static_deal_draft_no_order_or_payment']=True
            result['saved_deal_resumes_after_reload']=True
            page.evaluate('localStorage.clear()')
            page.goto(base);page.wait_for_selector('.card');page.locator('.save').first.click();assert page.locator('#saved-count').inner_text()=='1'
            page.locator('[data-discover=under30]').click();assert page.locator('.card').count()>0;result['discovery_and_save']=True
            page.locator('#reset').click()
            assert page.locator('.discovery-chip.active').count()==1 and page.locator('.discovery-chip.active').get_attribute('data-discover')=='all'
            assert len(set(page.locator('.card h3').all_text_contents()[:5]))>=3;result['varied_recommendations']=True
            assert page.locator('.card img').evaluate_all('(xs)=>xs.slice(0,6).every(x=>x.loading==="eager")');result['eager_first_six']=True
            page.wait_for_function('()=>[...document.querySelectorAll(".card img")].slice(0,3).every(x=>x.complete&&x.naturalWidth>0)')
            page.screenshot(path=str(out/'showroom-desktop.png'))
            page.select_option('#drivetrain','AWD');assert page.locator('.card').count()>0
            assert all('AWD' in x for x in page.locator('.card-specs').all_text_contents());result['drivetrain_filter']=True
            page.locator('#reset').click();page.select_option('#trim-family','Performance');assert page.locator('.card').count()>0
            assert all('performance' in x.lower() for x in page.locator('.card .trim').all_text_contents());result['trim_filter']=True
            page.locator('#reset').click();page.select_option('#factory','Austin');page.locator('.card-main').first.click()
            assert 'Built in Austin' in page.locator('.card-specs').first.inner_text();
            assert 'Build factory' in page.locator('#vehicle-panel').inner_text() and 'Vehicle location' in page.locator('#vehicle-panel').inner_text();assert not page.locator('.verification-details').get_attribute('open')
            page.locator('.verification-details summary').click();assert 'Multi-point inspected' in page.locator('.verification-details').inner_text()
            page.locator('[data-close=vehicle-dialog]').click();page.locator('#reset').click();result['factory_filter_and_verification_disclosure']=True
            assert page.locator('#hardware option[value=HW4]').evaluate('(x)=>x.disabled');result['hardware_requires_evidence']=True
            for postal,state in [('94103','CA'),('78201','TX')]:
                page.locator('#zip-button').click();page.locator('#zip-input').fill(postal);page.locator('#zip-form button').click();page.locator('#zip-dialog').wait_for(state='hidden')
                assert page.locator('#sort').input_value()=='distance';assert state in page.locator('.card-footer').first.inner_text()
                assert 'mi away' in page.locator('.card-footer').first.inner_text()
            result['zip_changes_nearby_results']=True
            page.locator('#zip-button').click();page.locator('#zip-input').fill('00000');page.locator('#zip-form button').click();page.get_by_text('ZIP not found in our location data. Try a nearby ZIP.').wait_for()
            assert page.locator('#zip-label').inner_text()=='78201';page.locator('[data-close=zip-dialog]').click();result['unknown_zip_does_not_guess']=True
            page.goto(base+'models/model-y.html');page.wait_for_selector('.card');assert page.locator('#model').input_value()=='Model Y';result['category_subpath']=True
            mobile=b.new_page(viewport={'width':390,'height':844},is_mobile=True);mobile.goto(base+'?vin='+vin1);mobile.wait_for_function('(n)=>document.querySelectorAll(".gallery-thumb").length===n',arg=cnt1);mobile.wait_for_function('()=>document.querySelector("#gallery-stage img")?.naturalWidth>0');result['mobile_gallery']=True
            mobile.screenshot(path=str(out/'static-customer-gallery.png'))
            mobile.goto(base);mobile.wait_for_selector('.card');mobile.locator('#mobile-filters').click();assert mobile.locator('#drivetrain').is_visible();assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth');result['mobile_new_filters_and_bounds']=True
            assert not result['javascript_errors'];b.close()
    finally:server.shutdown();server.server_close()
    (out/'static-browser-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else ROOT/'.data/static-browser-results')
