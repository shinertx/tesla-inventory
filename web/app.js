'use strict';
(() => {
  const scriptURL = document.currentScript.src;
  const rootURL = new URL('../', scriptURL);
  const metaApiBase = document.querySelector('meta[name="volts-api-base"]')?.content?.trim() || 'https://api.voltsandvins.com/api/';
  const useExternalApi = /^(www\.)?voltsandvins\.com$/i.test(location.hostname);
  const rawApiBase = window.VOLTS_API_BASE || document.body.dataset.apiBase || (useExternalApi ? metaApiBase : 'api/');
  const apiURL = new URL(rawApiBase.endsWith('/') ? rawApiBase : rawApiBase + '/', rootURL);
  function trackVisit(event, vin=''){
    if(!useExternalApi && !window.ENABLE_VISIT_BEACON) return;
    try{
      fetch(new URL('visit', apiURL), {
        method:'POST',
        keepalive:true,
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({event, path:location.pathname+location.search, vin, referrer:document.referrer||''})
      }).catch(()=>{});
    }catch{}
  }
  document.querySelector('.brand').href=rootURL.href;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:2}).format(cents/100);
  const dollars = amount => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:0}).format(amount);
  let embeddedCheckout=null,stripeLoader=null,orderPollTimer=null,lastOrderSnapshot='',orderViewVersion=0,shippingEstimateTimer=null;
  function destroyCheckout(){if(embeddedCheckout){embeddedCheckout.destroy();embeddedCheckout=null;}}
  function stopOrderPoll(){if(orderPollTimer){clearInterval(orderPollTimer);orderPollTimer=null;}if(shippingEstimateTimer){clearTimeout(shippingEstimateTimer);shippingEstimateTimer=null;}}
  $('order-dialog').addEventListener('close',()=>{orderViewVersion++;destroyCheckout();stopOrderPoll();});
  async function loadStripe(){
    if(window.Stripe)return;
    if(!stripeLoader)stripeLoader=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='https://js.stripe.com/endive/stripe.js';script.onload=resolve;script.onerror=()=>{stripeLoader=null;script.remove();reject(new Error('Secure payment form could not load. Retry safely.'));};document.head.append(script);});
    await stripeLoader;
  }
  let items=[], byVIN=new Map(), filtered=[], limit=36, activeVIN=null, apiReady=false, config=null;
  let compareSelected=new Set();
  let saved=new Set(), zip='', requestKey=null, discovery='all',mediaVersion='',snapshotDate='';
  const galleryShards=new Map();let zipDataset=null,zipPoint=null,zipDatasetPromise=null,zipLookupVersion=0;
  const zipState=()=>Array.isArray(zipPoint)&&typeof zipPoint[0]==='string'?zipPoint[0].toUpperCase():'';
  let galleryPhotos=[],galleryIndex=0;let galleryRequest=0;const failedPhotos=new Set();
  try { saved=new Set(JSON.parse(localStorage.getItem('marketplace_saved') || '[]')); zip=localStorage.getItem('marketplace_zip') || ''; } catch {}
  if (!/^\d{5}$/.test(zip)) zip='';
  const stages=['requested','quoted','checkout_pending','deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending','completed'];
  const onlineLabels={sign_contract:'Sign your purchase agreement',pay_balance:'Complete your balance payment',submit_title_documents:'Complete your title documents',track_delivery:'Track your delivery'};
  const stageNames={requested:'Request received',quoted:'Your final price is ready',checkout_pending:'Secure checkout opened',deposit_processing:'Deposit processing (bank debit pending)',deposit_paid:'Deposit verified',dealer_confirmed:'Dealer accepted your purchase',dealer_funded:'Dealer confirmed your payment',settlement_pending:'Final title paperwork',in_transit:'Carrier has the vehicle',delivered:'Vehicle delivered',completed:'Purchase complete',refund_pending:'Deposit refund pending',refunded:'Deposit refunded',quote_expired:'Quote expired',cancelled:'Request cancelled',payment_review:'Payment needs review'};

  function notify(message){$('toast').textContent=message;$('toast').hidden=false;setTimeout(()=>{$('toast').hidden=true;},4500);}
  function open(id){ if (!$(id).open) $(id).showModal(); }
  function close(id){if(id==='request-dialog'&&requestSubmitting)return;$(id).close();}
  document.addEventListener('click',e=>{const b=e.target.closest('[data-close]');if(b)close(b.dataset.close);});
  document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close(d.id);}}));
  async function api(path,options={}){
    const headers={...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})};
    let response;
    try{response=await fetch(new URL(path,apiURL),{...options,headers});}
    catch{throw new Error('We could not confirm the result. Refresh your request status before trying again.');}
    let payload;try{payload=await response.json();}catch{throw new Error('We could not confirm the result. Refresh your request status before trying again.');}
    if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'Please check your details and try again.');
    return payload;
  }
  let accessInMemory,accessPersistenceFailed=false;
  function currentAccess(){
    if(accessInMemory!==undefined)return accessInMemory;
    try{const access=JSON.parse(sessionStorage.getItem('marketplace_order')||'null');return accessInMemory=access&&typeof access.id==='string'&&typeof access.token==='string'?access:null;}
    catch{accessPersistenceFailed=true;return accessInMemory=null;}
  }
  function rememberAccess(access){
    accessInMemory=access;
    try{sessionStorage.setItem('marketplace_order',JSON.stringify(access));accessPersistenceFailed=false;}
    catch{accessPersistenceFailed=true;}
  }
  function privateReturnLink(access){
    const url=new URL(rootURL.href);url.search='';
    url.hash=new URLSearchParams({request:access.id,access:access.token}).toString();return url.href;
  }
  function parseReturnLink(value){
    let url;try{url=new URL(value.trim());}catch{throw new Error('Paste the complete private return link you saved.');}
    const data=new URLSearchParams(url.hash.slice(1)),id=data.get('request')||'',token=data.get('access')||'';
    if(url.origin!==rootURL.origin||url.pathname!==rootURL.pathname||url.username||url.password||! /^[A-Za-z0-9-]{8,100}$/.test(id)||! /^[A-Za-z0-9_-]{12,200}$/.test(token))throw new Error('Use a private return link from this site.');
    return {id,token};
  }
  let restoredPrivateLink=false,privateLinkError='';
  const incomingAccess=new URLSearchParams(location.hash.slice(1));
  if(incomingAccess.has('request')||incomingAccess.has('access')){
    try{rememberAccess(parseReturnLink(location.href));restoredPrivateLink=true;}catch(error){privateLinkError=error.message;}
    history.replaceState(null,'',rootURL.href);
  }
  // A private fragment is removed before any analytics or API request.
  trackVisit('page_view',new URLSearchParams(location.search).get('vin')||'');
  function saveReturnPage(access){
    const link=privateReturnLink(access);
    const html=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>Your Volts &amp; VINs request</title><style>body{font:17px/1.6 system-ui;background:#f7f8fa;color:#17212d;margin:0;padding:28px}main{max-width:520px;margin:8vh auto;background:white;padding:32px;border-radius:16px}a{display:inline-block;background:#17212d;color:white;padding:14px 20px;border-radius:9px;text-decoration:none}small{display:block;margin-top:24px;color:#56616f}</style><main><p>VOLTS &amp; VINS</p><h1>Your request, saved.</h1><p>Use this button to check your final price, payment, and delivery updates.</p><a href="${esc(link)}" rel="noreferrer">Return to my request</a><small>Keep this file private. Anyone with its link can open your request. No payment is made by opening it.</small></main></html>`;
    const blob=URL.createObjectURL(new Blob([html],{type:'text/html'}));const a=document.createElement('a');a.href=blob;a.download='Volts-and-VINs-return-link.html';a.click();setTimeout(()=>URL.revokeObjectURL(blob),1000);
  }
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
    const ship=miles===null?null:(miles<=50?200:miles<=250?590:miles<=600?790:miles<=1200?1090:1390);
    const taxRate=zState?(STATE_TAX[zState]??.06):null;
    const tax=taxRate!==null?Math.round(x.display_price*taxRate):null;
    const reg=zState?285:null;
    const otd=ship!==null&&tax!==null?x.display_price+ship+tax+reg:null;
    const afterDep=otd!==null?Math.max(0,otd-250):Math.max(0,x.display_price-250);
    const principal=Math.max(0,(otd??x.display_price)-dealDown);
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
    $('result-count').textContent=`${filtered.length.toLocaleString()} Tesla ${filtered.length===1?'listing':'listings'}`;
    $('cards').innerHTML=filtered.slice(0,limit).map((x,i)=>`<article class="card" data-vin="${x.vin}"><div class="photo-wrap"><a class="photo-link" href="?vin=${x.vin}" data-open="${x.vin}" aria-label="View ${esc(x.year+' Tesla '+x.model)} photos and details">${image(x,'',i<6)}</a>${(x.photo_count||x.photos?.length)>1?`<span class="photo-count">▧ ${x.photo_count||x.photos.length} photos</span>`:''}<button class="save" data-save="${x.vin}" aria-label="${saved.has(x.vin)?'Remove saved':'Save'} ${esc(x.year+' '+x.model)}" aria-pressed="${saved.has(x.vin)}">${saved.has(x.vin)?'♥':'♡'}</button></div><a class="card-main" href="?vin=${x.vin}" data-open="${x.vin}"><h3>${x.year} Tesla ${esc(x.model)}</h3><div class="trim">${esc(x.trim)}</div><div class="card-specs"><span>${odometer(x)}</span>${x.drivetrain?`<span title="${esc(x.drivetrain_basis)}">${esc(x.drivetrain)}</span>`:''}${x.factory?`<span>Built in ${esc(x.factory)}</span>`:''}${x.hardware?`<span>${esc(x.hardware)} verified</span>`:''}</div><div class="card-price"><strong class="price">${dollars(x.display_price)}</strong><span>est.</span>${saving(x)>0?`<span class="price-win">Save ${dollars(saving(x))}</span>`:''}</div></a>${saving(x)>0?`<details class="card-benchmark"><summary>Compared with similar listings</summary><p>Mileage-adjusted comparison across ${x.reference_sample} similar Tesla asking prices (${esc(benchDate(x))} snapshot). Vehicle price only; tax, title, and delivery are quoted separately. Peer asking prices are not appraisals or guaranteed resale values.</p></details>`:''}<div class="card-footer"><span><span class="vehicle-location-label">Vehicle location</span>${esc(x.city||'Vehicle location')}${x.state!=='US'?', '+esc(x.state):''}${nearbyLabel(x)?`<small>${nearbyLabel(x)}</small>`:''}</span><button type="button" class="card-price-action" data-price="${x.vin}" aria-label="Review price for ${esc(x.year+' Tesla '+x.model)}">Review price</button></div></article>`).join('');
    $('filters-done').textContent=`Show ${filtered.length.toLocaleString()} results`;
    $('empty').hidden=filtered.length>0;$('load-more').hidden=limit>=filtered.length;
    attachImageFallbacks($('cards'));
  }
  $('cards').addEventListener('click',e=>{const save=e.target.closest('[data-save]');if(save){toggleSave(save.dataset.save);return;}const price=e.target.closest('[data-price]');if(price){buildDeal(price.dataset.price);return;}const link=e.target.closest('[data-open]');if(link){e.preventDefault();showVehicle(link.dataset.open);}});
  function showVehicle(vin){
    const x=byVIN.get(vin);if(!x){notify('This vehicle is not in the current published snapshot.');return;}
    activeVIN=vin;trackVisit('vin_view',vin);
    const url=new URL(location.href);url.searchParams.delete('reservation');url.searchParams.delete('session_id');url.searchParams.delete('test_mode');url.searchParams.set('vin',vin);history.replaceState(null,'',url);
    document.title=`${x.year} Tesla ${x.model} ${x.trim} (VIN ${x.vin}) | Volts & VINs`;
    let ld=$('dynamic-vehicle-schema');if(!ld){ld=document.createElement('script');ld.id='dynamic-vehicle-schema';ld.type='application/ld+json';document.head.append(ld);}
    const ldObj={'@context':'https://schema.org','@type':'Car','name':`${x.year} Tesla ${x.model} ${x.trim}`,'brand':{'@type':'Brand','name':'Tesla'},'model':x.model,'vehicleModelDate':String(x.year),'vehicleIdentificationNumber':x.vin,'itemCondition':'https://schema.org/UsedCondition','mileageFromOdometer':{'@type':'QuantitativeValue','value':x.mileage,'unitCode':'SMI'},'image':x.photo?[x.photo]:[],'url':url.href};
    if(x.reservable)ldObj.offers={'@type':'Offer','priceCurrency':'USD','price':x.display_price,'availability':'https://schema.org/InStock','url':url.href};
    ld.textContent=JSON.stringify(ldObj);
    $('vehicle-content').innerHTML=`<button class="close" data-close="vehicle-dialog" aria-label="Close vehicle details">×</button><div class="vehicle-top"><div class="vehicle-media"><div class="vehicle-image"><div id="gallery-stage">${image(x,'',true)}</div><button id="gallery-prev" class="gallery-arrow left" aria-label="Previous vehicle photo">‹</button><button id="gallery-next" class="gallery-arrow right" aria-label="Next vehicle photo">›</button><button id="photo-expand" class="photo-expand">⤢ View photos <span id="gallery-count"></span></button></div><div id="gallery-thumbs" class="gallery-thumbs"></div><div class="gallery-status"><span id="gallery-status" role="status"></span><button id="gallery-retry" class="secondary" hidden>Retry photos</button></div></div><div class="vehicle-summary"><p class="eyebrow">YOUR NEXT TESLA?</p><h2>${x.year} Tesla ${esc(x.model)}</h2><p class="summary-trim">${esc(x.trim)}</p><div class="summary-facts"><span><small>Odometer</small><strong>${odometer(x)}</strong></span>${x.drivetrain?`<span><small>Drivetrain</small><strong>${esc(x.drivetrain)}</strong></span>`:''}${x.factory?`<span><small>Build factory</small><strong>${esc(x.factory)}</strong></span>`:''}<span><small>Vehicle location</small><strong>${esc(x.city||x.state)}${x.city&&x.state!== 'US'?', '+esc(x.state):''}</strong></span></div><div class="summary-price"><div class="summary-price-row"><strong class="price">${dollars(x.display_price)}</strong>${saving(x)>0?`<span class="summary-savings-pill">Save ${dollars(saving(x))}</span>`:''}</div><span>Estimated vehicle price</span>${x.reference_price&&x.reference_sample>=5?`<details class="benchmark-details ${saving(x)>0?'':'benchmark-neutral'}"><summary>${saving(x)>0?`${dollars(saving(x))} below ${dollars(x.reference_price)} similar listings`:`Similar listings: ${dollars(x.reference_price)}`} (${x.reference_sample} listings · ${esc(benchDate(x))})</summary><p>Mileage-adjusted comparison across ${x.reference_sample} similar Tesla asking prices (${esc(benchDate(x))} snapshot). Vehicle savings apply to the vehicle price only; delivery, tax, and title are quoted separately. Peer asking prices are not appraisals or guaranteed resale values.</p></details>`:''}</div><p class="price-label">Tax, title, and delivery are quoted separately.</p><p class="summary-distance">${nearbyLabel(x)||'Set your ZIP to explore nearby vehicles.'}</p><div class="summary-actions"><button id="vehicle-save" class="secondary">${saved.has(x.vin)?'♥ Saved to your shortlist':'♡ Save to your shortlist'}</button></div><p class="price-label">Review your total, then request a final price. $0 today.</p></div></div><div class="vehicle-body"><div class="vehicle-tabs" role="tablist" aria-label="Vehicle information"><button class="tab" role="tab" id="tab-details" aria-controls="vehicle-panel" aria-selected="true" data-tab="details">Vehicle details</button><button class="tab" role="tab" id="tab-pricing" aria-controls="vehicle-panel" aria-selected="false" data-tab="pricing">Price and delivery</button><button class="tab" role="tab" id="tab-process" aria-controls="vehicle-panel" aria-selected="false" data-tab="process">Purchase steps</button></div><div id="vehicle-panel" role="tabpanel" aria-labelledby="tab-details"></div></div>`;
    $('vehicle-footer').innerHTML=`<div><strong>${dollars(x.display_price)}</strong><small>Estimated vehicle price</small></div><button id="vehicle-request" class="primary">Review price</button>`;
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
    if(tab==='details')$('vehicle-panel').innerHTML=`<div class="spec-grid">${spec('Availability',x.reservable?'Ready to reserve · seller hold active':'Availability to be confirmed')}${spec('VIN',x.vin)}${spec('Stock number',x.stock_number)}${spec('Trim',x.trim)}${spec('Model year',x.year)}${spec('Vehicle location',[x.city,x.state!=='US'?x.state:null].filter(Boolean).join(', ')||'Location not recorded')}${x.drivetrain?spec('Drivetrain',x.drivetrain):''}${x.factory?spec('Build factory',x.factory):''}${x.hardware?spec('AI computer · verified',x.hardware):''}</div><details class="verification-details"><summary>Checks before reservation</summary><p>We confirm availability, title, condition, and equipment before you accept a final quote.</p><div class="spec-grid">${spec('Title history',x.reservable?'Clean title verified':'Awaiting verification')}${spec('AI computer',x.hardware||'Awaiting screen verification')}${spec('FSD software','Awaiting screen verification')}${spec('Inspection','No inspection report on file')}${spec('Availability',x.reservable?'Seller hold active':'Awaiting confirmation')}</div><p>Drivetrain and factory come from the 17-character Tesla VIN. Your quote names the licensed selling dealer and complete out-the-door price.</p></details>`;
    if(tab==='pricing'){
      const est=estimateDeal(x);
      $('vehicle-panel').innerHTML=`${saving(x)>0?`<div class="line-item"><span>Similar listings (${x.reference_sample} · ${esc(benchDate(x))})</span><strong>${dollars(x.reference_price)}</strong></div><div class="line-item savings-line"><span>Your vehicle savings vs. benchmark (vehicle only)</span><strong>-${dollars(saving(x))}</strong></div>`:''}<div class="line-item"><span>Estimated vehicle price</span><strong>${dollars(x.display_price)}</strong></div><div class="line-item"><span>Estimated shipping to ${zip?esc(zip):'your ZIP'}${est.miles!==null?` (~${est.miles.toLocaleString()} mi)`:''} (not a carrier quote)</span><strong>${est.ship!==null?(est.ship===200?'$200 est. (<=50 mi)':dollars(est.ship)+' est.'):(zip?'Distance unavailable · carrier quote required':'Set ZIP to estimate shipping')}</strong></div><div class="line-item"><span>Estimated ${est.zState?esc(est.zState)+' ':'state '}tax, title &amp; registration${est.taxRate!==null?` (${(est.taxRate*100).toFixed(2).replace(/\.?0+$/,'')}%)`:''} (not a dealer quote)</span><strong>${est.tax!==null?dollars(est.tax+est.reg)+' est.':'Set ZIP to estimate tax'}</strong></div><div class="line-item otd-line"><span>Estimated total (before dealer quote)</span><strong>${est.otd!==null?dollars(est.otd)+' est.':dollars(x.display_price)+' + tax/delivery quote'}</strong></div><div class="line-item"><span>Reservation deposit (after written seller quote &amp; payment approval)</span><strong>-$250</strong></div><div class="line-item"><span>Estimated balance after $250 deposit</span><strong>${est.otd!==null?dollars(est.afterDep)+' est.':'Pending delivery and tax quote'}</strong></div>${nearbyLabel(x)?`<p>${nearbyLabel(x)}. Straight-line estimate between your ZIP center and the vehicle city; driving routes and final carrier rates are confirmed in your written quote.</p>`:''}<div class="notice">Shipping, tax, and monthly payment figures are estimates only. Your written quote names the licensed selling dealer and confirms actual shipping, tax, title, and purchase terms before any $250 deposit.</div>${x.reference_price?`<p>The mileage-adjusted asking-price comparison is ${dollars(x.reference_price)}, using ${x.reference_sample} peer listings (${esc(benchDate(x))} snapshot). This estimate is not an appraisal or a completed-sale value.</p>`:''}`;
    }
    if(tab==='process')$('vehicle-panel').innerHTML=stages.filter(s=>s!=='checkout_pending').map(s=>`<div class="order-stage">${esc(stageNames[s])}</div>`).join('')+'<p>You only pay the $250 refundable reservation after reviewing and accepting your complete written quote from the licensed selling dealer.</p>';
  }
  let requestDraft=null,requestSubmitting=false;
  function paintDeal(){
    const x=byVIN.get(activeVIN);if(!x)return;
    const est=estimateDeal(x),zState=est.zState;
    $('deal-summary').innerHTML=`<p class="eyebrow">1 OF 2 · REVIEW PRICE</p><h2>${x.year} Tesla ${esc(x.model)}</h2><p class="flow-car-summary">${esc(x.trim)} · ${odometer(x)}</p><div class="deal-total"><span>Estimated total</span><strong>${est.otd!==null?dollars(est.otd):dollars(x.display_price)+' + tax & delivery'}</strong><small>${est.otd!==null?'Vehicle, delivery, tax & registration':'Delivery and tax quote needed'}</small></div>${saving(x)>0?`<p class="flow-savings">Vehicle price saves ${dollars(saving(x))} compared with ${dollars(x.reference_price)} similar listings.</p>`:''}<div class="price-breakdown"><div class="line-item"><span>Vehicle price</span><strong>${dollars(x.display_price)}</strong></div><div class="line-item"><span>Estimated delivery${zip?' to '+esc(zip):''}</span><strong>${est.ship!==null?dollars(est.ship):(zip?'Quote needed':'ZIP needed')}</strong></div><div class="line-item"><span>Estimated tax & registration${zState?' · '+esc(zState):''}</span><strong>${est.tax!==null?dollars(est.tax+est.reg):'ZIP needed'}</strong></div></div><div class="deal-mode-toggle" role="group" aria-label="Payment option"><button type="button" class="deal-mode-btn ${dealMode==='cash'?'active':''}" aria-pressed="${dealMode==='cash'}" data-deal-mode="cash">Pay in full</button><button type="button" class="deal-mode-btn ${dealMode==='finance'?'active':''}" aria-pressed="${dealMode==='finance'}" data-deal-mode="finance">Monthly estimate</button></div>${dealMode==='finance'?`<div class="deal-finance-box"><div class="deal-finance-headline"><strong>${dollars(est.monthly)}<span>/mo est.</span></strong></div><div class="form-row"><label>Down payment<select id="deal-down">${[1500,3500,5000,10000].map(v=>`<option value="${v}" ${dealDown===v?'selected':''}>${dollars(v)}</option>`).join('')}</select></label><label>Loan term<select id="deal-term">${[48,60,72].map(t=>`<option value="${t}" ${dealTerm===t?'selected':''}>${t} months</option>`).join('')}</select></label></div><p class="price-label">Illustrative example at 6.49% APR; not a credit offer. Down payment includes the $250 reservation.${est.otd===null?' Vehicle price only; tax and delivery extra.':''}</p></div>`:''}<details class="estimate-details"><summary>About this estimate</summary><p>Delivery, tax, registration, and monthly payments are estimates. Your final quote confirms the licensed seller, vehicle checks, complete price, and terms.</p><p>The $250 reservation becomes available after your quote is approved. It counts toward your purchase.</p>${x.reference_price&&x.reference_sample>=5?`<p>Vehicle comparison uses ${x.reference_sample} similar asking prices from ${esc(benchDate(x))}. It is not an appraisal.</p>`:''}</details>`;
    $('deal-summary').querySelectorAll('[data-deal-mode]').forEach(b=>b.addEventListener('click',()=>{dealMode=b.dataset.dealMode;paintDeal();}));
    $('deal-down')?.addEventListener('change',e=>{dealDown=Number(e.target.value);paintDeal();});
    $('deal-term')?.addEventListener('change',e=>{dealTerm=Number(e.target.value);paintDeal();});
  }
  function buildDeal(vin){
    const x=byVIN.get(vin);if(!x)return;activeVIN=vin;trackVisit('deal_estimator',vin);
    try{const d=JSON.parse(localStorage.getItem('marketplace_deal')||'null');if(d&&d.vin===vin&&d.mode)dealMode=d.mode;}catch{}
    paintDeal();$('deal-zip').value=zip;
    $('deal-message').textContent=zipState()?`Estimate for ${zip}. Your final price is confirmed before payment.`:'Enter your delivery ZIP to estimate the total.';
    $('deal-continue').textContent=apiReady?'Continue':'Save price';
    close('vehicle-dialog');open('deal-dialog');$('deal-scroll').scrollTop=0;
  }
  $('deal-back').addEventListener('click',()=>{close('deal-dialog');showVehicle(activeVIN);});
  $('deal-zip').addEventListener('input',async e=>{
    const val=e.target.value.trim(),vin=activeVIN;
    if(/^\d{5}$/.test(val)&&val!==zip){
      try{if(!await resolveZip(val)||activeVIN!==vin||!$('deal-dialog').open||$('deal-zip').value!==val)return;paintDeal();$('deal-message').textContent=`Estimate for ${val}. Your final price is confirmed before payment.`;}catch(error){if(activeVIN===vin&&$('deal-dialog').open&&$('deal-zip').value===val)$('deal-message').textContent=error.message;}
    }
  });
  $('deal-form').addEventListener('submit',async e=>{
    e.preventDefault();const postal=$('deal-zip').value,vin=activeVIN,button=$('deal-continue');if(button.disabled)return;button.disabled=true;
    try{if(!await resolveZip(postal)||activeVIN!==vin||!$('deal-dialog').open)return;paintDeal();if(apiReady){close('deal-dialog');startRequest(activeVIN);return;}
      localStorage.setItem('marketplace_deal',JSON.stringify({vin:activeVIN,zip:postal,mode:dealMode,created_at:new Date().toISOString()}));
      localStorage.setItem('marketplace_zip',postal);
      if(!saved.has(activeVIN))toggleSave(activeVIN);
      $('deal-message').textContent='Price saved on this device. No request or reservation has been placed.';
      $('deal-continue').textContent='Price saved';
    }catch(error){if(activeVIN===vin&&$('deal-dialog').open)$('deal-message').textContent=error.message;}finally{button.disabled=false;}
  });
  function channel(){const value=new URLSearchParams(location.search).get('utm_source')||'direct';return /^[a-z0-9_-]{1,60}$/.test(value)?value:'direct';}
  function paintRequestEstimate(){
    const x=byVIN.get(activeVIN);if(!x)return;
    const form=$('request-form'),postal=form.elements.zip.value.trim();
    const est=estimateDeal(x),matches=postal===zip&&!!zipState();
    $('request-estimate').innerHTML=`<div class="request-estimate-total"><span>Estimated total</span><strong>${matches&&est.otd!==null?dollars(est.otd):dollars(x.display_price)+' + tax & delivery'}</strong></div><p>${matches&&est.otd!==null?'Vehicle, estimated delivery, tax & registration to '+esc(postal):'Enter a valid delivery ZIP to update delivery and tax.'}</p>${saving(x)>0?`<p class="flow-savings">Vehicle price saves ${dollars(saving(x))} compared with ${dollars(x.reference_price)} similar listings.</p>`:''}`;
    $('request-finance-note').hidden=form.elements.payment_preference.value!=='partner_financing';
  }
  async function startRequest(vin){
    activeVIN=vin;const x=byVIN.get(vin);$('request-car').textContent=`${x.year} ${x.model} · ${x.trim}`;
    $('request-error').textContent='';const form=$('request-form');
    if(!requestDraft||requestDraft.vin!==vin){requestKey=crypto.randomUUID();requestDraft={vin,key:requestKey};form.reset();}
    else{requestKey=requestDraft.key;for(const [name,value] of Object.entries(requestDraft.fields||{})){if(form.elements[name]){if(form.elements[name].type==='checkbox')form.elements[name].checked=value;else form.elements[name].value=value;}}}
    form.elements.zip.value=zip;if(zipState())form.elements.state.value=zipState();
    form.elements.payment_preference.value=dealMode==='finance'?'partner_financing':'cash';
    paintRequestEstimate();
    close('vehicle-dialog');open('request-dialog');$('request-scroll').scrollTop=0;
    if(!apiReady){$('request-error').textContent='Requests are temporarily unavailable. Your details have not been sent.';$('submit-request').disabled=true;}else $('submit-request').disabled=false;
  }
  function keepRequestDraft(){
    if(!requestDraft)return;const form=$('request-form');requestDraft.fields={};
    for(const name of ['name','email','state','zip','payment_preference','consent'])requestDraft.fields[name]=form.elements[name].type==='checkbox'?form.elements[name].checked:form.elements[name].value;
  }
  $('request-back').addEventListener('click',async()=>{
    keepRequestDraft();const vin=activeVIN,postal=$('request-form').elements.zip.value.trim(),button=$('request-back');
    dealMode=$('request-form').elements.payment_preference.value==='partner_financing'?'finance':'cash';
    button.disabled=true;
    try{if(/^\d{5}$/.test(postal))await resolveZip(postal);}catch{}
    finally{button.disabled=false;}
    if(activeVIN!==vin||!$('request-dialog').open)return;
    close('request-dialog');buildDeal(vin);$('deal-zip').value=postal;
  });
  $('request-dialog').addEventListener('close',keepRequestDraft);
  $('request-dialog').addEventListener('cancel',e=>{if(requestSubmitting)e.preventDefault();});
  $('request-form').elements.payment_preference.addEventListener('change',paintRequestEstimate);
  $('request-form').elements.zip.addEventListener('input',async e=>{
    const val=e.target.value.trim(),vin=activeVIN;paintRequestEstimate();
    if(!/^\d{5}$/.test(val))return;
    try{
      if(!await resolveZip(val)||activeVIN!==vin||!$('request-dialog').open||e.target.value.trim()!==val)return;
      $('request-form').elements.state.value=zipState();paintRequestEstimate();
    }catch{if(activeVIN===vin&&$('request-dialog').open)paintRequestEstimate();}
  });
  $('request-form').addEventListener('submit',async e=>{
    e.preventDefault();if(!apiReady)return;const form=e.currentTarget;const b=$('submit-request');if(requestSubmitting||b.disabled)return;requestSubmitting=true;
    const navigation=[$('request-back'),$('request-dialog').querySelector('[data-close]')];navigation.forEach(control=>control.disabled=true);b.disabled=true;b.textContent='Sending request…';
    const data=new FormData(form);keepRequestDraft();
    try{
      const order=await api('requests',{method:'POST',headers:{'Idempotency-Key':requestKey},body:JSON.stringify({vin:activeVIN,name:data.get('name'),email:data.get('email'),state:String(data.get('state')).toUpperCase(),zip:data.get('zip'),payment_preference:data.get('payment_preference')||'cash',demand_channel:channel(),campaign_id:new URLSearchParams(location.search).get('utm_campaign')?.slice(0,100)||'',consent:data.get('consent')==='on'})});
      rememberAccess({id:order.id,token:order.access_token});requestDraft=null;requestSubmitting=false;
      form.reset();close('request-dialog');showOrder(order);notify('Your final price request is saved. $0 paid today.');
    }catch(error){$('request-error').textContent=error.message;}finally{requestSubmitting=false;b.disabled=false;b.textContent='Request final price · $0 today';navigation.forEach(control=>control.disabled=false);}
  });
  function renderRecoverOrder(initialError=''){
    stopOrderPoll();
    const recoveryVersion=++orderViewVersion;
    let draft=null;try{const d=JSON.parse(localStorage.getItem('marketplace_deal')||'null');if(d&&byVIN.has(d.vin))draft=d;}catch{}
    $('order-content').innerHTML=`<p class="eyebrow">YOUR REQUEST</p><h2>Pick up where you left off.</h2><p>Open the private return link you saved after sending your request.</p><form id="recover-link-form"><label>Private return link<input id="recover-link" type="url" required autocomplete="off" placeholder="Paste your saved link"></label><button id="open-return-link" class="primary">Open my request</button></form>${draft?`<div class="notice">You also have a saved price. <button type="button" id="resume-draft" class="text-button">Review saved price →</button></div>`:''}<details id="legacy-recovery" class="estimate-details"><summary>Use an older access receipt</summary><p>Older receipts contain a request ID and a private access code.</p><form id="recover-form"><label>Request ID<input id="recover-id" required autocomplete="off"></label><label>Private access code<input id="recover-token" type="password" required autocomplete="off"></label><button class="secondary">Open older request</button></form></details><p id="recover-error" class="form-error" role="alert">${esc(initialError)}</p>`;
    const errorNode=$('recover-error');let pending=false;
    async function recover(access,button){
      if(pending)return;pending=true;button.disabled=true;errorNode.textContent='';
      try{const order=await api('orders/'+encodeURIComponent(access.id),{headers:{Authorization:'Bearer '+access.token}});if(recoveryVersion===orderViewVersion&&$('order-dialog').open){rememberAccess(access);showOrder(order);}}
      catch(error){if(errorNode.isConnected&&recoveryVersion===orderViewVersion)errorNode.textContent=error.message;}
      finally{pending=false;if(button.isConnected)button.disabled=false;}
    }
    $('recover-link-form').addEventListener('submit',e=>{e.preventDefault();try{recover(parseReturnLink($('recover-link').value),$('open-return-link'));}catch(error){errorNode.textContent=error.message;}});
    $('recover-form').addEventListener('submit',e=>{e.preventDefault();recover({id:$('recover-id').value.trim(),token:$('recover-token').value.trim()},e.currentTarget.querySelector('button'));});
    $('resume-draft')?.addEventListener('click',()=>{close('order-dialog');buildDeal(draft.vin);});
    if(currentAccess()){
      const retry=document.createElement('button');retry.type='button';retry.id='retry-saved-order';retry.className='secondary';retry.textContent='Retry my saved request';
      retry.addEventListener('click',refreshOrder);$('recover-link-form').before(retry);
    }
  }
  async function refreshOrder(){
    const access=currentAccess();if(!access){renderRecoverOrder();open('order-dialog');return;}
    const version=orderViewVersion;
    try{const order=await api('orders/'+encodeURIComponent(access.id),{headers:{Authorization:'Bearer '+access.token}});if(version===orderViewVersion&&currentAccess()?.id===access.id)showOrder(order);}
    catch(error){if(version===orderViewVersion&&currentAccess()?.id===access.id){renderRecoverOrder(error.message+' Your saved access is kept. Retry your request.');open('order-dialog');}}
  }
  async function loadSupportCases(access){
    const list=$('support-case-list');if(!list)return;
    try{
      const result=await api(`orders/${access.id}/cases`,{headers:{Authorization:'Bearer '+access.token}});
      if($('support-case-list')!==list||currentAccess()?.id!==access.id)return;
      const labels={other:'Purchase question',return:'Return request',warranty:'Warranty question',transport_damage:'Transport damage',title_delay:'Title processing'};
      list.innerHTML=result.items.length?result.items.map(c=>`<details class="support-case"><summary>${esc(labels[c.kind]||c.kind)} · ${esc(c.status.replaceAll('_',' '))}</summary><p>Reference: ${esc(c.id)}</p><p>${esc(c.description)}</p></details>`).join(''):'<p>No support requests yet.</p>';
    }catch{if($('support-case-list')===list)list.textContent='Support history could not load. Select Refresh status to retry.';}
  }
  function showOrder(order){
    const access=currentAccess();if(!access||order.id!==access.id)return;
    const version=++orderViewVersion;
    const isCurrentView=()=>version===orderViewVersion&&currentAccess()?.id===access.id&&$('order-dialog').open;
    destroyCheckout();stopOrderPoll();lastOrderSnapshot=JSON.stringify(order);
    const q=order.quote;
    const pref=order.payment_preference||'cash';
    const fin=order.financing||{state:'not_requested'};
    const tr=order.transport||{state:'unquoted'};
    const shippingEstimate=order.shipping_estimate,nowSeconds=Date.now()/1000;
    const hasShippingEstimate=!q&&shippingEstimate?.binding===false&&shippingEstimate?.carrier_booked===false&&Number.isInteger(shippingEstimate.customer_estimate_cents)&&shippingEstimate.customer_estimate_cents>0&&shippingEstimate.customer_estimate_cents<=2000000&&Number.isInteger(shippingEstimate.observed_at)&&Number.isInteger(shippingEstimate.cache_expires_at)&&shippingEstimate.observed_at<=nowSeconds&&nowSeconds<shippingEstimate.cache_expires_at&&shippingEstimate.cache_expires_at<=shippingEstimate.observed_at+900;
    const balState=order.balance_payment_state||'unpaid';
    const canChangePref=['requested','quoted','checkout_pending','deposit_processing','deposit_paid','dealer_confirmed'].includes(order.state);
    const finLabels={not_requested:'Application not submitted',application_ready:'Application ready · not submitted',prequalified:'Prequalified · final approval still needed',application_submitted:'Application submitted to partner lender',conditional_approval:'Additional information needed before funding',contract_signed:'Contract signed (awaiting lender wire)',lender_funded:'Lender payment confirmed',declined:'Declined by partner lender'};
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
    const statusMessages={
      requested:'Nothing to pay today. We are confirming availability, vehicle details, and your complete price. Save your return link to check for your quote.',
      quoted:'Review your final price, seller details, and terms below before reserving.',
      checkout_pending:'Complete the secure payment below, or refresh this page to check its status.',
      deposit_processing:'Your $250 bank payment is processing. Your reservation is confirmed after funds settle.',
      deposit_paid:'Your reservation is confirmed. Complete the next step shown here, or wait for your purchase documents.',
      dealer_confirmed:'Your purchase is accepted. Your next available payment or document step appears here.',
      dealer_funded:'Payment is confirmed. Delivery details appear here after a carrier accepts the shipment.',
      in_transit:'Your Tesla is on its way. Check delivery updates below.',
      delivered:'Your Tesla was delivered. Any available title steps and support options appear here.',
      settlement_pending:'Final title paperwork is being completed. Check this page for updates.',
      completed:'Your purchase is complete. Your request details and support options remain available here.',
      quote_expired:'This quote expired. Select Request updated quote below before making a payment.',
      payment_review:'We are checking your payment. Do not pay again. Select Get help if you need assistance.',
      cancelled:'This request is cancelled. No further purchase action is needed.',
      refunded:'Your deposit was refunded. You can review this request or browse more Teslas.',
    };
    const statusText=order.state==='refund_pending'?(order.refund_submitted?'Your deposit refund was sent to the payment processor. This page updates after settlement.':'Your deposit refund is queued for processing. Check this page for updates.'):(statusMessages[order.state]||'Check this page for your next step, or select Get help.');
    const actions=(order.online_actions||[]).filter(a=>onlineLabels[a.kind]);
    const balanceSettled=balState==='paid'||(fin.state==='lender_funded'&&fin.funded_amount_cents>=quoteBalanceCents);
    const amountLabel=balanceSettled?'Amount due':depositCredited?(balState==='ach_processing'?'Balance payment processing':'Balance after reservation'):'Due when you reserve';
    const amountValue=money(balanceSettled?0:depositCredited?quoteBalanceCents:quoteDepositCents);
    const paymentNote=balanceSettled?'Payment is verified. No further purchase payment is due.':balState==='ach_processing'?'Your bank payment is processing. Do not pay again.':depositCredited?'Your reservation deposit is credited toward this purchase.':'No payment is collected until you accept your quote and complete checkout.';
    let nextText=statusText,nextAction='',primaryUrl='';
    const setLink=action=>{primaryUrl=action.url;nextAction=`<a class="primary order-primary-action" href="${esc(action.url)}" target="_blank" rel="noopener noreferrer">${esc(onlineLabels[action.kind]||'Continue financing')} ↗</a>`;};
    const signing=actions.find(a=>a.kind==='sign_contract'),title=actions.find(a=>a.kind==='submit_title_documents');
    if(order.state==='requested'){
      nextAction='<button id="save-request-link" class="primary">Save return link</button>';
    }else if(q&&['quoted','checkout_pending'].includes(order.state)&&config?.payments_enabled){
      nextAction='<button id="review-order-quote" class="primary">Review quote and reserve</button>';
    }else if(['deposit_paid','dealer_confirmed'].includes(order.state)){
      if(signing){nextText='Your purchase agreement is ready. Review and sign it securely.';setLink(signing);}
      else if(order.state==='dealer_confirmed'&&pref==='cash'&&!balanceSettled&&config?.payments_enabled&&['unpaid','checkout_open','failed','expired'].includes(balState)){
        nextText='Review your remaining balance and bank payment terms.';nextAction='<button id="review-balance" class="primary">Review balance payment</button>';
      }else if(pref==='partner_financing'&&!balanceSettled){
        nextText=fin.state==='not_requested'?'Financing is your preference. No application has been submitted. '+(fin.application_url?'Continue with the lender when you are ready.':'We are preparing your application link. No action is needed yet.'):(finLabels[fin.state]||'Check your lender status below.');
        if(fin.state==='application_ready')nextText='Your lender application is ready. Open it securely when you are ready. This is not a credit approval.';
        if(fin.application_url&&['not_requested','application_ready','prequalified','conditional_approval'].includes(fin.state))setLink({url:fin.application_url});
      }else if(title){nextText='Your title documents are ready to complete securely.';setLink(title);}
      else nextText=balanceSettled?'Payment is verified. We are preparing delivery. No action is needed yet.':balState==='ach_processing'?'Your bank payment is processing. Do not pay again.':'Your reservation is confirmed. We are preparing your next document or payment step. No action is needed yet.';
    }else if(['dealer_funded','in_transit','delivered','settlement_pending'].includes(order.state)){
      const tracking=actions.find(a=>a.kind==='track_delivery');
      if(title){nextText='Complete your available title documents securely.';setLink(title);}
      else if(order.state==='in_transit'&&(tr.tracking_url||tracking))setLink({kind:'track_delivery',url:tr.tracking_url||tracking.url});
    }
    const otherActions=actions.filter(a=>a.url!==primaryUrl&&!(a.kind==='track_delivery'&&a.url===tr.tracking_url));
    $('order-content').innerHTML=`<p class="eyebrow">YOUR REQUEST</p><h2>${esc(stageNames[order.state]||order.state)}</h2>${v?.model?`<div class="order-vehicle-card">${v.photo?`<img src="${esc(v.photo)}" alt="${esc(v.year+' Tesla '+v.model)}" loading="lazy" referrerpolicy="no-referrer">`:''}<div><strong>${esc((v.year?v.year+' ':'')+'Tesla '+v.model)}</strong><span>${esc([v.trim,v.mileage>0?`${v.mileage.toLocaleString()} mi`:null,v.city&&v.state&&v.state!=='US'?`${v.city}, ${v.state}`:null].filter(Boolean).join(' · '))}</span>${vehSavingsCents>0?`<em class="shortlist-save">Save ${money(vehSavingsCents)} vs. ${money(refCents)} similar listings (${refSample} listings)</em>`:''}</div></div>`:''}<section id="order-next-step" class="order-next-step"><p class="eyebrow">${nextAction?'YOUR NEXT STEP':'CURRENT STATUS'}</p><p id="order-status-message">${esc(nextText)}</p>${nextAction}</section>${hasShippingEstimate?`<section id="provider-shipping-estimate" class="online-steps"><h3>Estimated delivery</h3><div class="line-item"><span>Provider delivery estimate</span><strong>${money(shippingEstimate.customer_estimate_cents)}</strong></div><p>Updated ${esc(new Date(shippingEstimate.observed_at*1000).toLocaleString())}. Final price and delivery timing are confirmed in your written quote.</p><p>No carrier is booked yet.</p></section>`:''}${q&&!['cancelled','refunded','refund_pending','payment_review'].includes(order.state)?`<section id="order-payment-summary" class="order-payment-summary"><div class="line-item"><span>Complete purchase price</span><strong>${money(q.total_cents)}</strong></div><div class="line-item"><span>${amountLabel}</span><strong id="order-amount-due">${amountValue}</strong></div><p>${esc(paymentNote)}</p></section>`:''}${!config?.payments_enabled&&['requested','quoted','checkout_pending'].includes(order.state)?'<p class="notice">Nothing is due now. Reservations open here when checkout is available for this vehicle.</p>':''}${q?`<section id="order-quote" tabindex="-1"><h3>Your written quote</h3><p>Sold and fulfilled by <strong>${esc(q.seller.legal_name)}</strong><br>License ${esc(q.seller.license_number)} · ${esc(q.seller.address)}</p>${vehSavingsCents>0?`<div class="line-item"><span>Peer benchmark (${refSample} listings · ${esc(benchDate(v||{benchmark_date:q.benchmark_date}))})</span><strong>${money(refCents)}</strong></div><div class="line-item savings-line"><span>Vehicle savings vs. benchmark (vehicle only)</span><strong>-${money(vehSavingsCents)}</strong></div>`:''}${[['Vehicle price',money(q.vehicle_price_cents)],['Sales tax',money(q.tax_cents)],['Title and registration',money(q.title_registration_cents)],['Documentation',money(q.documentation_cents)],['Delivery',money(q.delivery_charge_cents)],['Complete purchase price',money(q.total_cents)],[depositCredited?'$250 reservation deposit (paid & credited)':'Reservation deposit (credited toward purchase)','-'+money(quoteDepositCents)],['Original quote balance after deposit',money(quoteBalanceCents)]].map(([label,value])=>`<div class="line-item"><span>${label}</span><strong>${value}</strong></div>`).join('')}<p>Quote expires ${esc(new Date(q.valid_until*1000).toLocaleString())}.</p><ul class="terms-list">${Object.entries(q.terms).map(([label,url])=>`<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label.replaceAll('_',' '))}</a></li>`).join('')}</ul></section>`:''}${q&&['quoted','checkout_pending'].includes(order.state)&&config?.payments_enabled?'<label class="check"><input id="accept-quote" type="checkbox">I accept this complete quote and the linked deposit, return, and warranty terms.</label><button id="pay-deposit" class="primary">Reserve for $250</button>':''}${pref==='partner_financing'||fin.state!=='not_requested'?`<section class="online-steps"><h3>Partner financing status</h3><div class="line-item"><span>Lender status</span><strong>${esc(finLabels[fin.state]||fin.state)}</strong></div>${finProvider?`<div class="line-item"><span>Partner lender</span><strong>${esc(finProvider)}</strong></div>`:''}${fin.approved_amount_cents>0?`<div class="line-item"><span>Approved financing amount</span><strong>${money(fin.approved_amount_cents)}</strong></div>`:''}${fin.funded_amount_cents>0?`<div class="line-item"><span>Funded proceeds to selling dealer</span><strong>${money(fin.funded_amount_cents)}</strong></div>`:''}${fin.stipulations?.length?`<div class="line-item"><span>Required stipulations</span><strong>${esc(fin.stipulations.join(', '))}</strong></div>`:''}${fin.application_url&&fin.application_url!==primaryUrl?`<a class="online-step" href="${esc(fin.application_url)}" target="_blank" rel="noopener noreferrer">Open partner lender application ↗</a>`:''}<p id="order-payment-preference-note">${fin.state==='not_requested'?'Selecting financing is a preference, not a credit application. No application has been submitted. '+(fin.application_url?'Open the lender application when you are ready.':'We will show the application here when it is available.'):fin.state==='application_ready'?'Your application link is ready. No application has been submitted. This is not a credit approval.':'Your financing status comes from the lender.'}</p><p>Prequalification and conditional approval are not funded proceeds. Vehicle release requires verified lender funding to the selling dealer.</p></section>`:''}${q&&order.state==='dealer_confirmed'&&pref==='cash'?`<section id="order-balance" class="online-steps" tabindex="-1"><h3>Balance payment</h3><div class="line-item"><span>Complete purchase price</span><strong>${money(q.total_cents)}</strong></div><div class="line-item"><span>Less $250 reservation credit</span><strong>-${money(quoteDepositCents)}</strong></div><div class="line-item"><span>Remaining balance due</span><strong>${money(balanceSettled?0:quoteBalanceCents)}</strong></div><div class="line-item"><span>Balance status</span><strong>${esc(balLabels[balState]||balState)}</strong></div>${config?.payments_enabled&&['unpaid','checkout_open','failed','expired'].includes(balState)?'<label class="check"><input id="accept-balance" type="checkbox">I authorize ACH bank payment for the remaining balance under the accepted purchase terms.</label><button id="pay-balance" class="primary">Pay remaining balance via ACH</button>':''}<p>Bank account linking initiates an ACH Direct Debit (1–4 business days to settle). Vehicle release requires settled funds.</p></section>`:''}${tr.state!=='unquoted'?`<section class="online-steps"><h3>Delivery &amp; carrier tracking</h3><div class="line-item"><span>Transport status</span><strong>${esc(trLabels[tr.state]||tr.state)}</strong></div>${trProvider?`<div class="line-item"><span>Carrier</span><strong>${esc(trProvider)}</strong></div>`:''}${Number.isInteger(tr.rate_cents)?`<div class="line-item"><span>Carrier rate</span><strong>${money(tr.rate_cents)}</strong></div>`:''}${tr.quote_expires_at?`<div class="line-item"><span>Rate quote expires</span><strong>${esc(new Date(tr.quote_expires_at*1000).toLocaleString())}</strong></div>`:''}${tr.pickup_window_start&&tr.pickup_window_end?`<div class="line-item"><span>Pickup window</span><strong>${esc(new Date(tr.pickup_window_start*1000).toLocaleDateString())} – ${esc(new Date(tr.pickup_window_end*1000).toLocaleDateString())}</strong></div>`:''}${tr.delivery_window_start&&tr.delivery_window_end?`<div class="line-item"><span>Estimated delivery window</span><strong>${esc(new Date(tr.delivery_window_start*1000).toLocaleDateString())} – ${esc(new Date(tr.delivery_window_end*1000).toLocaleDateString())}</strong></div>`:''}${tr.bol_reference?`<div class="line-item"><span>Bill of lading (BOL)</span><strong>${esc(tr.bol_reference)}</strong></div>`:''}${tr.tracking_url&&tr.tracking_url!==primaryUrl?`<a class="online-step" href="${esc(tr.tracking_url)}" target="_blank" rel="noopener noreferrer">Open live carrier tracking ↗</a>`:''}<p>${tr.state==='quoted'?'A carrier rate quote is an estimate only; vehicle dispatch requires carrier acceptance and an electronic bill of lading.':'Carrier dispatch and delivery milestones are verified with the selling dealer and carrier.'}</p></section>`:''}${otherActions.length?`<section class="online-steps"><h3>Other purchase steps</h3>${otherActions.map(a=>`<a class="online-step" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(onlineLabels[a.kind])} ↗</a>`).join('')}<p>Your purchase stays tracked here. Required signing or bank services open securely. Completion requires verification.</p></section>`:''}<details class="payment-settings"><summary>Payment preference</summary><div class="line-item"><span>Payment path</span><strong>${pref==='partner_financing'?'Financing':'Pay in full'}</strong></div>${canChangePref?`<label>Update payment preference<select id="order-payment-pref"><option value="cash" ${pref==='cash'?'selected':''}>Pay in full</option><option value="partner_financing" ${pref==='partner_financing'?'selected':''}>Financing (subject to approval)</option></select></label>`:''}</details><div id="embedded-payment" class="embedded-payment"></div><div class="form-row"><button id="refresh-order" class="secondary">Refresh status</button>${['requested','quoted','quote_expired','checkout_pending','deposit_processing','deposit_paid'].includes(order.state)?'<button id="cancel-order" class="secondary">Cancel request</button>':''}</div><button id="report-issue" class="text-button">${order.state==='quote_expired'?'Request updated quote':'Get help'}</button><div id="issue-form" hidden><label>Issue type<select id="issue-kind"><option value="other">Purchase question</option><option value="return">Return request</option><option value="warranty">Warranty question</option><option value="transport_damage">Transport damage</option><option value="title_delay">Title processing</option></select></label><label>Describe the issue<textarea id="issue-description" minlength="5" maxlength="1000" rows="4"></textarea></label><button id="send-issue" class="secondary">Submit for review</button></div><details id="order-access" class="order-access"><summary>Return link and request details</summary><p>VIN ${esc(order.vin)}</p><p class="price-label">Request ${esc(order.id)}</p><div class="form-row"><button id="copy-access" class="secondary">Copy private return link</button><button id="save-access" class="text-button">Save return link</button><button id="switch-order" class="text-button">Open another request</button></div><button id="delete-request" class="text-button">Request personal-data deletion</button></details><p id="order-error" class="form-error" role="alert"></p>`;
    $('save-request-link')?.addEventListener('click',()=>saveReturnPage(access));
    $('review-order-quote')?.addEventListener('click',()=>{$('order-quote').scrollIntoView({behavior:'smooth',block:'start'});$('order-quote').focus({preventScroll:true});});
    $('review-balance')?.addEventListener('click',()=>{$('order-balance').scrollIntoView({behavior:'smooth',block:'start'});$('order-balance').focus({preventScroll:true});});
    if(accessPersistenceFailed){
      const warning=document.createElement('p');warning.className='notice';warning.id='access-warning';warning.textContent='Your browser cannot save request access. Save your private return link before leaving this page.';$('order-next-step').after(warning);$('order-access').open=true;
    }
    const support=document.createElement('section');support.className='online-steps';support.innerHTML='<h3>Your support requests</h3><p id="support-receipt" role="status"></p><div id="support-case-list">Loading support history…</div>';$('issue-form').after(support);loadSupportCases(access);
    const returnNote=document.createElement('p');returnNote.className='price-label';returnNote.textContent='Keep your return link private. It opens this request without entering a code.';$('save-access').closest('.form-row').after(returnNote);
    const fallback=document.createElement('div');fallback.id='return-link-fallback';fallback.hidden=true;fallback.innerHTML='<label>Your private return link<input id="private-return-link" readonly></label>';$('save-access').closest('.form-row').after(fallback);
    $('save-access').addEventListener('click',()=>saveReturnPage(access));
    $('copy-access').addEventListener('click',async()=>{
      const link=privateReturnLink(access);
      try{await navigator.clipboard.writeText(link);notify('Private return link copied. Keep it private.');}
      catch{if(fallback.isConnected&&currentAccess()?.id===access.id){fallback.hidden=false;$('private-return-link').value=link;$('private-return-link').focus();$('private-return-link').select();notify('Select and copy your private return link.');}}
    });
    $('switch-order')?.addEventListener('click',()=>{destroyCheckout();stopOrderPoll();renderRecoverOrder();});
    $('refresh-order').addEventListener('click',()=>{$('order-error').textContent='';refreshOrder();});
    $('order-payment-pref')?.addEventListener('change',async e=>{
      const select=e.target;if(select.disabled)return;select.disabled=true;
      $('order-error').textContent='';
      try{const updated=await api(`orders/${access.id}/payment-preference`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({payment_preference:e.target.value})});if(isCurrentView()){showOrder(updated);notify('Payment preference updated.');}}catch(err){if(isCurrentView())$('order-error').textContent=err.message;}finally{if(select.isConnected)select.disabled=false;}
    });
    $('report-issue').addEventListener('click',()=>{$('issue-form').hidden=!$('issue-form').hidden;if(!$('issue-form').hidden){if(order.state==='quote_expired'&&!$('issue-description').value)$('issue-description').value='Please update the expired quote for this request.';$('issue-description').focus();}});
    $('send-issue').addEventListener('click',async()=>{
      const button=$('send-issue');if(button.disabled)return;
      const errorNode=$('order-error'),issueForm=$('issue-form'),descriptionNode=$('issue-description'),receiptNode=$('support-receipt');
      errorNode.textContent='';const description=descriptionNode.value.trim();
      if(description.length<5){errorNode.textContent='Describe the issue in at least five characters.';descriptionNode.focus();return;}
      button.disabled=true;
      try{
        const body=JSON.stringify({kind:$('issue-kind').value,description});
        const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(access.id+'\n'+body));
        const key='support-'+Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');
        const receipt=await api(`orders/${access.id}/cases`,{method:'POST',headers:{Authorization:'Bearer '+access.token,'Idempotency-Key':key},body});
        issueForm.hidden=true;descriptionNode.value='';receiptNode.textContent=`Support request recorded. Reference: ${receipt.id}`;
        if(issueForm.isConnected&&currentAccess()?.id===access.id){loadSupportCases(access);notify('Your support request was recorded. Keep its reference below.');}
      }catch(e){errorNode.textContent=e.message;}finally{if(button.isConnected)button.disabled=false;}
    });
    $('cancel-order')?.addEventListener('click',async()=>{$('order-error').textContent='';try{const result=await api(`orders/${access.id}/cancel`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({reason:'Customer requested cancellation'})});if(isCurrentView()){if(result.id)showOrder(result);else{notify(result.message||'Your cancellation request needs review.');refreshOrder();}}}catch(e){if(isCurrentView())$('order-error').textContent=e.message;}});
    $('delete-request').addEventListener('click',async()=>{$('order-error').textContent='';try{await api(`orders/${access.id}/privacy`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:'{}'});notify('Deletion request recorded for review against transaction retention requirements.');}catch(e){$('order-error').textContent=e.message;}});
    $('accept-quote')?.addEventListener('change',()=>{$('order-error').textContent='';});
    $('accept-balance')?.addEventListener('change',()=>{$('order-error').textContent='';});
    const mountStripeResult=async result=>{
      if(!isCurrentView())return;
      if(result.mode==='embedded_page'){
        await loadStripe();if(!isCurrentView())return;destroyCheckout();
        const provider=window.Stripe(result.publishable_key,{stripeAccount:result.account});
        const checkout=await provider.createEmbeddedCheckoutPage({fetchClientSecret:async()=>result.client_secret,onComplete:async()=>{if(!isCurrentView())return;destroyCheckout();await refreshOrder();if(currentAccess()?.id===access.id)notify('Payment submitted. Your purchase updates after payment verification.');}});
        if(!isCurrentView()){checkout.destroy();return;}embeddedCheckout=checkout;
        embeddedCheckout.mount('#embedded-payment');$('embedded-payment').scrollIntoView({behavior:'smooth',block:'start'});
      }else{const target=new URL(result.url);if(target.protocol!=='https:'||target.hostname!=='checkout.stripe.com')throw new Error('Unexpected payment destination');location.assign(target.href);}
    };
    $('pay-deposit')?.addEventListener('click',async()=>{
      $('order-error').textContent='';
      if(!$('accept-quote').checked){$('order-error').textContent='Review and accept the quote and linked terms first.';return;}
      $('pay-deposit').disabled=true;
      try{const result=await api(`orders/${access.id}/checkout`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({quote_version:order.quote_version,terms_accepted:true})});await mountStripeResult(result);}catch(e){if(isCurrentView()){$('order-error').textContent=e.message;$('pay-deposit').disabled=false;}}
    });
    $('pay-balance')?.addEventListener('click',async()=>{
      $('order-error').textContent='';
      if(!$('accept-balance').checked){$('order-error').textContent='Authorize the ACH balance payment and accepted purchase terms first.';return;}
      $('pay-balance').disabled=true;
      try{const result=await api(`orders/${access.id}/balance-checkout`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({quote_version:order.quote_version,terms_accepted:true})});await mountStripeResult(result);}catch(e){if(isCurrentView()){$('order-error').textContent=e.message;$('pay-balance').disabled=false;}}
    });
    open('order-dialog');
    if(hasShippingEstimate){const panel=$('provider-shipping-estimate');shippingEstimateTimer=setTimeout(()=>{if(panel.isConnected)panel.remove();},Math.max(0,shippingEstimate.cache_expires_at*1000-Date.now()));}
    if(access&&(['requested','quoted','checkout_pending','deposit_processing','deposit_paid','dealer_confirmed','dealer_funded','in_transit','refund_pending'].includes(order.state)||balState==='ach_processing')){
      orderPollTimer=setInterval(async()=>{
        if(!$('order-dialog').open||embeddedCheckout||!$('issue-form')?.hidden)return;
        try{
          const latest=await api('orders/'+encodeURIComponent(access.id),{headers:{Authorization:'Bearer '+access.token}});
          if(isCurrentView()&&JSON.stringify(latest)!==lastOrderSnapshot)showOrder(latest);
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
    $('photo-expand').hidden=!galleryPhotos.length;
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
  function paintFullPhoto(){const photo=galleryPhotos[galleryIndex];if(!photo)return;$('full-photo-error').hidden=true;$('full-photo').hidden=false;$('full-photo').src=photo.url;$('full-photo').alt=photo.title;$('full-caption').textContent=`${galleryIndex+1} / ${galleryPhotos.length} · ${photo.title}`;}
  $('full-photo').addEventListener('error',()=>{$('full-photo').hidden=true;$('full-photo-error').hidden=false;});
  $('retry-full-photo').addEventListener('click',paintFullPhoto);
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
    compareSelected=new Set([...compareSelected].filter(vin=>favorites.some(x=>x.vin===vin)));
    if(!compareSelected.size&&favorites.length<=3)compareSelected=new Set(favorites.map(x=>x.vin));
    $('shortlist-content').innerHTML=favorites.length?favorites.map(x=>`<div class="shortlist-row"><button class="shortlist-car" data-shortlist-open="${x.vin}">${image(x)}<span><strong>${x.year} Tesla ${esc(x.model)}</strong><small>${esc(x.trim)} · ${x.mileage.toLocaleString()} mi</small><b>${dollars(x.display_price)}${saving(x)>0?` <em class="shortlist-save">Save ${dollars(saving(x))} vs. ${dollars(x.reference_price)} benchmark</em>`:''}</b></span><span>→</span></button><label class="compare-choice"><input type="checkbox" data-compare-select="${x.vin}" ${compareSelected.has(x.vin)?'checked':''} aria-label="Compare ${esc(x.year+' Tesla '+x.model+' stock '+x.stock_number)}">Compare</label></div>`).join(''):'<div class="shortlist-empty">♡<h3>Start with a favorite.</h3><p>Tap a heart while you explore. Your shortlist will be right here.</p></div>';
    const unavailable=[...saved].filter(vin=>!byVIN.has(vin));
    if(unavailable.length){
      if(!favorites.length)$('shortlist-content').textContent='';
      $('shortlist-content').insertAdjacentHTML('beforeend',unavailable.map(vin=>`<div class="shortlist-unavailable"><span><strong>Listing no longer available</strong><small>VIN ${esc(vin)}</small></span><button class="secondary" data-remove-unavailable="${esc(vin)}" aria-label="Remove unavailable saved vehicle ${esc(vin)}">Remove</button></div>`).join(''));
      $('shortlist-content').querySelectorAll('[data-remove-unavailable]').forEach(b=>b.addEventListener('click',()=>{toggleSave(b.dataset.removeUnavailable);showShortlist();}));
    }
    const updateCompare=()=>{const count=compareSelected.size;$('compare-saved').hidden=favorites.length<2;$('compare-saved').disabled=count<2||count>3;$('compare-saved').textContent=count>=2?`Compare ${count} vehicles`:'Choose vehicles to compare';$('compare-message').textContent=favorites.length>=2?`Choose 2 or 3 vehicles to compare. ${count} of 3 selected.`:'';$('shortlist-content').querySelectorAll('[data-compare-select]').forEach(input=>input.disabled=count>=3&&!input.checked);};
    $('shortlist-content').querySelectorAll('[data-compare-select]').forEach(input=>input.addEventListener('change',()=>{if(input.checked&&compareSelected.size<3)compareSelected.add(input.dataset.compareSelect);else{compareSelected.delete(input.dataset.compareSelect);input.checked=false;}updateCompare();}));updateCompare();
    $('shortlist-content').querySelectorAll('[data-shortlist-open]').forEach(b=>b.addEventListener('click',()=>{close('saved-dialog');showVehicle(b.dataset.shortlistOpen);}));attachImageFallbacks($('shortlist-content'));open('saved-dialog');
  }
  function comparisonStatus(x){
    if(!x.reference_price||x.reference_sample<5)return 'Comparison unavailable';
    const difference=Math.round(x.display_price-x.reference_price);
    return difference>0?`${dollars(difference)} above the ${dollars(x.reference_price)} peer reference`:`At the ${dollars(x.reference_price)} peer reference`;
  }
  $('compare-saved').addEventListener('click',()=>{
    const xs=items.filter(x=>saved.has(x.vin)&&compareSelected.has(x.vin));if(xs.length<2||xs.length>3)return;
    $('compare-content').innerHTML=`<div class="comparison-grid">${xs.map(x=>`<article>${image(x)}<h3>${x.year} ${esc(x.model)}</h3><div class="price">${dollars(x.display_price)}</div>${saving(x)>0?`<p class="compare-save">Save ${dollars(saving(x))} vs. ${dollars(x.reference_price)} (${x.reference_sample} peers · ${esc(benchDate(x))})</p>`:`<p class="compare-save-muted">${esc(comparisonStatus(x))}</p>`}<p>${esc(x.trim)}</p><p>${x.mileage.toLocaleString()} miles</p><p>${esc(x.city)}, ${esc(x.state)}</p><button class="primary" data-compare-open="${x.vin}">Explore this Tesla</button></article>`).join('')}</div>`;
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
  function toggleFilters(expanded){$('filters').classList.toggle('expanded',expanded);$('mobile-filters').setAttribute('aria-expanded',String(expanded));}
  $('mobile-filters').addEventListener('click',()=>toggleFilters(!$('filters').classList.contains('expanded')));
  $('filters-done').addEventListener('click',()=>{toggleFilters(false);$('inventory').scrollIntoView({block:'start'});$('mobile-filters').focus({preventScroll:true});});
  $('zip-label').textContent=zip||'Set ZIP';$('zip-button').addEventListener('click',()=>{$('zip-input').value=zip;open('zip-dialog');});
  async function resolveZip(value){
    const lookup=++zipLookupVersion;
    if(!zipDataset){
      if(!zipDatasetPromise)zipDatasetPromise=fetch(new URL('data/us_zip_centers.json',rootURL)).then(async r=>{if(!r.ok)throw new Error('Location data could not load. Please retry.');return (await r.json()).zips;}).catch(error=>{zipDatasetPromise=null;throw error;});
      zipDataset=await zipDatasetPromise;
    }
    if(lookup!==zipLookupVersion)return false;
    if(!zipDataset[value])throw new Error('ZIP not found in our location data. Try a nearby ZIP.');
    zip=value;zipPoint=zipDataset[value];$('zip-label').textContent=zip;
    try{localStorage.setItem('marketplace_zip',zip);}catch{}
    $('sort').querySelector('[value=distance]').disabled=false;$('sort').value='distance';applyFilters();
    if(activeVIN&&$('vehicle-dialog').open&&byVIN.has(activeVIN)){const text=$('vehicle-content').querySelector('.summary-distance');if(text)text.textContent=nearbyLabel(byVIN.get(activeVIN))||'City distance is unavailable for this vehicle.';if($('tab-pricing').getAttribute('aria-selected')==='true')vehicleTab('pricing');}
    return true;
  }
  $('zip-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;$('zip-error').textContent='';try{await resolveZip($('zip-input').value);try{localStorage.setItem('marketplace_zip',zip);}catch{}close('zip-dialog');}catch(error){$('zip-error').textContent=error.message;}finally{button.disabled=false;}});
  if(zip){const initialZip=zip;resolveZip(initialZip).catch(()=>{if(zip===initialZip){zip='';zipPoint=null;$('zip-label').textContent='Set ZIP';}});}
  $('privacy-button').addEventListener('click',()=>open('privacy-dialog'));
  $('order-button').addEventListener('click',()=>{if(apiReady||currentAccess()){refreshOrder();return;}try{const draft=JSON.parse(localStorage.getItem('marketplace_deal')||'null');if(draft&&byVIN.has(draft.vin)){buildDeal(draft.vin);return;}}catch{}notify('Choose a Tesla and select Review price to start.');});updateSaved();
  function purchaseAvailability(){
    const paymentsOn=!!(apiReady&&config?.payments_enabled);
    $('purchase-availability').hidden=paymentsOn;
    $('purchase-availability').textContent=apiReady?'Final price requests are open. Reservations become available after seller and payment approval.':'Browse Teslas and save your estimated price while requests are being connected.';
    $('business-status').textContent=paymentsOn?'Find your Tesla · Estimate your total · $250 refundable reservation after quote approval':(apiReady?'Find your Tesla · Estimate your total · Monthly payment calculator · Request a dealer quote':'15,000+ Used Teslas Nationwide · Estimate Your Total · Monthly Payment Calculator');
    $('order-button').hidden=false;$('order-button').textContent=apiReady?'Track my request':'Saved price';
    $('hero-description').textContent='Compare Teslas, review your total, and request your final price online.';
    if(items.length)applyFilters(false);
    const button=$('vehicle-request');if(button){button.disabled=false;button.textContent='Review price';}
  }
  purchaseAvailability();
  api('config').then(c=>{config=c;apiReady=!!c.requests_enabled;purchaseAvailability();}).catch(()=>{apiReady=false;purchaseAvailability();}).finally(()=>{if(restoredPrivateLink)refreshOrder();else if(privateLinkError){renderRecoverOrder(privateLinkError);open('order-dialog');}});
  fetch(new URL('inventory.json?v='+(document.querySelector('meta[name="volts-catalog-version"]')?.content||new URL(scriptURL).searchParams.get('v')||'current'),rootURL)).then(r=>{if(!r.ok)throw new Error('Inventory unavailable');return r.json();}).then(payload=>{
    mediaVersion=payload.meta?.media_version||'';snapshotDate=payload.meta?.built_at||'';
    items=payload.items.filter(x=>!x.expires_at||new Date(x.expires_at).getTime()>Date.now());byVIN=new Map(items.map(x=>[x.vin,x]));
    const reservableCount=items.filter(x=>x.reservable).length;
    if($('reservable-label'))$('reservable-label').textContent=reservableCount?`Reservable now (${reservableCount} seller-approved)`:'Reservable now (0 seller-approved · browsing discovery catalog)';
    if($('reservable-only'))$('reservable-only').disabled=!reservableCount;
    if($('reservable-only'))$('reservable-only').closest('label').hidden=!reservableCount;
    document.querySelector('[data-discover=finds]').hidden=!items.some(x=>saving(x)>=500);
    for(const option of $('hardware').options){if(option.value){const count=items.filter(x=>x.hardware===option.value).length;option.disabled=!count;option.textContent=count?`${option.value} · ${count} verified`:`${option.value} — evidence needed`;}}
    $('hardware').closest('label').hidden=!items.some(x=>x.hardware);
    options('model',[...new Set(items.map(x=>x.model))].sort());options('year',[...new Set(items.map(x=>x.year))].sort((a,b)=>b-a));options('state',[...new Set(items.map(x=>x.state))].filter(x=>x!=='US').sort());
    $('snapshot-status').textContent='Your next favorite is in here.';
    const preset=document.body.dataset.preset;if(preset){for(const part of preset.split(';')){const [key,value]=part.split(':');if(key==='discover'){discovery=value;document.querySelectorAll('[data-discover]').forEach(b=>b.classList.toggle('active',b.dataset.discover===value));}else if($(key))$(key).value=value;}}
    const q=new URLSearchParams(location.search).get('q');if(q&&$('search'))$('search').value=q;
    applyFilters();
    const vin=new URLSearchParams(location.search).get('vin')||document.body.dataset.initialVin;if(vin&&!restoredPrivateLink&&!privateLinkError)showVehicle(vin);
    // Redirect parameters never prove payment. Only an authenticated server order does.
    if(new URLSearchParams(location.search).has('checkout')&&currentAccess())refreshOrder();
  }).catch(()=>{$('result-count').textContent='Inventory is temporarily unavailable';$('snapshot-status').textContent='Please try again later. No request or payment was created.';});
})();
