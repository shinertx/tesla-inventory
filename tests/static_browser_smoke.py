"""Exercise the actual GitHub Pages subpath, without an API or mocked vehicle images."""
import functools,json,sys,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
class PagesHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/tesla-inventory/'):self.path=self.path[len('/tesla-inventory'):]
        return super().do_GET()
    def log_message(self,*args):pass

def main(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(PagesHandler,directory=str(ROOT)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}/tesla-inventory/'
    result={'api_present':False,'mock_images':False,'named_galleries':{},'javascript_errors':[]}
    try:
        with sync_playwright() as p:
            b=p.chromium.launch();page=b.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:result['javascript_errors'].append(str(e)))
            for vin,count in [('5YJ3E1EA8SF921313',30),('7SAYGDED1RF039277',45),('5YJ3E1EA8KF413066',59)]:
                page.goto(base+'?vin='+vin);page.wait_for_function('(n)=>document.querySelectorAll(".gallery-thumb").length===n',arg=count)
                page.wait_for_function('()=>document.querySelector("#gallery-stage img")?.naturalWidth>0')
                assert page.locator('#vehicle-request').is_disabled()
                assert page.locator('#vehicle-request').inner_text()=='Online reservations coming soon'
                page.locator('.gallery-thumb').last.click();page.wait_for_function('()=>document.querySelector("#gallery-stage img")?.naturalWidth>0')
                result['named_galleries'][vin]={'count':count,'first_and_last_rendered':True}
            page.goto(base);page.wait_for_selector('.card');page.locator('.save').first.click();assert page.locator('#saved-count').inner_text()=='1'
            page.locator('[data-discover=under30]').click();assert page.locator('.card').count()>0;result['discovery_and_save']=True
            page.goto(base+'models/model-y.html');page.wait_for_selector('.card');assert page.locator('#model').input_value()=='Model Y';result['category_subpath']=True
            mobile=b.new_page(viewport={'width':390,'height':844},is_mobile=True);mobile.goto(base+'?vin=5YJ3E1EA8SF921313');mobile.wait_for_function('()=>document.querySelectorAll(".gallery-thumb").length===30');mobile.wait_for_function('()=>document.querySelector("#gallery-stage img")?.naturalWidth>0');result['mobile_gallery']=True
            mobile.screenshot(path=str(out/'static-customer-gallery.png'))
            assert not result['javascript_errors'];b.close()
    finally:server.shutdown();server.server_close()
    (out/'static-browser-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else ROOT/'.data/static-browser-results')
