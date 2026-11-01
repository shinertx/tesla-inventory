'use strict';
(() => {
  const scriptURL = document.currentScript.src;
  const rootURL = new URL('../', scriptURL);
  const metaApiBase = document.querySelector('meta[name="volts-api-base"]')?.content?.trim() || 'https://hank.jockeyvc.com/volts-api/api/';
  const useExternalApi = /^(www\.)?voltsandvins\.com$/i.test(location.hostname);
  const rawApiBase = window.VOLTS_API_BASE || document.body.dataset.apiBase || (useExternalApi ? metaApiBase : 'api/');
  const apiURL = new URL(rawApiBase.endsWith('/') ? rawApiBase : rawApiBase + '/', rootURL);
  document.querySelector('.brand').href=rootURL.href;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:2}).format(cents/100);
  const dollars = amount => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:0}).format(amount);
  let embeddedCheckout=null,stripeLoader=null,orderPollTimer=null,lastOrderSnapshot='';
  function destroyCheckout(){if(embeddedCheckout){embeddedCheckout.destroy();embeddedCheckout=null;}}
  function stopOrderPoll(){if(orderPollTimer){clearInterval(orderPollTimer);orderPollTimer=null;}}
  $('order-dialog').addEventListener('close',()=>{destroyCheckout();stopOrderPoll();});
  async function loadStripe(){
    if(window.Stripe)return;
    if(!stripeLoader)stripeLoader=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='https://js.stripe.com/endive/stripe.js';script.onload=resolve;script.onerror=()=>{stripeLoader=null;script.remove();reject(new Error('Secure payment form could not load. Retry safely.'));};document.head.append(script);});
    await stripeLoader;
  }
  let items=[], byVIN=new Map(), filtered=[], limit=36, activeVIN=null, apiReady=false, config=null;
  let saved=new Set(), zip='', requestKey=null, discovery='all',mediaVersion='',snapshotDate='';
  const galleryShards=new Map();let zipDataset=null,zipPoint=null;
  const zipState=()=>Array.isArray(zipPoint)&&typeof zipPoint[0]==='string'?zipPoint[0].toUpperCase():'';
  let galleryPhotos=[],galleryIndex=0;let galleryRequest=0;const failedPhotos=new Set();
  try { saved=new Set(JSON.parse(localStorage.getItem('marketplace_saved') || '[]')); zip=localStorage.getItem('marketplace_zip') || ''; } catch {}
  if (!/^\d{5}$/.test(zip)) zip='';
  const stages=['requested','quoted','checkout_pending','deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending','completed'];
  const onlineLabels={sign_contract:'Sign your purchase agreement',pay_balance:'Complete your balance payment',submit_title_documents:'Complete your title documents',track_delivery:'Track your delivery'};
  const stageNames={requested:'Preparing your deal',quoted:'Complete quote ready',checkout_pending:'Secure checkout opened',deposit_processing:'Deposit processing (bank debit pending)',deposit_paid:'Deposit verified',dealer_confirmed:'Dealer accepted your purchase',dealer_funded:'Dealer confirmed your payment',settlement_pending:'Final title paperwork',in_transit:'Carrier has the vehicle',delivered:'Vehicle delivered',completed:'Purchase complete',refund_pending:'Deposit refund pending',refunded:'Deposit refunded',quote_expired:'Quote expired',cancelled:'Request cancelled',payment_review:'Payment needs review'};

  function notify(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>{$('toast').hidden=true;},4500);}
  function open(id){ if (!$(id).open) $(id).showModal(); }
  function close(id){$(id).close();}
  document.addEventListener('click',e=>{const b=e.target.closest('[data-close]');if(b)close(b.dataset.close);});
  document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
  async function api(path,options={}){
    const headers={...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})};
    const response=await fetch(new URL(path,apiURL),{...options,headers});
    let payload;try{payload=await response.json();}catch{throw new Error('The request service is unavailable. No payment was collected.');}
    if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'Please check your details and try again.');
    return payload;
  }
  function currentAccess(){try{return JSON.parse(sessionStorage.getItem('marketplace_order') || 'null');}catch{return null;}}
  function updateSaved(){
    try{localStorage.setItem('marketplace_saved',JSON.stringify([...saved]));}catch{}
    $('saved-count').textContent=saved.size;
  }
  function toggleSave(vin){const adding=!saved.has(vin);adding?saved.add(vin):saved.delete(vin);updateSaved();applyFilters(false);if(adding){$('saved-button').classList.remove('saved-pop');void $('saved-button').offsetWidth;$('saved-button').classList.add('saved-pop');notify('♥ Added to your shortlist');}}
  function options(id,values){const select=$(id);values.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;select.append(option);});}
  function image(item,cls='',priority=false){
    return item.photo?`<img class="${cls}" src="${esc(item.photo)}" alt="${esc(item.year+' Tesla '+item.model)}" loading="${priority?'eager':'lazy'}" ${priority?'fetchpriority="high"':''} decoding="async" referrerpolicy="no-referrer">`:`<span class="photo-fallback">${esc(item.model)}</span>`;
  }
  function attachImageFallbacks(container){container.querySelectorAll('img').forEach(img=>{
    const ready=()=>img.classList.add('loaded');if(img.complete&&img.naturalWidth)ready();img.addEventListener('load',ready,{once:true});
    img.addEventListener('error',()=>{const card=img.closest('.card');if(card&&$('photos-only').checked){failedPhotos.add(card.dataset.vin);queueMicrotask(()=>applyFilters(false));return;}const fallback=document.createElement('span');fallback.className='photo-fallback';fallback.textContent='Photo coming soon';img.replaceWith(fallback);},{once:true});
  });}
  const odometer=x=>x.mileage>0?`${x.mileage.toLocaleString()} mi`:'Odometer to confirm';
  const saving=x=>x&&x.reference_sample>=5&&x.reference_price>x.display_price?Math.round(x.reference_price-x.display_price):0;
  function benchDate(x){
    const raw=x?.benchmark_date||x?.source_observed_at||snapshotDate;
    if(!raw)return 'current snapshot';
    const d=new Date(String(raw).length===10?raw+'T00:00:00Z':raw);
    return Number.isNaN(d.getTime())?String(raw).slice(0,10):d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
  }
  function distance(x){
    if(!zipPoint||!x.location_center)return null;
    const rad=n=>n*Math.PI/180;const [lat,lon]=x.location_center;const [state,baseLat,baseLon]=zipPoint;
    const a=Math.sin(rad(lat-baseLat)/2)**2+Math.cos(rad(lat))*Math.cos(rad(baseLat))*Math.sin(rad(lon-baseLon)/2)**2;
    return Math.round(3958.8*2*Math.atan2(Math.sqrt(a),Math.sqrt(Math.max(0,1-a))));
  }
  function nearbyLabel(x){const miles=distance(x);return miles===null?'':`About ${miles.toLocaleString()} mi away`;}
  const STATE_TAX={AL:.02,AK:0,AZ:.056,AR:.065,CA:.0725,CO:.029,CT:.0635,DE:0,DC:.06,FL:.06,GA:.07,HI:.04,ID:.06,IL:.0625,IN:.07,IA:.05,KS:.065,KY:.06,LA:.0445,ME:.055,MD:.06,MA:.0625,MI:.06,MN:.06875,MS:.05,MO:.04225,MT:0,NE:.055,NV:.0825,NH:0,NJ:.06625,NM:.04,NY:.04,NC:.03,ND:.05,OH:.0575,OK:.045,OR:0,PA:.06,RI:.07,SC:.05,SD:.04,TN:.07,TX:.0625,UT:.0685,VT:.06,VA:.0415,WA:.065,WV:.06,WI:.05,WY:.04};
  let dealMode='cash',dealDown=3500,dealTerm=60;
  function estimateDeal(x){
    const zState=zipState(),miles=distance(x);
    const ship=miles===null?null:(miles<=50?0:miles<=250?390:miles<=600?590:miles<=1200?890:1190);
    const taxRate=zState?(STATE_TAX[zState]??.06):null;
    const tax=taxRate!==null?Math.round(x.display_price*taxRate):null;
    const reg=zState?285:null;
    const otd=ship!==null&&tax!==null?x.display_price+ship+tax+reg:null;
    const afterDep=otd!==null?Math.max(0,otd-250):Math.max(0,x.display_price-250);
    const principal=Math.max(0,(otd??x.display_price)-dealDown-250);
    const r=.0649/12;
    const monthly=principal>0?Math.round((principal*r)/(1-Math.pow(1+r,-dealTerm))):0;
    return {zState,miles,ship,taxRate,tax,reg,otd,afterDep,monthly};
  }
  function rank(x){return Math.min(saving(x)/Math.max(x.reference_price||1,1),.15)*20+Math.min(x.photo_count||0,20)/20+Math.max(0,(x.year-2014)/14)+(x.mileage>0?Math.max(0,1-x.mileage/150000):.2);}
  function varied(rows){
    const buckets=new Map();rows.forEach(x=>{if(!buckets.has(x.model))buckets.set(x.model,[]);buckets.get(x.model).push(x);});
    const result=[];while(buckets.size){for(const [key,list] of [...buckets]){result.push(list.shift());if(!list.length)buckets.delete(key);}}return result;
  }
  function applyFilters(resetLimit=true){
    const search=$('search').value.trim().toLowerCase();
    filtered=items.filter(x=>(!$('photos-only').checked||(!!x.photo&&!failedPhotos.has(x.vin)))&&(discovery!=='finds'||saving(x)>=500)&&(!$('model').value||x.model===$('model').value)&&(!$('year').value||x.year===Number($('year').value))&&(!$('state').value||x.state===$('state').value)&&(!$('drivetrain').value||x.drivetrain===$('drivetrain').value)&&(!$('trim-family').value||x.trim_family===$('trim-family').value)&&(!$('factory').value||x.factory===$('factory').value)&&(!$('hardware').value||x.hardware===$('hardware').value)&&x.display_price<=Number($('price').value)&&x.mileage<=Number($('mileage').value)&&($('mileage').value==='999999'||x.mileage>0)&&(!$('saved-only').checked||saved.has(x.vin))&&(!$('reservable-only')?.checked||!!x.reservable)&&(!search||[x.vin,x.model,x.trim,x.stock_number,x.city,x.state,x.drivetrain,x.factory].join(' ').toLowerCase().includes(search)));
    const sort=$('sort').value;
    filtered.sort((a,b)=>sort==='recommended'?rank(b)-rank(a)||a.vin.localeCompare(b.vin):sort==='savings'?saving(b)-saving(a)||rank(b)-rank(a)||a.display_price-b.display_price||a.vin.localeCompare(b.vin):sort==='distance'?(distance(a)??Infinity)-(distance(b)??Infinity)||rank(b)-rank(a):sort==='price-desc'?b.display_price-a.display_price:sort==='mileage'?a.mileage-b.mileage:sort==='year'?b.year-a.year:a.display_price-b.display_price);
    if(sort==='recommended')filtered=varied(filtered);
    $('snapshot-status').textContent=zipPoint?`Near ${zip} · distances are approximate, straight-line estimates`:'Explore photos, compare the details, and save your favorites.';
    if(resetLimit!==false)limit=36;render();
  }
  function render(){
    $('result-count').textContent=`${filtered.length.toLocaleString()} Tesla listings`;
    $('cards').innerHTML=filtered.slice(0,limit).map((x,i)=>`<article class="card" data-vin="${x.vin}"><div class="photo-wrap">${image(x,'',i<6)}${(x.photo_count||x.photos?.length)>1?`<span class="photo-count">▧ ${x.photo_count||x.photos.length} photos</span>`:''}<button class="save" data-save="${x.vin}" aria-label="${saved.has(x.vin)?'Remove saved':'Save'} ${esc(x.year+' '+x.model)}" aria-pressed="${saved.has(x.vin)}">${saved.has(x.vin)?'♥':'♡'}</button></div><a class="card-main" href="?vin=${x.vin}" data-open="${x.vin}"><h3>${x.year} Tesla ${esc(x.model)}</h3><div class="trim">${esc(x.trim)}</div><div class="card-specs"><span>${odometer(x)}</span>${x.drivetrain?`<span title="${esc(x.drivetrain_basis)}">${esc(x.drivetrain)}</span>`:''}${x.factory?`<span>${esc(x.factory)}</span>`:''}${x.hardware?`<span>${esc(x.hardware)} verified</span>`:''}</div><div class="card-price"><strong class="price">${dollars(x.display_price)}</strong><span>est.</span>${saving(x)>0?`<span class="price-win">Save ${dollars(saving(x))}</span>`:''}</div></a>${saving(x)>0?`<details class="card-benchmark"><summary>Vs. ${dollars(x.reference_price)} benchmark · ${x.reference_sample} peers · ${esc(benchDate(x))}</summary><p>Mileage-adjusted comparison across ${x.reference_sample} peer Tesla asking prices (${esc(benchDate(x))} snapshot). Vehicle price only; tax, title, and delivery are quoted separately. Peer asking prices are not appraisals or guaranteed resale values.</p></details>`:''}<div class="card-footer"><span>${esc(x.city||'Vehicle location')}${x.state!=='US'?', '+esc(x.state):''}${nearbyLabel(x)?`<small>${nearbyLabel(x)}</small>`:''}</span><span class="reserve-note">Build your deal →</span></div></article>`).join('');
    $('empty').hidden=filtered.length>0;$('load-more').hidden=limit>=filtered.length;
    attachImageFallbacks($('cards'));
  }
  $('cards').addEventListener('click',e=>{const save=e.target.closest('[data-save]');if(save){toggleSave(save.dataset.save);return;}const link=e.target.closest('[data-open]');if(link){e.preventDefault();showVehicle(link.dataset.open);}});
  function showVehicle(vin){
    const x=byVIN.get(vin);if(!x){notify('This vehicle is not in the current published snapshot.');return;}
    activeVIN=vin;
    const url=new URL(location.href);url.searchParams.delete('reservation');url.searchParams.delete('session_id');url.searchParams.delete('test_mode');url.searchParams.set('vin',vin);history.replaceState(null,'',url);
    document.title=`${x.year} Tesla ${x.model} ${x.trim} (VIN ${x.vin}) | Volts & VINs`;
    let ld=$('dynamic-vehicle-schema');if(!ld){ld=document.createElement('script');ld.id='dynamic-vehicle-schema';ld.type='application/ld+json';document.head.append(ld);}
    const ldObj={'@context':'https://schema.org','@type':'Car','name':`${x.year} Tesla ${x.model} ${x.trim}`,'brand':{'@type':'Brand','name':'Tesla'},'model':x.model,'vehicleModelDate':String(x.year),'vehicleIdentificationNumber':x.vin,'itemCondition':'https://schema.org/UsedCondition','mileageFromOdometer':{'@type':'QuantitativeValue','value':x.mileage,'unitCode':'SMI'},'image':x.photo?[x.photo]:[],'url':url.href};
    if(x.reservable)ldObj.offers={'@type':'Offer','priceCurrency':'USD','price':x.display_price,'availability':'https://schema.org/InStock','url':url.href};
    ld.textContent=JSON.stringify(ldObj);
    $('vehicle-content').innerHTML=`<button class="close" data-close="vehicle-dialog" aria-label="Close vehicle details">×</button><div class="vehicle-top"><div class="vehicle-media"><div class="vehicle-image"><div id="gallery-stage">${image(x,'',true)}</div><button id="gallery-prev" class="gallery-arrow left" aria-label="Previous vehicle photo">‹</button><button id="gallery-next" class="gallery-arrow right" aria-label="Next vehicle photo">›</button><button id="photo-expand" class="photo-expand">⤢ View photos <span id="gallery-count"></span></button></div><div id="gallery-thumbs" class="gallery-thumbs"></div><div class="gallery-status"><span id="gallery-status" role="status"></span><button id="gallery-retry" class="secondary" hidden>Retry photos</button></div></div><div class="vehicle-summary"><p class="eyebrow">YOUR NEXT TESLA?</p><h2>${x.year} Tesla ${esc(x.model)}</h2><p class="summary-trim">${esc(x.trim)}</p><div class="summary-facts"><span><small>Odometer</small><strong>${odometer(x)}</strong></span>${x.drivetrain?`<span><small>Drivetrain</small><strong>${esc(x.drivetrain)}</strong></span>`:''}${x.factory?`<span><small>Built in</small><strong>${esc(x.factory)}</strong></span>`:''}<span><small>Vehicle location</small><strong>${esc(x.city||x.state)}${x.city&&x.state!== 'US'?', '+esc(x.state):''}</strong></span></div><div class="summary-price"><div class="summary-price-row"><strong class="price">${dollars(x.display_price)}</strong>${saving(x)>0?`<span class="summary-savings-pill">Save ${dollars(saving(x))}</span>`:''}</div><span>Estimated vehicle price</span>${x.reference_price&&x.reference_sample>=5?`<details class="benchmark-details ${saving(x)>0?'':'benchmark-neutral'}"><summary>${saving(x)>0?`${dollars(saving(x))} below ${dollars(x.reference_price)} peer benchmark`:`Peer benchmark ${dollars(x.reference_price)}`} (${x.reference_sample} listings · ${esc(benchDate(x))})</summary><p>Mileage-adjusted comparison across ${x.reference_sample} peer Tesla asking prices (${esc(benchDate(x))} snapshot). Vehicle savings apply to the vehicle price only; delivery, tax, and title are quoted separately. Peer asking prices are not appraisals or guaranteed resale values.</p></details>`:''}</div><p class="price-label">Tax, title, and delivery are quoted separately.</p><p class="summary-distance">${nearbyLabel(x)||'Set your ZIP to explore nearby vehicles.'}</p><div class="summary-actions"><button id="vehicle-request" class="primary">Build your deal</button><button id="vehicle-save" class="secondary">${saved.has(x.vin)?'♥ Saved to your shortlist':'♡ Save to your shortlist'}</button></div><p class="price-label">Enter your ZIP to estimate your total and request a written dealer quote.</p></div></div><div class="vehicle-body"><div class="vehicle-tabs" role="tablist" aria-label="Vehicle information"><button class="tab" role="tab" id="tab-details" aria-controls="vehicle-panel" aria-selected="true" data-tab="details">Vehicle details</button><button class="tab" role="tab" id="tab-pricing" aria-controls="vehicle-panel" aria-selected="false" data-tab="pricing">Price and delivery</button><button class="tab" role="tab" id="tab-process" aria-controls="vehicle-panel" aria-selected="false" data-tab="process">Purchase steps</button></div><div id="vehicle-panel" role="tabpanel" aria-labelledby="tab-details"></div></div>`;
    $('vehicle-save').addEventListener('click',()=>{toggleSave(x.vin);$('vehicle-save').textContent=saved.has(x.vin)?'♥ Saved to your shortlist':'♡ Save to your shortlist';});
    $('vehicle-request').addEventListener('click',()=>buildDeal(vin));
    $('vehicle-content').querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>vehicleTab(b.dataset.tab)));
    $('vehicle-content').querySelector('[role=tablist]').addEventListener('keydown',e=>{
      if(!['ArrowLeft','ArrowRight'].includes(e.key))return;
      const tabs=[...$('vehicle-content').querySelectorAll('[data-tab]')];const index=tabs.indexOf(document.activeElement);
      if(index<0)return;e.preventDefault();const next=tabs[(index+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];next.click();next.focus();
    });
    attachImageFallbacks($('vehicle-content'));vehicleTab('details');open('vehicle-dialog');startGallery(x);
  }
  function vehicleTab(tab){
    const x=byVIN.get(activeVIN);if(!x)return;
    $('vehicle-content').querySelectorAll('[data-tab]').forEach(b=>{b.setAttribute('aria-selected',b.dataset.tab===tab);b.tabIndex=b.dataset.tab===tab?0:-1;});
    $('vehicle-panel').setAttribute('aria-labelledby','tab-'+tab);
    const spec=(name,value)=>`<div class="spec"><span>${name}</span><strong>${esc(value)}</strong></div>`;
    if(tab==='details')$('vehicle-panel').innerHTML=`<div class="spec-grid">${spec('Availability',x.reservable?'Ready to reserve · seller hold active':'Ready for quote · dealer confirms hold')}${spec('VIN',x.vin)}${spec('Stock number',x.stock_number)}${spec('Trim',x.trim)}${spec('Model year',x.year)}${x.drivetrain?spec('Drivetrain',x.drivetrain):''}${x.factory?spec('Build factory',x.factory):''}${x.hardware?spec('AI computer · verified',x.hardware):''}</div><details class="verification-details"><summary>Checks before reservation</summary><p>The selling dealer confirms vehicle condition, clean title, equipment, and availability in your written quote before you pay a deposit.</p><div class="spec-grid">${spec('Title history',x.reservable?'Clean title verified':'Verified in your quote')}${spec('AI computer',x.hardware||'Confirmed on vehicle screen')}${spec('FSD software','Confirmed on vehicle screen')}${spec('Inspection','No inspection report on file')}${spec('Availability',x.reservable?'Seller hold active':'Confirmed by selling dealer')}</div><p>Drivetrain and factory come from the 17-character Tesla VIN. Your quote names the licensed selling dealer and complete out-the-door price.</p></details>`;
    if(tab==='pricing'){
      const est=estimateDeal(x);
      $('vehicle-panel').innerHTML=`${saving(x)>0?`<div class="line-item"><span>Peer benchmark (${x.reference_sample} listings · ${esc(benchDate(x))})</span><strong>${dollars(x.reference_price)}</strong></div><div class="line-item savings-line"><span>Your vehicle savings vs. benchmark (vehicle only)</span><strong>-${dollars(saving(x))}</strong></div>`:''}<div class="line-item"><span>Estimated vehicle price</span><strong>${dollars(x.display_price)}</strong></div><div class="line-item"><span>Estimated shipping to ${zip?esc(zip):'your ZIP'}${est.miles!==null?` (~${est.miles.toLocaleString()} mi)`:''} (not a carrier quote)</span><strong>${est.ship!==null?(est.ship===0?'$0 est. (<=50 mi)':dollars(est.ship)+' est.'):(zip?'Distance unavailable · carrier quote required':'Set ZIP to estimate shipping')}</strong></div><div class="line-item"><span>Estimated ${est.zState?esc(est.zState)+' ':'state '}tax, title &amp; registration${est.taxRate!==null?` (${(est.taxRate*100).toFixed(2).replace(/\.?0+$/,'')}%)`:''} (not a dealer quote)</span><strong>${est.tax!==null?dollars(est.tax+est.reg)+' est.':'Set ZIP to estimate tax'}</strong></div><div class="line-item otd-line"><span>Estimated total (before dealer quote)</span><strong>${est.otd!==null?dollars(est.otd)+' est.':dollars(x.display_price)+' + tax/delivery quote'}</strong></div><div class="line-item"><span>Reservation deposit (after written seller quote &amp; payment approval)</span><strong>-$250</strong></div><div class="line-item"><span>Estimated balance after $250 deposit</span><strong>${est.otd!==null?dollars(est.afterDep)+' est.':'Pending delivery and tax quote'}</strong></div>${nearbyLabel(x)?`<p>${nearbyLabel(x)}. Straight-line estimate between your ZIP center and the vehicle city; driving routes and final carrier rates are confirmed in your written quote.</p>`:''}<div class="notice">Shipping, tax, and monthly payment figures are estimates only. Your written quote names the licensed selling dealer and confirms actual shipping, tax, title, and purchase terms before any $250 deposit.</div>${x.reference_price?`<p>The mileage-adjusted asking-price comparison is ${dollars(x.reference_price)}, using ${x.reference_sample} peer listings (${esc(benchDate(x))} snapshot). This estimate is not an appraisal or a completed-sale value.</p>`:''}`;
    }
    if(tab==='process')$('vehicle-panel').innerHTML=stages.filter(s=>s!=='checkout_pending').map(s=>`<div class="order-stage">${esc(stageNames[s])}</div>`).join('')+'<p>You only pay the $250 refundable reservation after reviewing and accepting your complete written quote from the licensed selling dealer.</p>';
  }
  function paintDeal(){
    const x=byVIN.get(activeVIN);if(!x)return;
    const est=estimateDeal(x),zState=est.zState;
    $('deal-summary').innerHTML=`<p class="eyebrow">ESTIMATE YOUR TOTAL · MONTHLY PAYMENT CALCULATOR</p><h2>${x.year} Tesla ${esc(x.model)}</h2><div class="order-vehicle-card">${x.photo?`<img src="${esc(x.photo)}" alt="${esc(x.year+' Tesla '+x.model)}" loading="lazy" referrerpolicy="no-referrer">`:''}<div><strong>${esc(x.trim)} · ${odometer(x)}</strong><span>${esc(x.city||x.state)}${x.city&&x.state!=='US'?', '+esc(x.state):''}${nearbyLabel(x)?` · ${nearbyLabel(x)}`:''}</span>${saving(x)>0?`<em class="shortlist-save">Save ${dollars(saving(x))} vs. ${dollars(x.reference_price)} benchmark (${x.reference_sample} peers)</em>`:''}</div></div><div class="deal-mode-toggle" role="group" aria-label="Payment option"><button type="button" class="deal-mode-btn ${dealMode==='cash'?'active':''}" data-deal-mode="cash">Estimate your total · ${est.otd!==null?dollars(est.otd)+' est.':dollars(x.display_price)+' + quote'}</button><button type="button" class="deal-mode-btn ${dealMode==='finance'?'active':''}" data-deal-mode="finance">Monthly payment calculator · ~${dollars(est.monthly)}/mo</button></div>${dealMode==='finance'?`<div class="deal-finance-box"><div class="deal-finance-headline"><strong>${dollars(est.monthly)}<span>/mo est.</span></strong><small>6.49% illustrative APR · ${dealTerm} mos · ${dollars(dealDown)} down + $250 deposit${est.otd===null?' · vehicle price only; tax and delivery extra':''}</small></div><div class="form-row"><label>Cash down<select id="deal-down">${[1500,3500,5000,10000].map(v=>`<option value="${v}" ${dealDown===v?'selected':''}>${dollars(v)}</option>`).join('')}</select></label><label>Loan term<select id="deal-term">${[48,60,72].map(t=>`<option value="${t}" ${dealTerm===t?'selected':''}>${t} months</option>`).join('')}</select></label></div><p class="price-label">Illustrative monthly payment calculator only; not a credit offer, prequalification, or lender approval. Partner financing requires separate application and written terms.</p></div>`:''}${saving(x)>0?`<div class="line-item"><span>Peer benchmark (${x.reference_sample} listings · ${esc(benchDate(x))})</span><strong>${dollars(x.reference_price)}</strong></div><div class="line-item savings-line"><span>Vehicle savings vs. benchmark (vehicle only)</span><strong>-${dollars(saving(x))}</strong></div>`:''}<div class="line-item"><span>Estimated vehicle price</span><strong>${dollars(x.display_price)}</strong></div><div class="line-item"><span>Estimated shipping${zip?` to ${esc(zip)}`:''}${est.miles!==null?` (~${est.miles.toLocaleString()} mi)`:''} (not a carrier quote)</span><strong>${est.ship!==null?(est.ship===0?'$0 est. (<=50 mi)':dollars(est.ship)+' est.'):(zip?'Distance unavailable · carrier quote required':'Enter ZIP to estimate shipping')}</strong></div><div class="line-item"><span>Estimated ${zState?esc(zState)+' ':'state '}tax, title &amp; registration${est.taxRate!==null?` (${(est.taxRate*100).toFixed(2).replace(/\.?0+$/,'')}%)`:''} (not a dealer quote)</span><strong>${est.tax!==null?dollars(est.tax+est.reg)+' est.':'Enter ZIP to estimate tax'}</strong></div><div class="line-item otd-line"><span>Estimated total (before dealer quote)</span><strong>${est.otd!==null?dollars(est.otd)+' est.':dollars(x.display_price)+' + tax/delivery quote'}</strong></div><div class="line-item"><span>Quote request submission</span><strong>$0 (no payment collected)</strong></div><div class="line-item"><span>Reservation deposit (after written quote &amp; seller approval)</span><strong>-$250 toward purchase</strong></div><div class="line-item"><span>Estimated balance after $250 deposit</span><strong>${est.otd!==null?dollars(est.afterDep)+' est.':'Pending delivery and tax quote'}</strong></div><ol class="deal-steps"><li><strong>Enter your 5-digit ZIP below</strong> to estimate shipping, state tax, and monthly payments.</li><li><strong>${apiReady?'Continue to request a dealer quote ($0 today)':'Save a local deal draft in this browser'}</strong> — estimates do not lock a price or hold a vehicle.</li><li><strong>Written seller quote required first</strong> — $250 reservations open only after the licensed selling dealer confirms availability and payment approval.</li></ol>`;
    $('deal-summary').querySelectorAll('[data-deal-mode]').forEach(b=>b.addEventListener('click',()=>{dealMode=b.dataset.dealMode;paintDeal();}));
    $('deal-down')?.addEventListener('change',e=>{dealDown=Number(e.target.value);paintDeal();});
    $('deal-term')?.addEventListener('change',e=>{dealTerm=Number(e.target.value);paintDeal();});
  }
  function buildDeal(vin){
    const x=byVIN.get(vin);if(!x)return;activeVIN=vin;
    try{const d=JSON.parse(localStorage.getItem('marketplace_deal')||'null');if(d&&d.vin===vin&&d.mode)dealMode=d.mode;}catch{}
    const zState=zipState();
    paintDeal();
    $('deal-zip').value=zip;$('deal-message').textContent=apiReady?(zip&&zState?`Delivery ZIP ${zip} (${zState}) estimate shown above. Continue to request a dealer quote ($0 today).`:'Enter your 5-digit ZIP to estimate your total, then continue to request a dealer quote.'):'Enter your 5-digit ZIP to estimate your total and save your deal draft on this device.';
    $('deal-continue').textContent=apiReady?'Continue to quote request':'Save deal draft & ZIP';
    close('vehicle-dialog');open('deal-dialog');
  }
  $('deal-zip').addEventListener('input',async e=>{
    const val=e.target.value.trim();
    if(/^\d{5}$/.test(val)&&val!==zip){
      try{await resolveZip(val);paintDeal();const zs=zipState();$('deal-message').textContent=apiReady?`Delivery ZIP ${val}${zs?` (${zs})`:''} estimate shown above. Continue to request a dealer quote ($0 today).`:`Delivery ZIP ${val}${zs?` (${zs})`:''} estimate shown above. Save your deal draft on this device.`;}catch{}
    }
  });
  $('deal-form').addEventListener('submit',async e=>{
    e.preventDefault();const postal=$('deal-zip').value;
    try{await resolveZip(postal);paintDeal();if(apiReady){close('deal-dialog');startRequest(activeVIN);return;}
      localStorage.setItem('marketplace_deal',JSON.stringify({vin:activeVIN,zip:postal,mode:dealMode,created_at:new Date().toISOString()}));
      localStorage.setItem('marketplace_zip',postal);
      if(!saved.has(activeVIN))toggleSave(activeVIN);
      $('deal-message').textContent='Deal draft saved on this device. No order or reservation has been placed.';
      $('deal-continue').textContent='Draft saved';
    }catch(error){$('deal-message').textContent=error.message;}
  });
  function channel(){const value=new URLSearchParams(location.search).get('utm_source')||'direct';return /^[a-z0-9_-]{1,60}$/.test(value)?value:'direct';}
  async function startRequest(vin){
    activeVIN=vin;const x=byVIN.get(vin);$('request-car').textContent=`${x.year} ${x.model} · VIN ${vin}`;
    $('request-error').textContent='';requestKey=crypto.randomUUID();
    $('request-form').reset();$('request-form').elements.zip.value=zip;
    if(zipState())$('request-form').elements.state.value=zipState();
    if($('request-form').elements.payment_preference)$('request-form').elements.payment_preference.value=dealMode==='finance'?'partner_financing':'cash';
    close('vehicle-dialog');open('request-dialog');
    if(!apiReady){$('request-error').textContent='The request service is not connected. No personal details have been submitted.';$('submit-request').disabled=true;}else $('submit-request').disabled=false;
  }
  $('request-form').elements.zip.addEventListener('input',e=>{
    const val=e.target.value.trim();
    if(/^\d{5}$/.test(val)&&zipDataset?.[val]?.[0])$('request-form').elements.state.value=String(zipDataset[val][0]).toUpperCase();
  });
  $('request-form').addEventListener('submit',async e=>{
    e.preventDefault();if(!apiReady)return;const form=e.currentTarget;const b=$('submit-request');b.disabled=true;
    const data=new FormData(form);
    try{
      const order=await api('requests',{method:'POST',headers:{'Idempotency-Key':requestKey},body:JSON.stringify({vin:activeVIN,name:data.get('name'),email:data.get('email'),state:String(data.get('state')).toUpperCase(),zip:data.get('zip'),payment_preference:data.get('payment_preference')||'cash',demand_channel:channel(),campaign_id:new URLSearchParams(location.search).get('utm_campaign')?.slice(0,100)||'',consent:data.get('consent')==='on'})});
      sessionStorage.setItem('marketplace_order',JSON.stringify({id:order.id,token:order.access_token}));
      form.reset();close('request-dialog');showOrder(order);notify('Quote request recorded. No payment was collected.');
    }catch(error){$('request-error').textContent=error.message;}finally{b.disabled=false;}
  });
  function renderRecoverOrder(initialError=''){
    let draft=null;try{const d=JSON.parse(localStorage.getItem('marketplace_deal')||'null');if(d&&byVIN.has(d.vin))draft=d;}catch{}
    $('order-content').innerHTML=`<h2>Open your purchase request</h2><p>Use the Request ID and private access code you saved when submitting your request.</p>${draft?`<div class="notice">Saved deal draft found for VIN ${esc(draft.vin)}. <button type="button" id="resume-draft" class="text-button">Resume saved deal draft →</button></div>`:''}<form id="recover-form"><label>Request ID<input id="recover-id" required></label><label>Private access code<input id="recover-token" type="password" required></label><button class="primary">Open request</button><p id="recover-error" class="form-error" role="alert">${esc(initialError)}</p></form>`;
    $('resume-draft')?.addEventListener('click',()=>{close('order-dialog');buildDeal(draft.vin);});
    if(currentAccess()){
      const retry=document.createElement('button');retry.type='button';retry.id='retry-saved-order';retry.className='secondary';retry.textContent='Retry your saved request';
      retry.addEventListener('click',refreshOrder);$('recover-form').before(retry);
    }
    $('recover-form').addEventListener('submit',async e=>{e.preventDefault();const recovered={id:$('recover-id').value.trim(),token:$('recover-token').value.trim()};try{const order=await api('orders/'+encodeURIComponent(recovered.id),{headers:{Authorization:'Bearer '+recovered.token}});sessionStorage.setItem('marketplace_order',JSON.stringify(recovered));showOrder(order);}catch(error){$('recover-error').textContent=error.message;}});
  }
  async function refreshOrder(){
    const access=currentAccess();if(!access){renderRecoverOrder();open('order-dialog');return;}
    try{showOrder(await api('orders/'+encodeURIComponent(access.id),{headers:{Authorization:'Bearer '+access.token}}));}catch(error){renderRecoverOrder(error.message+' Your saved access is kept. Retry your request.');open('order-dialog');}
  }
  function showOrder(order){
    destroyCheckout();stopOrderPoll();lastOrderSnapshot=JSON.stringify(order);
    const q=order.quote;const access=currentAccess();
    const pref=order.payment_preference||'cash';
    const fin=order.financing||{state:'not_requested'};
    const tr=order.transport||{state:'unquoted'};
    const balState=order.balance_payment_state||'unpaid';
    const canChangePref=['requested','quoted','checkout_pending','deposit_processing','deposit_paid','dealer_confirmed'].includes(order.state);
    const finLabels={not_requested:'Not requested',prequalified:'Prequalified (not funded proceeds)',application_submitted:'Application submitted to partner lender',conditional_approval:'Conditionally approved (stips pending · not funded proceeds)',contract_signed:'Contract signed (awaiting lender wire)',lender_funded:'Lender proceeds funded to selling dealer',declined:'Declined by partner lender'};
    const balLabels={unpaid:'Awaiting balance payment',checkout_open:'ACH checkout session open',ach_processing:'ACH debit initiated (1–4 business days · vehicle release awaits settlement)',paid:'Balance settled and verified',failed:'ACH debit failed · retry available',expired:'Checkout session expired · retry available',payment_review:'Under payment review'};
    const trLabels={unquoted:'Awaiting carrier quote',quoted:'Carrier rate quoted (dispatch requires carrier acceptance)',carrier_accepted:'Carrier accepted dispatch',dispatched:'Vehicle picked up and in transit',delivered:'Delivered to buyer',exception:'Transport exception under review'};
    const finProvider=fin.provider||fin.lender_name||'';
    const trProvider=tr.provider||tr.carrier_name||'';
    const v=byVIN.get(order.vin)||order.vehicle||null;
    const refCents=q?(q.reference_price_cents||(v?.reference_sample>=5&&v?.reference_price?Math.round(v.reference_price*100):0)):(v?.reference_sample>=5&&v?.reference_price?Math.round(v.reference_price*100):0);
    const refSample=q?(q.reference_sample||v?.reference_sample||0):(v?.reference_sample||0);
    const vehSavingsCents=q?(q.vehicle_savings_cents??(refCents>q.vehicle_price_cents?refCents-q.vehicle_price_cents:0)):(saving(v)*100);
    const quoteDepositCents=q?(q.deposit_cents||25000):25000;
    const quoteBalanceCents=q?(q.balance_after_deposit_cents??Math.max(0,q.total_cents-quoteDepositCents)):0;
    const depositCredited=['deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending','completed'].includes(order.state);
    const statusText=order.state==='requested'?'Your deal is being prepared. Your complete written quote and licensed selling dealer will appear here once verified.':order.state==='deposit_processing'?'Your $250 bank reservation debit is processing (1–4 business days). Vehicle hold locks once funds settle.':order.state==='refund_pending'?(order.refund_submitted?'Your $250 deposit refund has been submitted to the payment processor and updates automatically once settled.':'Your $250 deposit refund is queued for processing and updates automatically.'):'Status updates automatically as each step is verified (or select Refresh status anytime).';
    $('order-content').innerHTML=`<p class="eyebrow">YOUR PURCHASE</p><h2>${esc(stageNames[order.state]||order.state)}</h2><p>VIN ${esc(order.vin)}</p><p class="price-label">Request ${esc(order.id)}</p>${v?.model?`<div class="order-vehicle-card">${v.photo?`<img src="${esc(v.photo)}" alt="${esc(v.year+' Tesla '+v.model)}" loading="lazy" referrerpolicy="no-referrer">`:''}<div><strong>${esc((v.year?v.year+' ':'')+'Tesla '+v.model)}</strong><span>${esc([v.trim,v.mileage>0?`${v.mileage.toLocaleString()} mi`:null,v.city&&v.state&&v.state!=='US'?`${v.city}, ${v.state}`:null].filter(Boolean).join(' · '))}</span>${vehSavingsCents>0?`<em class="shortlist-save">Save ${money(vehSavingsCents)} vs. ${money(refCents)} peer benchmark (${refSample} listings)</em>`:''}</div></div>`:''}<div class="form-row"><button id="save-access" class="text-button">Save private access receipt</button><button id="switch-order" class="text-button">Open a different request ID</button></div><p>${statusText}</p>${!config?.payments_enabled?'<p class="notice">Online deposit payments are currently disabled until licensed seller and payment provider approval are completed for this vehicle. Your quote request remains tracked here.</p>':''}<div class="line-item"><span>Payment path</span><strong>${pref==='partner_financing'?'Partner financing':'Cash / ACH bank transfer'}</strong></div>${canChangePref?`<label>Update payment preference<select id="order-payment-pref"><option value="cash" ${pref==='cash'?'selected':''}>Cash / ACH bank transfer</option><option value="partner_financing" ${pref==='partner_financing'?'selected':''}>Partner financing (subject to lender approval)</option></select></label>`:''}${q?`<h3>Your written quote</h3><p>Sold and fulfilled by <strong>${esc(q.seller.legal_name)}</strong><br>License ${esc(q.seller.license_number)} · ${esc(q.seller.address)}</p>${vehSavingsCents>0?`<div class="line-item"><span>Peer benchmark (${refSample} listings · ${esc(benchDate(v||{benchmark_date:q.benchmark_date}))})</span><strong>${money(refCents)}</strong></div><div class="line-item savings-line"><span>Vehicle savings vs. benchmark (vehicle only)</span><strong>-${money(vehSavingsCents)}</strong></div>`:''}${[['Vehicle price',money(q.vehicle_price_cents)],['Sales tax',money(q.tax_cents)],['Title and registration',money(q.title_registration_cents)],['Documentation',money(q.documentation_cents)],['Delivery',money(q.delivery_charge_cents)],['Complete purchase price',money(q.total_cents)],[depositCredited?'$250 reservation deposit (paid & credited)':'Reservation deposit (credited toward purchase)','-'+money(quoteDepositCents)],['Remaining balance after $250 deposit',money(quoteBalanceCents)]].map(([label,value])=>`<div class="line-item"><span>${label}</span><strong>${value}</strong></div>`).join('')}<p>Quote expires ${esc(new Date(q.valid_until*1000).toLocaleString())}.</p><ul class="terms-list">${Object.entries(q.terms).map(([label,url])=>`<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label.replaceAll('_',' '))}</a></li>`).join('')}</ul>`:''}${q&&['quoted','checkout_pending'].includes(order.state)&&config?.payments_enabled?'<label class="check"><input id="accept-quote" type="checkbox">I accept this complete quote and the linked deposit, return, and warranty terms.</label><button id="pay-deposit" class="primary">Pay refundable $250 reservation</button>':''}${pref==='partner_financing'||fin.state!=='not_requested'?`<section class="online-steps"><h3>Partner financing status</h3><div class="line-item"><span>Lender status</span><strong>${esc(finLabels[fin.state]||fin.state)}</strong></div>${finProvider?`<div class="line-item"><span>Partner lender</span><strong>${esc(finProvider)}</strong></div>`:''}${fin.approved_amount_cents>0?`<div class="line-item"><span>Approved financing amount</span><strong>${money(fin.approved_amount_cents)}</strong></div>`:''}${fin.funded_amount_cents>0?`<div class="line-item"><span>Funded proceeds to selling dealer</span><strong>${money(fin.funded_amount_cents)}</strong></div>`:''}${fin.stipulations?.length?`<div class="line-item"><span>Required stipulations</span><strong>${esc(fin.stipulations.join(', '))}</strong></div>`:''}${fin.application_url?`<a class="online-step" href="${esc(fin.application_url)}" target="_blank" rel="noopener noreferrer">Open partner lender application ↗</a>`:''}<p>Prequalification and conditional approval are not funded proceeds. Vehicle release requires verified lender funding to the selling dealer.</p></section>`:''}${q&&order.state==='dealer_confirmed'&&pref==='cash'?`<section class="online-steps"><h3>Remaining balance (${money(quoteBalanceCents)})</h3><div class="line-item"><span>Complete purchase price</span><strong>${money(q.total_cents)}</strong></div><div class="line-item"><span>Less $250 reservation credit</span><strong>-${money(quoteDepositCents)}</strong></div><div class="line-item"><span>Remaining balance due</span><strong>${money(quoteBalanceCents)}</strong></div><div class="line-item"><span>Balance status</span><strong>${esc(balLabels[balState]||balState)}</strong></div>${config?.payments_enabled&&['unpaid','checkout_open','failed','expired'].includes(balState)?'<label class="check"><input id="accept-balance" type="checkbox">I authorize ACH bank payment for the remaining balance under the accepted purchase terms.</label><button id="pay-balance" class="primary">Pay remaining balance via ACH</button>':''}<p>Bank account linking initiates an ACH Direct Debit (1–4 business days to settle). Vehicle release requires settled funds.</p></section>`:''}${tr.state!=='unquoted'?`<section class="online-steps"><h3>Delivery &amp; carrier tracking</h3><div class="line-item"><span>Transport status</span><strong>${esc(trLabels[tr.state]||tr.state)}</strong></div>${trProvider?`<div class="line-item"><span>Carrier</span><strong>${esc(trProvider)}</strong></div>`:''}${Number.isInteger(tr.rate_cents)?`<div class="line-item"><span>Carrier rate</span><strong>${money(tr.rate_cents)}</strong></div>`:''}${tr.quote_expires_at?`<div class="line-item"><span>Rate quote expires</span><strong>${esc(new Date(tr.quote_expires_at*1000).toLocaleString())}</strong></div>`:''}${tr.pickup_window_start&&tr.pickup_window_end?`<div class="line-item"><span>Pickup window</span><strong>${esc(new Date(tr.pickup_window_start*1000).toLocaleDateString())} – ${esc(new Date(tr.pickup_window_end*1000).toLocaleDateString())}</strong></div>`:''}${tr.delivery_window_start&&tr.delivery_window_end?`<div class="line-item"><span>Estimated delivery window</span><strong>${esc(new Date(tr.delivery_window_start*1000).toLocaleDateString())} – ${esc(new Date(tr.delivery_window_end*1000).toLocaleDateString())}</strong></div>`:''}${tr.bol_reference?`<div class="line-item"><span>Bill of lading (BOL)</span><strong>${esc(tr.bol_reference)}</strong></div>`:''}${tr.tracking_url?`<a class="online-step" href="${esc(tr.tracking_url)}" target="_blank" rel="noopener noreferrer">Open live carrier tracking ↗</a>`:''}<p>${tr.state==='quoted'?'A carrier rate quote is an estimate only; vehicle dispatch requires carrier acceptance and an electronic bill of lading.':'Carrier dispatch and delivery milestones are verified with the selling dealer and carrier.'}</p></section>`:''}${order.online_actions?.length?`<section class="online-steps"><h3>Complete your purchase</h3>${order.online_actions.map(a=>`<a class="online-step" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(onlineLabels[a.kind])} ↗</a>`).join('')}<p>Your purchase stays tracked here. Required signing or bank services open securely. Completion requires verification.</p></section>`:''}<div id="embedded-payment" class="embedded-payment"></div><div class="form-row"><button id="refresh-order" class="secondary">Refresh status</button>${['requested','quoted','quote_expired','checkout_pending','deposit_paid'].includes(order.state)?'<button id="cancel-order" class="secondary">Cancel request</button>':''}</div><button id="report-issue" class="text-button">Report a purchase issue</button><div id="issue-form" hidden><label>Issue type<select id="issue-kind"><option value="other">Purchase question</option><option value="return">Return request</option><option value="warranty">Warranty question</option><option value="transport_damage">Transport damage</option><option value="title_delay">Title processing</option></select></label><label>Describe the issue<textarea id="issue-description" minlength="5" maxlength="1000" rows="4"></textarea></label><button id="send-issue" class="secondary">Submit for review</button></div><button id="delete-request" class="text-button">Request personal-data deletion</button><p id="order-error" class="form-error" role="alert"></p>`;
    $('save-access').addEventListener('click',()=>{
      const content=JSON.stringify({request_id:access.id,private_access_code:access.token,site:rootURL.href,instructions:'Keep this receipt private. Open Your purchase request to restore access.'},null,2);
      const url=URL.createObjectURL(new Blob([content],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='vehicle-request-access.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
    $('switch-order')?.addEventListener('click',()=>{destroyCheckout();stopOrderPoll();renderRecoverOrder();});
    $('refresh-order').addEventListener('click',()=>{$('order-error').textContent='';refreshOrder();});
    $('order-payment-pref')?.addEventListener('change',async e=>{
      $('order-error').textContent='';
      try{const updated=await api(`orders/${access.id}/payment-preference`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({payment_preference:e.target.value})});showOrder(updated);notify('Payment preference updated.');}catch(err){$('order-error').textContent=err.message;}
    });
    $('report-issue').addEventListener('click',()=>{$('issue-form').hidden=!$('issue-form').hidden;});
    $('send-issue').addEventListener('click',async()=>{
      $('order-error').textContent='';
      try{await api(`orders/${access.id}/cases`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({kind:$('issue-kind').value,description:$('issue-description').value})});$('issue-form').hidden=true;notify('Your purchase issue was recorded for support review.');}catch(e){$('order-error').textContent=e.message;}
    });
    $('cancel-order')?.addEventListener('click',async()=>{$('order-error').textContent='';try{const result=await api(`orders/${access.id}/cancel`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({reason:'Customer requested cancellation'})});showOrder(result);}catch(e){$('order-error').textContent=e.message;}});
    $('delete-request').addEventListener('click',async()=>{$('order-error').textContent='';try{await api(`orders/${access.id}/privacy`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:'{}'});notify('Deletion request recorded for review against transaction retention requirements.');}catch(e){$('order-error').textContent=e.message;}});
    $('accept-quote')?.addEventListener('change',()=>{$('order-error').textContent='';});
    $('accept-balance')?.addEventListener('change',()=>{$('order-error').textContent='';});
    const mountStripeResult=async result=>{
      if(result.mode==='embedded_page'){
        await loadStripe();destroyCheckout();
        const provider=window.Stripe(result.publishable_key,{stripeAccount:result.account});
        embeddedCheckout=await provider.createEmbeddedCheckoutPage({fetchClientSecret:async()=>result.client_secret,onComplete:async()=>{destroyCheckout();await refreshOrder();notify('Payment submitted. Your purchase updates after payment verification.');}});
        embeddedCheckout.mount('#embedded-payment');$('embedded-payment').scrollIntoView({behavior:'smooth',block:'start'});
      }else{const target=new URL(result.url);if(target.protocol!=='https:'||target.hostname!=='checkout.stripe.com')throw new Error('Unexpected payment destination');location.assign(target.href);}
    };
    $('pay-deposit')?.addEventListener('click',async()=>{
      $('order-error').textContent='';
      if(!$('accept-quote').checked){$('order-error').textContent='Review and accept the quote and linked terms first.';return;}
      $('pay-deposit').disabled=true;
      try{const result=await api(`orders/${access.id}/checkout`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({quote_version:order.quote_version,terms_accepted:true})});await mountStripeResult(result);}catch(e){$('order-error').textContent=e.message;$('pay-deposit').disabled=false;}
    });
    $('pay-balance')?.addEventListener('click',async()=>{
      $('order-error').textContent='';
      if(!$('accept-balance').checked){$('order-error').textContent='Authorize the ACH balance payment and accepted purchase terms first.';return;}
      $('pay-balance').disabled=true;
      try{const result=await api(`orders/${access.id}/balance-checkout`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({quote_version:order.quote_version,terms_accepted:true})});await mountStripeResult(result);}catch(e){$('order-error').textContent=e.message;$('pay-balance').disabled=false;}
    });
    open('order-dialog');
    if(access&&(['requested','quoted','checkout_pending','deposit_processing','deposit_paid','dealer_confirmed','dealer_funded','in_transit','refund_pending'].includes(order.state)||balState==='ach_processing')){
      orderPollTimer=setInterval(async()=>{
        if(!$('order-dialog').open||embeddedCheckout||!$('issue-form')?.hidden)return;
        try{
          const latest=await api('orders/'+encodeURIComponent(access.id),{headers:{Authorization:'Bearer '+access.token}});
          if(JSON.stringify(latest)!==lastOrderSnapshot)showOrder(latest);
        }catch{}
      },4000);
    }
  }
  function watchGalleryImage(img){
    if(!img)return;
    img.addEventListener('error',()=>{
      const panel=document.createElement('div');panel.className='photo-fallback';
      const text=document.createElement('span');text.textContent='This photo could not load.';
      const retry=document.createElement('button');retry.className='secondary';retry.textContent='Retry this photo';
      retry.addEventListener('click',()=>{panel.replaceWith(img);watchGalleryImage(img);img.src=img.src;});
      panel.append(text,retry);img.replaceWith(panel);
    },{once:true});
  }
  function paintGallery(){
    $('gallery-prev').hidden=$('gallery-next').hidden=galleryPhotos.length<2;
    if(!galleryPhotos.length)return;const photo=galleryPhotos[galleryIndex];
    $('gallery-stage').innerHTML=`<img class="loaded" src="${esc(photo.url)}" alt="${esc(photo.title)}" referrerpolicy="no-referrer">`;
    watchGalleryImage($('gallery-stage').querySelector('img'));
    $('gallery-count').textContent=`${galleryIndex+1} / ${galleryPhotos.length}`;
    $('gallery-prev').hidden=$('gallery-next').hidden=galleryPhotos.length<2;
    $('gallery-thumbs').innerHTML=galleryPhotos.length>1||!(activeVIN&&byVIN.get(activeVIN)?.photo_count>1)?galleryPhotos.map((x,i)=>`<button class="gallery-thumb ${i===galleryIndex?'active':''}" data-photo="${i}" aria-label="${esc(x.title)} — photo ${i+1}"><img src="${esc(x.url)}" loading="lazy" alt="${esc(x.title)}" referrerpolicy="no-referrer"></button>`).join(''):'';
    $('gallery-thumbs').querySelectorAll('[data-photo]').forEach(b=>b.addEventListener('click',()=>{galleryIndex=Number(b.dataset.photo);paintGallery();}));
    if($('photo-dialog').open)paintFullPhoto();
    const thumb=$('gallery-thumbs').querySelector('.active');if(thumb)thumb.scrollIntoView({block:'nearest',inline:'nearest'});
  }
  function changePhoto(delta){if(!galleryPhotos.length)return;galleryIndex=(galleryIndex+delta+galleryPhotos.length)%galleryPhotos.length;paintGallery();}
  function paintFullPhoto(){const photo=galleryPhotos[galleryIndex];if(!photo)return;$('full-photo').src=photo.url;$('full-photo').alt=photo.title;$('full-caption').textContent=`${galleryIndex+1} / ${galleryPhotos.length} · ${photo.title}`;}
  function startGallery(x){
    galleryPhotos=x.photos?.length?x.photos:(x.photo?[{url:x.photo,title:`${x.year} Tesla ${x.model}`,category:'photos'}]:[]);galleryIndex=0;paintGallery();
    $('gallery-prev').addEventListener('click',()=>changePhoto(-1));$('gallery-next').addEventListener('click',()=>changePhoto(1));
    $('photo-expand').addEventListener('click',()=>{if(!galleryPhotos.length)return;paintFullPhoto();open('photo-dialog');});
    const load=async()=>{
      const request=++galleryRequest;
      $('gallery-status').textContent=galleryPhotos.length>1?`${galleryPhotos.length} vehicle photos`:'Loading vehicle photos…';$('gallery-retry').hidden=true;
      try{
        // Photo discovery must not depend on the unrelated checkout configuration race.
        let result;
        if(x.photo_count>1){
          const shard=(Number(x.vin.slice(-3))%128).toString(16).padStart(2,'0');
          if(!galleryShards.has(shard))galleryShards.set(shard,fetch(new URL(`media/${shard}.json?v=${encodeURIComponent(mediaVersion)}`,rootURL)).then(r=>{if(!r.ok)throw new Error('Photo download failed');return r.json();}));
          try{const data=await galleryShards.get(shard);if(!Array.isArray(data[x.vin])||!data[x.vin].length)throw new Error('Gallery missing');result={photos:data[x.vin]};}
          catch(e){galleryShards.delete(shard);throw e;}
        }else if(Number.isInteger(x.photo_count)){result={photos:galleryPhotos};}
        else{result=await api(`vehicles/${x.vin}/photos`);}
        if(activeVIN!==x.vin||request!==galleryRequest)return;
        if(result.photos.length){const selected=galleryPhotos[galleryIndex]?.url;galleryPhotos=result.photos;x.photos=result.photos;galleryIndex=Math.max(0,galleryPhotos.findIndex(p=>p.url===selected));paintGallery();}
        $('gallery-status').textContent=galleryPhotos.length>1?`${galleryPhotos.length} vehicle photos`:(galleryPhotos.length?'1 vehicle photo available. Additional photos are not available yet.':'Vehicle photos are not available yet.');
      }catch(e){
        if(activeVIN!==x.vin||request!==galleryRequest)return;
        $('gallery-status').textContent=galleryPhotos.length>1?`${galleryPhotos.length} vehicle photos`:'Additional photos could not load. Please retry.';$('gallery-retry').hidden=false;
      }
    };
    $('gallery-retry').addEventListener('click',load);load();
  }
  $('full-prev').addEventListener('click',()=>changePhoto(-1));$('full-next').addEventListener('click',()=>changePhoto(1));
  $('photo-dialog').addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();changePhoto(e.key==='ArrowRight'?1:-1);}});
  function showShortlist(){
    const favorites=items.filter(x=>saved.has(x.vin));
    $('shortlist-content').innerHTML=favorites.length?favorites.map(x=>`<button class="shortlist-car" data-shortlist-open="${x.vin}">${image(x)}<span><strong>${x.year} Tesla ${esc(x.model)}</strong><small>${esc(x.trim)} · ${x.mileage.toLocaleString()} mi</small><b>${dollars(x.display_price)}${saving(x)>0?` <em class="shortlist-save">Save ${dollars(saving(x))} vs. ${dollars(x.reference_price)} benchmark</em>`:''}</b></span><span>→</span></button>`).join(''):'<div class="shortlist-empty">♡<h3>Start with a favorite.</h3><p>Tap a heart while you explore. Your shortlist will be right here.</p></div>';
    $('compare-saved').hidden=favorites.length<2;
    $('shortlist-content').querySelectorAll('[data-shortlist-open]').forEach(b=>b.addEventListener('click',()=>{close('saved-dialog');showVehicle(b.dataset.shortlistOpen);}));attachImageFallbacks($('shortlist-content'));open('saved-dialog');
  }
  $('compare-saved').addEventListener('click',()=>{
    const xs=items.filter(x=>saved.has(x.vin)).slice(0,3);
    $('compare-content').innerHTML=`<div class="comparison-grid">${xs.map(x=>`<article>${image(x)}<h3>${x.year} ${esc(x.model)}</h3><div class="price">${dollars(x.display_price)}</div>${saving(x)>0?`<p class="compare-save">Save ${dollars(saving(x))} vs. ${dollars(x.reference_price)} (${x.reference_sample} peers · ${esc(benchDate(x))})</p>`:'<p class="compare-save-muted">At market reference</p>'}<p>${esc(x.trim)}</p><p>${x.mileage.toLocaleString()} miles</p><p>${esc(x.city)}, ${esc(x.state)}</p><button class="primary" data-compare-open="${x.vin}">Explore this Tesla</button></article>`).join('')}</div>`;
    $('compare-content').querySelectorAll('[data-compare-open]').forEach(b=>b.addEventListener('click',()=>{close('compare-dialog');showVehicle(b.dataset.compareOpen);}));close('saved-dialog');open('compare-dialog');
  });
  document.querySelectorAll('[data-discover]').forEach(button=>button.addEventListener('click',()=>{
    discovery=button.dataset.discover;document.querySelectorAll('[data-discover]').forEach(b=>b.classList.toggle('active',b===button));
    $('model').value=['Model Y','Model 3','Cybertruck'].includes(discovery)?discovery:'';
    $('price').value=discovery==='under25'?'25000':discovery==='under30'?'30000':'999999';$('mileage').value=discovery==='lowmiles'?'30000':'999999';$('search').value='';applyFilters();
  }));
  ['model','year','state','price','mileage','sort','saved-only','photos-only','reservable-only','drivetrain','trim-family','factory','hardware'].forEach(id=>$(id)?.addEventListener('change',applyFilters));
  let searchTimer;$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(applyFilters,140);});
  $('reset').addEventListener('click',()=>{['model','year','state','search','drivetrain','trim-family','factory','hardware'].forEach(id=>$(id).value='');$('price').value='999999';$('mileage').value='999999';$('saved-only').checked=false;if($('reservable-only'))$('reservable-only').checked=false;discovery='all';document.querySelectorAll('[data-discover]').forEach(b=>b.classList.toggle('active',b.dataset.discover==='all'));$('photos-only').checked=true;applyFilters();});
  $('load-more').addEventListener('click',()=>{limit+=36;render();});
  $('saved-button').addEventListener('click',showShortlist);
  $('mobile-filters').addEventListener('click',()=>$('filters').classList.toggle('expanded'));
  $('zip-label').textContent=zip||'Set ZIP';$('zip-button').addEventListener('click',()=>{$('zip-input').value=zip;open('zip-dialog');});
  async function resolveZip(value){
    if(!zipDataset){const r=await fetch(new URL('data/us_zip_centers.json',rootURL));if(!r.ok)throw new Error('Location data could not load. Please retry.');zipDataset=(await r.json()).zips;}
    if(!zipDataset[value])throw new Error('ZIP not found in our location data. Try a nearby ZIP.');
    zip=value;zipPoint=zipDataset[value];$('zip-label').textContent=zip;
    try{localStorage.setItem('marketplace_zip',zip);}catch{}
    $('sort').querySelector('[value=distance]').disabled=false;$('sort').value='distance';applyFilters();
    if(activeVIN&&$('vehicle-dialog').open&&byVIN.has(activeVIN)){const text=$('vehicle-content').querySelector('.summary-distance');if(text)text.textContent=nearbyLabel(byVIN.get(activeVIN))||'City distance is unavailable for this vehicle.';if($('tab-pricing').getAttribute('aria-selected')==='true')vehicleTab('pricing');}
  }
  $('zip-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;$('zip-error').textContent='';try{await resolveZip($('zip-input').value);try{localStorage.setItem('marketplace_zip',zip);}catch{}close('zip-dialog');}catch(error){$('zip-error').textContent=error.message;}finally{button.disabled=false;}});
  if(zip)resolveZip(zip).catch(()=>{zip='';zipPoint=null;$('zip-label').textContent='Set ZIP';});
  $('privacy-button').addEventListener('click',()=>open('privacy-dialog'));
  $('order-button').addEventListener('click',()=>{if(apiReady){refreshOrder();return;}try{const draft=JSON.parse(localStorage.getItem('marketplace_deal')||'null');if(draft&&byVIN.has(draft.vin)){buildDeal(draft.vin);return;}}catch{}notify('Choose a Tesla and select Build your deal to start.');});updateSaved();
  function purchaseAvailability(){
    const paymentsOn=!!(apiReady&&config?.payments_enabled);
    $('purchase-availability').hidden=paymentsOn;
    $('purchase-availability').textContent=apiReady?'Online quote requests are open. Online deposit payments remain disabled until licensed seller and payment provider approval.':'Online reservations are being connected. Browsing, monthly payment calculator, and saved deal drafts are available.';
    $('business-status').textContent=paymentsOn?'Find your Tesla · Estimate your total · $250 refundable reservation after quote approval':(apiReady?'Find your Tesla · Estimate your total · Monthly payment calculator · Request a dealer quote':'15,000+ Used Teslas Nationwide · Estimate Your Total · Monthly Payment Calculator');
    $('order-button').hidden=false;$('order-button').textContent=apiReady?'Your purchase':'Your saved deal';
    if(apiReady)$('hero-description').innerHTML=paymentsOn?'Shop used Teslas nationwide. Estimate your total, request a written dealer quote, and reserve online for <strong>$250, refundable</strong> after seller approval.':'Shop used Teslas nationwide. Estimate your total with our monthly payment calculator and submit a <strong>free online quote request</strong> for seller confirmation.';
    if(items.length)applyFilters(false);
    const button=$('vehicle-request');if(button){button.disabled=false;button.textContent='Build your deal';}
  }
  purchaseAvailability();
  api('config').then(c=>{config=c;apiReady=!!c.requests_enabled;purchaseAvailability();}).catch(()=>{apiReady=false;purchaseAvailability();});
  fetch(new URL('inventory.json?v='+(new URL(scriptURL).searchParams.get('v')||'current'),rootURL)).then(r=>{if(!r.ok)throw new Error('Inventory unavailable');return r.json();}).then(payload=>{
    mediaVersion=payload.meta?.media_version||'';snapshotDate=payload.meta?.built_at||'';
    items=payload.items.filter(x=>!x.expires_at||new Date(x.expires_at).getTime()>Date.now());byVIN=new Map(items.map(x=>[x.vin,x]));
    const reservableCount=items.filter(x=>x.reservable).length;
    if($('reservable-label'))$('reservable-label').textContent=reservableCount?`Reservable now (${reservableCount} seller-approved)`:'Reservable now (0 seller-approved · browsing discovery catalog)';
    if($('reservable-only'))$('reservable-only').disabled=!reservableCount;
    document.querySelector('[data-discover=finds]').hidden=!items.some(x=>saving(x)>=500);
    for(const option of $('hardware').options){if(option.value){const count=items.filter(x=>x.hardware===option.value).length;option.disabled=!count;option.textContent=count?`${option.value} · ${count} verified`:`${option.value} — evidence needed`;}}
    options('model',[...new Set(items.map(x=>x.model))].sort());options('year',[...new Set(items.map(x=>x.year))].sort((a,b)=>b-a));options('state',[...new Set(items.map(x=>x.state))].filter(x=>x!=='US').sort());
    $('snapshot-status').textContent='Your next favorite is in here.';
    const preset=document.body.dataset.preset;if(preset){for(const part of preset.split(';')){const [key,value]=part.split(':');if(key==='discover'){discovery=value;document.querySelectorAll('[data-discover]').forEach(b=>b.classList.toggle('active',b.dataset.discover===value));}else if($(key))$(key).value=value;}}
    const q=new URLSearchParams(location.search).get('q');if(q&&$('search'))$('search').value=q;
    applyFilters();
    const vin=new URLSearchParams(location.search).get('vin');if(vin)showVehicle(vin);
    // Redirect parameters never prove payment. Only an authenticated server order does.
    if(new URLSearchParams(location.search).has('checkout')&&currentAccess())refreshOrder();
  }).catch(()=>{$('result-count').textContent='Inventory is temporarily unavailable';$('snapshot-status').textContent='Please try again later. No request or payment was created.';});
})();
