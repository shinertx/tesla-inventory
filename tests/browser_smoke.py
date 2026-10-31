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
        settings=Settings(db_path=Path(tmp)/'orders.db',origin=f'http://127.0.0.1:{port}')
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
                context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else r.abort())
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base);page.wait_for_selector('.card');results['initial_cards']=page.locator('.card').count();assert results['initial_cards']==36
                page.screenshot(path=str(out/'tesla-marketplace-desktop.png'),full_page=False)
                page.select_option('#model','Cybertruck');results['model_filter']=all('Cybertruck' in t for t in page.locator('.card h3').all_text_contents());assert results['model_filter']
                page.locator('.save').first.click();assert page.locator('#saved-count').inner_text()=='1'
                page.locator('.card-main').first.click();page.wait_for_selector('#vehicle-dialog[open]')
                detail=page.locator('#vehicle-content').inner_text();assert '97.4%' not in detail and '8.2mm' not in detail and '150-POINT CERTIFIED' not in detail
                results['honest_vehicle_details']='No inspection report on file' in detail;assert results['honest_vehicle_details']
                page.locator('#vehicle-request').click();page.locator('[name=name]').fill('Browser Test Buyer');page.locator('[name=email]').fill('browser@example.test');page.locator('[name=state]').fill('TX');page.locator('[name=zip]').fill('78201');page.locator('[name=consent]').check();page.locator('#submit-request').click()
                page.wait_for_selector('#order-dialog[open]');assert 'Verification requested' in page.locator('#order-content').inner_text();results['durable_request']=True
                access=page.evaluate('JSON.parse(sessionStorage.getItem("marketplace_order"))')
                page.reload();page.wait_for_selector('.card');page.locator('[data-close=vehicle-dialog]').click();page.locator('#order-button').click();page.wait_for_selector('#order-dialog[open]');assert 'Verification requested' in page.locator('#order-content').inner_text();results['status_survives_reload']=True
                page.locator('#report-issue').click();page.locator('#issue-description').fill('Please verify the charging adapters included with this vehicle.');page.locator('#send-issue').click();page.locator('#issue-form').wait_for(state='hidden');results['support_case']=True
                page.locator('#cancel-order').click();page.get_by_role('heading',name='Request cancelled').wait_for();results['cancellation']=True
                forged=context.new_page();forged.goto(base+'/?reservation=success&vin=7G2CEHED5RA040513&test_mode=true');forged.wait_for_selector('.card')
                assert forged.evaluate('localStorage.getItem("tesla_reservations")') is None
                assert forged.locator('#order-dialog[open]').count()==0
                assert '150-POINT CERTIFIED' not in forged.content();results['forged_callback_ignored']=True
                category=context.new_page();category.goto(base+'/models/model-y.html');category.wait_for_selector('.card');assert category.locator('#model').input_value()=='Model Y';results['category_preset']=True
                mobile=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,device_scale_factor=1)
                mobile.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else r.abort())
                m=mobile.new_page();m.goto(base);m.wait_for_selector('.card');results['mobile_no_horizontal_overflow']=m.evaluate('document.documentElement.scrollWidth<=innerWidth');assert results['mobile_no_horizontal_overflow']
                m.locator('#mobile-filters').click();assert m.locator('#filters').is_visible();results['mobile_filters']=True;m.locator('#mobile-filters').click()
                m.screenshot(path=str(out/'tesla-marketplace-mobile.png'),full_page=False)
                assert not errors,errors;results['javascript_errors']=errors
                browser.close()
        finally:
            server.should_exit=True;thread.join(5);sock.close()
    (out/'browser-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
if __name__=='__main__':main()
