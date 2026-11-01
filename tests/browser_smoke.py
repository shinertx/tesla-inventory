"""Independent bounded desktop/mobile browser verification. No external payments or messages."""
import json,socket,threading,tempfile,time,sys
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.main import create_app
from app.config import Settings

def main():
    out=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'.data/browser-results'
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        settings=Settings(db_path=Path(tmp)/'orders.db',origin=f'http://127.0.0.1:{port}',sourcing_path=Path(tmp)/'absent-supplier.json')
        server=uvicorn.Server(uvicorn.Config(create_app(settings),log_level='error'))
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        for _ in range(50):
            if server.started:break
            time.sleep(.05)
        base=settings.origin;results={};errors=[]
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1050})
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else (r.fulfill(status=200,content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#dce5eb"/></svg>') if r.request.resource_type=='image' else r.abort()))
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base);page.wait_for_selector('.card');results['initial_cards']=page.locator('.card').count();assert results['initial_cards']==36
                page.screenshot(path=str(out/'tesla-marketplace-desktop.png'),full_page=False)
                assert 'Availability needs confirmation' not in page.locator('#cards').inner_text();results['clean_customer_cards']=True
                if page.locator('[data-discover=finds]').is_visible():
                    page.locator('[data-discover=finds]').click();assert page.locator('.price-win').count()==page.locator('.card').count()
                    assert 'Save $' in page.locator('.price-win').first.inner_text()
                    page.locator('.card-benchmark summary').first.click()
                    assert 'similar Tesla asking prices' in page.locator('.card-benchmark').first.inner_text()
                page.select_option('#sort','savings');assert 'Save $' in page.locator('.price-win').first.inner_text()
                results['price_discovery']=True
                page.select_option('#sort','recommended');page.locator('[data-discover=all]').click()
                page.locator('#load-more').click();assert page.locator('.card').count()==72
                failed_vin=page.locator('.card').nth(36).get_attribute('data-vin')
                page.evaluate('document.querySelectorAll(".card img")[36].dispatchEvent(new Event("error"))')
                page.wait_for_function('(v)=>!document.querySelector(`.card[data-vin="${v}"]`)',arg=failed_vin)
                assert page.locator('.card').count()==72;results['load_more_preserves_limit_on_image_error']=True
                page.select_option('#model','Cybertruck');results['model_filter']=all('Cybertruck' in t for t in page.locator('.card h3').all_text_contents());assert results['model_filter']
                page.locator('#reset').click();assert page.locator('.card').count()==36;results['filter_change_resets_limit']=True
                page.select_option('#model','Cybertruck')
                page.locator('.save').first.click();assert page.locator('#saved-count').inner_text()=='1'
                page.locator('.card-main').first.click();page.wait_for_selector('#vehicle-dialog[open]')
                page.locator('.verification-details summary').click()
                detail=page.locator('#vehicle-content').inner_text();assert '97.4%' not in detail and '8.2mm' not in detail and '150-POINT CERTIFIED' not in detail
                results['honest_vehicle_details']='No inspection report on file' in detail;assert results['honest_vehicle_details']
                page.locator('#tab-pricing').click();assert 'Estimated shipping' in page.locator('#vehicle-panel').inner_text()
                page.locator('#tab-process').click();assert 'Request received' in page.locator('#vehicle-panel').inner_text()
                page.locator('#tab-details').click()
                page.locator('#vehicle-request').click();page.wait_for_selector('#deal-dialog[open]')
                assert 'Estimated total' in page.locator('#deal-summary').inner_text() and 'Monthly estimate' in page.locator('#deal-summary').inner_text()
                page.locator('[data-deal-mode=finance]').click();page.select_option('#deal-down','5000');page.select_option('#deal-term','72')
                assert 'not a credit offer' in page.locator('#deal-summary').inner_text()
                page.locator('[data-deal-mode=cash]').click();results['deal_estimator_and_calculator']=True
                page.locator('#deal-zip').fill('78201');page.locator('#deal-continue').click();page.wait_for_selector('#request-dialog[open]');assert page.locator('[name=state]').input_value()=='TX' and page.locator('[name=zip]').input_value()=='78201';results['zip_and_state_prefilled']=True;page.locator('[name=name]').fill('Browser Test Buyer');page.locator('[name=email]').fill('browser@example.test');page.locator('[name=consent]').check();page.locator('#submit-request').click()
                page.wait_for_selector('#order-dialog[open]');assert 'Request received' in page.locator('#order-content').inner_text();results['durable_request']=True
                access=page.evaluate('JSON.parse(sessionStorage.getItem("marketplace_order"))')
                page.reload();page.wait_for_selector('.card');page.locator('[data-close=vehicle-dialog]').click();page.locator('#order-button').click();page.wait_for_selector('#order-dialog[open]');assert 'Request received' in page.locator('#order-content').inner_text();results['status_survives_reload']=True
                order_path=base+'/api/orders/'+access['id']
                page.route(order_path,lambda r:r.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'Temporary outage'})))
                page.locator('[data-close=order-dialog]').click();page.locator('#order-button').click();page.locator('#retry-saved-order').wait_for()
                assert page.evaluate('JSON.parse(sessionStorage.getItem("marketplace_order"))')==access
                page.unroute(order_path);page.locator('#retry-saved-order').click();page.locator('#report-issue').wait_for()
                assert 'Request received' in page.locator('#order-content').inner_text();results['temporary_outage_keeps_private_access']=True
                page.locator('#switch-order').click();page.locator('#legacy-recovery summary').click();page.locator('#recover-id').fill(access['id']);page.locator('#recover-token').fill(access['token']);page.locator('#recover-form button[type=submit], #recover-form button.secondary').click()
                page.wait_for_selector('#report-issue');assert 'Request received' in page.locator('#order-content').inner_text();results['order_recovery']=True
                page.locator('#report-issue').click();page.locator('#issue-description').fill('Please verify the charging adapters included with this vehicle.');page.locator('#send-issue').click();page.locator('#issue-form').wait_for(state='hidden');results['support_case']=True
                page.locator('#cancel-order').click();page.get_by_role('heading',name='Request cancelled').wait_for();results['cancellation']=True
                page.locator('[data-close=order-dialog]').click()
                page.locator('.save').nth(1).click();page.locator('#saved-button').click();assert page.locator('.shortlist-car').count()==2
                page.locator('[data-compare-select]').nth(0).check();page.locator('[data-compare-select]').nth(1).check();page.locator('#compare-saved').click();assert page.locator('.comparison-grid article').count()==2;results['shortlist_comparison']=True
                page.locator('[data-close=compare-dialog]').click()
                # A failed config request previously suppressed photo discovery entirely.
                race=context.new_page();race.route('**/api/config',lambda r:r.abort())
                attempts=[]
                def photo_response(route):
                    attempts.append(1)
                    if len(attempts)==1:route.fulfill(status=503,content_type='application/json',body='{}')
                    else:route.fulfill(status=200,content_type='application/json',body=json.dumps({'7SAYGDED1RF039277':[{'url':f'https://example.test/angle-{i}.jpg','title':f'Angle {i}','category':'photos'} for i in range(3)]}))
                race.route('**/media/*.json*',photo_response)
                race.goto(base+'/?vin=7SAYGDED1RF039277');race.locator('#gallery-retry').wait_for(state='visible');race.locator('#gallery-retry').click()
                race.wait_for_function('()=>document.querySelectorAll(".gallery-thumb").length===3')
                assert len(attempts)==2;results['gallery_independent_of_checkout_config']=True;results['gallery_retry']=True;race.close()
                gallery=context.new_page();gallery.goto(base+'/?vin=5YJ3E1EA8KF413066');gallery.wait_for_selector('#gallery-thumbs .gallery-thumb')
                assert gallery.locator('.gallery-thumb').count()>=43
                gallery.locator('#gallery-next').click();assert gallery.locator('#gallery-count').inner_text().startswith('2 /')
                gallery.locator('#photo-expand').click();assert gallery.locator('#photo-dialog').evaluate('(x)=>x.open');results['full_vehicle_gallery']=True;gallery.close()
                for named_vin,expected_min in [('5YJ3E1EA8SF921313',30),('7SAYGDED1RF039277',45)]:
                    vp=context.new_page();vp.goto(base+f'/?vin={named_vin}');vp.wait_for_selector('#gallery-thumbs .gallery-thumb')
                    assert vp.locator('.gallery-thumb').count()>=expected_min
                    vp.close()
                results['named_vin_galleries']=True
                forged=context.new_page();forged.goto(base+'/?reservation=success&vin=7G2CEHED5RA040513&test_mode=true');forged.wait_for_selector('.card')
                assert forged.evaluate('localStorage.getItem("tesla_reservations")') is None
                assert forged.locator('#order-dialog[open]').count()==0
                assert '150-POINT CERTIFIED' not in forged.content();results['forged_callback_ignored']=True
                category=context.new_page();category.goto(base+'/models/model-y.html');category.wait_for_selector('.card');assert category.locator('#model').input_value()=='Model Y';results['category_preset']=True
                missing_center=next(x['vin'] for x in json.loads((ROOT/'inventory.json').read_text())['items'] if x.get('photo') and not x.get('location_center'))
                incomplete=context.new_page();incomplete.goto(base+'/?vin='+missing_center);incomplete.locator('#vehicle-request').click()
                assert 'Delivery and tax quote needed' in incomplete.locator('#deal-summary').inner_text()
                incomplete.locator('[data-deal-mode=finance]').click()
                assert 'vehicle price only; tax and delivery extra' in incomplete.locator('#deal-summary').inner_text().lower()
                results['unknown_delivery_keeps_balance_pending']=True;incomplete.close()
                mobile=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,device_scale_factor=1)
                mobile.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else (r.fulfill(status=200,content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#dce5eb"/></svg>') if r.request.resource_type=='image' else r.abort()))
                m=mobile.new_page();m.goto(base);m.wait_for_selector('.card');results['mobile_no_horizontal_overflow']=m.evaluate('document.documentElement.scrollWidth<=innerWidth');assert results['mobile_no_horizontal_overflow']
                m.locator('#mobile-filters').click();assert m.locator('#filters').is_visible();results['mobile_filters']=True;m.locator('#mobile-filters').click()
                m.screenshot(path=str(out/'tesla-marketplace-mobile.png'),full_page=False)
                assert not errors,errors;results['javascript_errors']=errors
                browser.close()
        finally:
            server.should_exit=True;thread.join(5);sock.close()
    (out/'browser-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
