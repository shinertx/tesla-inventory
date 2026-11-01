'use strict';
(() => {
  const scriptURL = document.currentScript.src;
  const rootURL = new URL('../', scriptURL);
  const apiURL = new URL('api/', rootURL);
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
    const response=await fetch(new URL(path,apiURL),{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
    let payload;try{payload=await response.json();}catch{throw new Error('The request service is unavailable. No payment was collected.');}
    if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'Please check your details and try again.');
    return payload;
  }
  function currentAccess(){try{return JSON.parse(sessionStorage.getItem('marketplace_order') || 'null');}catch{return null;}}
  function updateSaved(){
    try{localStorage.setItem('marketplace_saved',JSON.stringify([...saved]));}catch{}
    $('saved-count').textContent=saved.size;
  }
  function toggleSave(vin){const adding=!saved.has(vin);adding?saved.add(vin):saved.delete(vin);updateSaved();applyFilters();if(adding){$('saved-button').classList.remove('saved-pop');void $('saved-button').offsetWidth;$('saved-button').classList.add('saved-pop');notify('♥ Added to your shortlist');}}
  function options(id,values){const select=$(id);values.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;select.append(option);});}
  function image(item,cls='',priority=false){
    return item.photo?`<img class="${cls}" src="${esc(item.photo)}" alt="${esc(item.year+' Tesla '+item.model)}" loading="${priority?'eager':'lazy'}" ${priority?'fetchpriority="high"':''} decoding="async" referrerpolicy="no-referrer">`:`<span class="photo-fallback">${esc(item.model)}</span>`;
  }
  function attachImageFallbacks(container){container.querySelectorAll('img').forEach(img=>{
    const ready=()=>img.classList.add('loaded');if(img.complete&&img.naturalWidth)ready();img.addEventListener('load',ready,{once:true});
    img.addEventListener('error',()=>{const card=img.closest('.card');if(card&&$('photos-only').checked){failedPhotos.add(card.dataset.vin);queueMicrotask(applyFilters);return;}const fallback=document.createElement('span');fallback.className='photo-fallback';fallback.textContent='Photo coming soon';img.replaceWith(fallback);},{once:true});
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
  function rank(x){return Math.min(saving(x)/Math.max(x.reference_price||1,1),.15)*20+Math.min(x.photo_count||0,20)/20+Math.max(0,(x.year-2014)/14)+(x.mileage>0?Math.max(0,1-x.mileage/150000):.2);}
  function varied(rows){
    const buckets=new Map();rows.forEach(x=>{if(!buckets.has(x.model))buckets.set(x.model,[]);buckets.get(x.model).push(x);});
    const result=[];while(buckets.size){for(const [key,list] of [...buckets]){result.push(list.shift());if(!list.length)buckets.delete(key);}}return result;
  }
  function applyFilters(){
    const search=$('search').value.trim().toLowerCase();
    filtered=items.filter(x=>(!$('photos-only').checked||(!!x.photo&&!failedPhotos.has(x.vin)))&&(discovery!=='finds'||saving(x)>=500)&&(!$('model').value||x.model===$('model').value)&&(!$('year').value||x.year===Number($('year').value))&&(!$('state').value||x.state===$('state').value)&&(!$('drivetrain').value||x.drivetrain===$('drivetrain').value)&&(!$('trim-family').value||x.trim_family===$('trim-family').value)&&(!$('factory').value||x.factory===$('factory').value)&&(!$('hardware').value||x.hardware===$('hardware').value)&&x.display_price<=Number($('price').value)&&x.mileage<=Number($('mileage').value)&&($('mileage').value==='999999'||x.mileage>0)&&(!$('saved-only').checked||saved.has(x.vin))&&(!$('reservable-only')?.checked||!!x.reservable)&&(!search||[x.vin,x.model,x.trim,x.stock_number,x.city,x.state,x.drivetrain,x.factory].join(' ').toLowerCase().includes(search)));
    const sort=$('sort').value;
    filtered.sort((a,b)=>sort==='recommended'?rank(b)-rank(a)||a.vin.localeCompare(b.vin):sort==='savings'?saving(b)-saving(a)||rank(b)-rank(a)||a.display_price-b.display_price||a.vin.localeCompare(b.vin):sort==='distance'?(distance(a)??Infinity)-(distance(b)??Infinity)||rank(b)-rank(a):sort==='price-desc'?b.display_price-a.display_price:sort==='mileage'?a.mileage-b.mileage:sort==='year'?b.year-a.year:a.display_price-b.display_price);
    if(sort==='recommended')filtered=varied(filtered);
    $('snapshot-status').textContent=zipPoint?`Near ${zip} · distances are approximate, straight-line estimates`:'Explore photos, compare the details, and save your favorites.';
    limit=36;render();
  }
  function render(){
    $('result-count').textContent=`${filtered.length.toLocaleString()} Tesla listings`;
    $('cards').innerHTML=filtered.slice(0,limit).map((x,i)=>`<article class="card" data-vin="${x.vin}"><div class="photo-wrap">${image(x,'',i<6)}${(x.photo_count||x.photos?.length)>1?`<span class="photo-count">▧ ${x.photo_count||x.photos.length} photos</span>`:''}${saving(x)>=500?`<span class="find-badge">Save ${dollars(saving(x))}</span>`:''}<button class="save" data-save="${x.vin}" aria-label="${saved.has(x.vin)?'Remove saved':'Save'} ${esc(x.year+' '+x.model)}" aria-pressed="${saved.has(x.vin)}">${saved.has(x.vin)?'♥':'♡'}</button></div><a class="card-main" href="?vin=${x.vin}" data-open="${x.vin}"><h3>${x.year} Tesla ${esc(x.model)}</h3><div class="trim">${esc(x.trim)}</div><div class="card-specs"><span>${odometer(x)}</span>${x.drivetrain?`<span title="${esc(x.drivetrain_basis)}">${esc(x.drivetrain)}${x.drivetrain_basis==='VIN-derived'?' · VIN':''}</span>`:''}${x.hardware?`<span>${esc(x.hardware)} verified</span>`:''}</div><div class="card-price"><strong class="price">${dollars(x.display_price)}</strong><span>est.</span>${saving(x)>0?`<span class="price-win">Save ${dollars(saving(x))}</span>`:''}</div></a>${saving(x)>0?`<details class="card-benchmark"><summary>Vs. ${dollars(x.reference_price)} benchmark · ${x.reference_sample} peers · ${esc(benchDate(x))}</summary><p>Mileage-adjusted comparison across ${x.reference_sample} peer Tesla asking prices (${esc(benchDate(x))} snapshot). Vehicle price only; tax, title, and delivery are quoted separately. Peer asking prices are not appraisals or guaranteed resale values.</p></details>`:''}<div class="card-footer"><span>${esc(x.city||'Vehicle location')}${x.state!=='US'?', '+esc(x.state):''}${nearbyLabel(x)?`<small>${nearbyLabel(x)}</small>`:''}</span><span class="reserve-note">Build your deal →</span></div></article>`).join('');
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
    $('vehicle-content').innerHTML=`<button class="close" data-close="vehicle-dialog" aria-label="Close vehicle details">×</button><div class="vehicle-top"><div class="vehicle-media"><div class="vehicle-image"><div id="gallery-stage">${image(x,'',true)}</div><button id="gallery-prev" class="gallery-arrow left" aria-label="Previous vehicle photo">‹</button><button id="gallery-next" class="gallery-arrow right" aria-label="Next vehicle photo">›</button><button id="photo-expand" class="photo-expand">⤢ View photos <span id="gallery-count"></span></button></div><div id="gallery-thumbs" class="gallery-thumbs"></div><div class="gallery-status"><span id="gallery-status" role="status"></span><button id="gallery-retry" class="secondary" hidden>Retry photos</button></div></div><div class="vehicle-summary"><p class="eyebrow">YOUR NEXT TESLA?</p><h2>${x.year} Tesla ${esc(x.model)}</h2><p class="summary-trim">${esc(x.trim)}</p><div class="summary-facts"><span><small>Odometer</small><strong>${odometer(x)}</strong></span>${x.drivetrain?`<span><small>Drive · ${esc(x.drivetrain_basis)}</small><strong>${esc(x.drivetrain)}</strong></span>`:''}${x.factory?`<span><small>Factory · VIN-derived</small><strong>${esc(x.factory)}</strong></span>`:''}<span><small>Vehicle location</small><strong>${esc(x.city||x.state)}${x.city&&x.state!== 'US'?', '+esc(x.state):''}</strong></span></div><div class="summary-price"><div class="summary-price-row"><strong class="price">${dollars(x.display_price)}</strong>${saving(x)>0?`<span class="summary-savings-pill">Save ${dollars(saving(x))}</span>`:''}</div><span>Estimated vehicle price</span>${x.reference_price&&x.reference_sample>=5?`<details class="benchmark-details"><summary>${saving(x)>0?`${dollars(saving(x))} below ${dollars(x.reference_price)} peer benchmark`:`Peer benchmark ${dollars(x.reference_price)}`} (${x.reference_sample} listings · ${esc(benchDate(x))})</summary><p>Mileage-adjusted comparison across ${x.reference_sample} peer Tesla asking prices (${esc(benchDate(x))} snapshot). Vehicle savings apply to the vehicle price only; delivery, tax, and title are quoted separately. Peer asking prices are not appraisals or guaranteed resale values.</p></details>`:''}</div><p class="price-label">Tax, title, and delivery are quoted separately.</p><p class="summary-distance">${nearbyLabel(x)||'Set your ZIP to explore nearby vehicles.'}</p><div class="summary-actions"><button id="vehicle-request" class="primary">Build your deal</button><button id="vehicle-save" class="secondary">${saved.has(x.vin)?'♥ Saved to your shortlist':'♡ Save to your shortlist'}</button></div><p class="price-label">Choose your delivery ZIP. Review the complete quote before your $250 reservation.</p></div></div><div class="vehicle-body"><div class="vehicle-tabs" role="tablist" aria-label="Vehicle information"><button class="tab" role="tab" id="tab-details" aria-controls="vehicle-panel" aria-selected="true" data-tab="details">Vehicle details</button><button class="tab" role="tab" id="tab-pricing" aria-controls="vehicle-panel" aria-selected="false" data-tab="pricing">Price and delivery</button><button class="tab" role="tab" id="tab-process" aria-controls="vehicle-panel" aria-selected="false" data-tab="process">Purchase steps</button></div><div id="vehicle-panel" role="tabpanel" aria-labelledby="tab-details"></div></div>`;
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
    if(tab==='details')$('vehicle-panel').innerHTML=`<div class="spec-grid">${spec('Listing tier',x.reservable?'Seller-approved reservable stock':'Discovery listing · seller confirmation required')}${spec('Vehicle identification number',x.vin)}${spec('Stock number',x.stock_number)}${spec('Advertised trim',x.trim)}${spec('Model year',x.year)}${x.drivetrain?spec('Drivetrain · '+x.drivetrain_basis,x.drivetrain):''}${x.factory?spec('Build factory · VIN-derived',x.factory):''}${x.hardware?spec('AI computer · evidence verified',x.hardware):''}</div><details class="verification-details"><summary>Checks before reservation</summary><p>The selling dealer must confirm vehicle condition, title, equipment, and availability before payment.</p><div class="spec-grid">${spec('Title history',x.reservable?'Clean title verified':'Not yet verified')}${spec('AI computer',x.hardware||'Vehicle-specific evidence required')}${spec('FSD software','Vehicle screen and transfer terms required')}${spec('Inspection','No inspection report on file')}${spec('Availability',x.reservable?'Seller hold active':'Seller confirmation required')}</div><p>VIN-derived drive and factory labels are inferences. Your final quote identifies the licensed seller and written purchase terms.</p></details>`;
    if(tab==='pricing')$('vehicle-panel').innerHTML=`${saving(x)>0?`<div class="line-item"><span>Peer benchmark (${x.reference_sample} listings · ${esc(benchDate(x))})</span><strong>${dollars(x.reference_price)}</strong></div><div class="line-item savings-line"><span>Your vehicle savings vs. benchmark (vehicle only)</span><strong>-${dollars(saving(x))}</strong></div>`:''}<div class="line-item"><span>Estimated vehicle price</span><strong>${dollars(x.display_price)}</strong></div><div class="line-item"><span>Sales tax and registration (separate)</span><strong>Quote required</strong></div><div class="line-item"><span>Delivery to ${zip?esc(zip):'your ZIP'} (separate)</span><strong>Carrier quote required</strong></div>${nearbyLabel(x)?`<p>${nearbyLabel(x)}. Straight-line estimate between your ZIP center and the vehicle city; driving routes and shipping costs differ.</p>`:''}<div class="notice">Your final quote identifies the licensed seller, complete price, inspection evidence, and written purchase terms. No trade-ins. Any financing requires separate approval and written terms.</div>${x.reference_price?`<p>The mileage-adjusted asking-price comparison is ${dollars(x.reference_price)}, using ${x.reference_sample} peer listings (${esc(benchDate(x))} snapshot). This estimate is not an appraisal or a completed-sale value.</p>`:''}`;
    if(tab==='process')$('vehicle-panel').innerHTML=stages.filter(s=>s!=='checkout_pending').map(s=>`<div class="order-stage">${esc(stageNames[s])}</div>`).join('')+'<p>Paid reservation is available only after a supported licensed seller, written vehicle hold, complete quote, and deposit terms are confirmed.</p>';
  }
  function buildDeal(vin){
    const x=byVIN.get(vin);if(!x)return;activeVIN=vin;
    const zState=zipState();
    $('deal-summary').innerHTML=`<p class="eyebrow">YOUR TESLA, YOUR DEAL</p><h2>${x.year} Tesla ${esc(x.model)}</h2><p>${esc(x.trim)} · ${odometer(x)}</p>${saving(x)>0?`<div class="line-item"><span>Peer benchmark (${x.reference_sample} listings · ${esc(benchDate(x))})</span><strong>${dollars(x.reference_price)}</strong></div><div class="line-item savings-line"><span>Vehicle savings vs. benchmark (vehicle only)</span><strong>-${dollars(saving(x))}</strong></div>`:''}<div class="line-item"><span>Estimated vehicle price</span><strong>${dollars(x.display_price)}</strong></div><div class="line-item"><span>Delivery${zip?` to ${esc(zip)}${zState?` (${esc(zState)})`:''}`:''} (quoted separately)</span><strong>${zip?'Carrier quote in your deal':'Quote after ZIP'}</strong></div><div class="line-item"><span>Tax, title and registration (quoted separately)</span><strong>Itemized in your quote</strong></div><div class="line-item"><span>Reservation after quote approval</span><strong>$250 toward your purchase</strong></div><div class="line-item"><span>Estimated vehicle balance after $250 credit (before tax/delivery)</span><strong>${dollars(Math.max(0,x.display_price-250))}</strong></div><p>Vehicle savings apply to the vehicle price only and are carried separately from delivery, tax, and registration. Review the refund terms and available payment methods before paying. Your deposit counts toward the purchase price. Your selling dealer confirms balance-payment options.</p><ol class="deal-steps"><li>Choose your Tesla and delivery ZIP.</li><li>Review your complete quote and selling dealer.</li><li>Reserve securely, complete documents, and follow delivery.</li></ol>`;
    $('deal-zip').value=zip;$('deal-message').textContent=apiReady?(zip&&zState?`Delivery ZIP ${zip} (${zState}) is ready. Your quote request is free.`:'Your quote request is free. No payment at this step.'):'Save a deal draft in this browser. Online ordering is being connected. No request, hold, or payment is submitted.';
    $('deal-continue').textContent=apiReady?'Continue to your quote':'Save deal draft';
    close('vehicle-dialog');open('deal-dialog');
  }
  $('deal-form').addEventListener('submit',async e=>{
    e.preventDefault();const postal=$('deal-zip').value;
    try{await resolveZip(postal);if(apiReady){close('deal-dialog');startRequest(activeVIN);return;}
      localStorage.setItem('marketplace_deal',JSON.stringify({vin:activeVIN,zip:postal,created_at:new Date().toISOString()}));
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
      form.reset();close('request-dialog');showOrder(order);notify('Your Tesla is on your shortlist. Your quote is next.');
    }catch(error){$('request-error').textContent=error.message;}finally{b.disabled=false;}
  });
  async function refreshOrder(){
    const access=currentAccess();if(!access){
      $('order-content').innerHTML='<h2>Open your purchase request</h2><p>Use the private access receipt you saved when requesting verification.</p><form id="recover-form"><label>Request ID<input id="recover-id" required></label><label>Private access code<input id="recover-token" type="password" required></label><button class="primary">Open request</button><p id="recover-error" class="form-error" role="alert"></p></form>';
      $('recover-form').addEventListener('submit',async e=>{e.preventDefault();const recovered={id:$('recover-id').value.trim(),token:$('recover-token').value.trim()};try{const order=await api('orders/'+encodeURIComponent(recovered.id),{headers:{Authorization:'Bearer '+recovered.token}});sessionStorage.setItem('marketplace_order',JSON.stringify(recovered));showOrder(order);}catch(error){$('recover-error').textContent=error.message;}});
      open('order-dialog');return;
    }
    try{showOrder(await api('orders/'+encodeURIComponent(access.id),{headers:{Authorization:'Bearer '+access.token}}));}catch(error){notify(error.message);}
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
    const statusText=order.state==='requested'?'Your deal is being prepared. Your complete quote and selling dealer will appear here automatically. Then reserve securely online for $250.':order.state==='deposit_processing'?'Your $250 bank reservation debit is processing (1–4 business days). Vehicle hold locks once funds settle.':order.state==='refund_pending'?(order.refund_submitted?'Your $250 deposit refund has been submitted to the payment processor and updates automatically once settled.':'Your $250 deposit refund is queued for processing and updates automatically.'):'Status updates automatically as each step is verified (or select Refresh status anytime).';
    $('order-content').innerHTML=`<p class="eyebrow">YOUR PURCHASE</p><h2>${esc(stageNames[order.state]||order.state)}</h2><p>VIN ${esc(order.vin)}</p><p class="price-label">Request ${esc(order.id)}</p>${v?.model?`<div class="order-vehicle-card">${v.photo?`<img src="${esc(v.photo)}" alt="${esc(v.year+' Tesla '+v.model)}" loading="lazy" referrerpolicy="no-referrer">`:''}<div><strong>${esc((v.year?v.year+' ':'')+'Tesla '+v.model)}</strong><span>${esc([v.trim,v.mileage>0?`${v.mileage.toLocaleString()} mi`:null,v.city&&v.state&&v.state!=='US'?`${v.city}, ${v.state}`:null].filter(Boolean).join(' · '))}</span>${vehSavingsCents>0?`<em class="shortlist-save">Save ${money(vehSavingsCents)} vs. ${money(refCents)} peer benchmark (${refSample} listings)</em>`:''}</div></div>`:''}<button id="save-access" class="text-button">Save private access receipt</button><p>${statusText}</p><div class="line-item"><span>Payment path</span><strong>${pref==='partner_financing'?'Partner financing':'Cash / ACH bank transfer'}</strong></div>${canChangePref?`<label>Update payment preference<select id="order-payment-pref"><option value="cash" ${pref==='cash'?'selected':''}>Cash / ACH bank transfer</option><option value="partner_financing" ${pref==='partner_financing'?'selected':''}>Partner financing (subject to lender approval)</option></select></label>`:''}${q?`<h3>Your written quote</h3><p>Sold and fulfilled by <strong>${esc(q.seller.legal_name)}</strong><br>License ${esc(q.seller.license_number)} · ${esc(q.seller.address)}</p>${vehSavingsCents>0?`<div class="line-item"><span>Peer benchmark (${refSample} listings · ${esc(benchDate(v||{benchmark_date:q.benchmark_date}))})</span><strong>${money(refCents)}</strong></div><div class="line-item savings-line"><span>Vehicle savings vs. benchmark (vehicle only)</span><strong>-${money(vehSavingsCents)}</strong></div>`:''}${[['Vehicle price',money(q.vehicle_price_cents)],['Sales tax',money(q.tax_cents)],['Title and registration',money(q.title_registration_cents)],['Documentation',money(q.documentation_cents)],['Delivery',money(q.delivery_charge_cents)],['Complete purchase price',money(q.total_cents)],[depositCredited?'$250 reservation deposit (paid & credited)':'Reservation deposit (credited toward purchase)','-'+money(quoteDepositCents)],['Remaining balance after $250 deposit',money(quoteBalanceCents)]].map(([label,value])=>`<div class="line-item"><span>${label}</span><strong>${value}</strong></div>`).join('')}<p>Quote expires ${esc(new Date(q.valid_until*1000).toLocaleString())}.</p><ul class="terms-list">${Object.entries(q.terms).map(([label,url])=>`<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label.replaceAll('_',' '))}</a></li>`).join('')}</ul>`:''}${q&&['quoted','checkout_pending'].includes(order.state)&&config?.payments_enabled?'<label class="check"><input id="accept-quote" type="checkbox">I accept this complete quote and the linked deposit, return, and warranty terms.</label><button id="pay-deposit" class="primary">Pay refundable $250 reservation</button>':''}${pref==='partner_financing'||fin.state!=='not_requested'?`<section class="online-steps"><h3>Partner financing status</h3><div class="line-item"><span>Lender status</span><strong>${esc(finLabels[fin.state]||fin.state)}</strong></div>${finProvider?`<div class="line-item"><span>Partner lender</span><strong>${esc(finProvider)}</strong></div>`:''}${fin.approved_amount_cents>0?`<div class="line-item"><span>Approved financing amount</span><strong>${money(fin.approved_amount_cents)}</strong></div>`:''}${fin.funded_amount_cents>0?`<div class="line-item"><span>Funded proceeds to selling dealer</span><strong>${money(fin.funded_amount_cents)}</strong></div>`:''}${fin.stipulations?.length?`<div class="line-item"><span>Required stipulations</span><strong>${esc(fin.stipulations.join(', '))}</strong></div>`:''}${fin.application_url?`<a class="online-step" href="${esc(fin.application_url)}" target="_blank" rel="noopener noreferrer">Open partner lender application ↗</a>`:''}<p>Prequalification and conditional approval are not funded proceeds. Vehicle release requires verified lender funding to the selling dealer.</p></section>`:''}${q&&order.state==='dealer_confirmed'&&pref==='cash'?`<section class="online-steps"><h3>Remaining balance (${money(quoteBalanceCents)})</h3><div class="line-item"><span>Complete purchase price</span><strong>${money(q.total_cents)}</strong></div><div class="line-item"><span>Less $250 reservation credit</span><strong>-${money(quoteDepositCents)}</strong></div><div class="line-item"><span>Remaining balance due</span><strong>${money(quoteBalanceCents)}</strong></div><div class="line-item"><span>Balance status</span><strong>${esc(balLabels[balState]||balState)}</strong></div>${config?.payments_enabled&&['unpaid','checkout_open','failed','expired'].includes(balState)?'<label class="check"><input id="accept-balance" type="checkbox">I authorize ACH bank payment for the remaining balance under the accepted purchase terms.</label><button id="pay-balance" class="primary">Pay remaining balance via ACH</button>':''}<p>Bank account linking initiates an ACH Direct Debit (1–4 business days to settle). Vehicle release requires settled funds.</p></section>`:''}${tr.state!=='unquoted'?`<section class="online-steps"><h3>Delivery &amp; carrier tracking</h3><div class="line-item"><span>Transport status</span><strong>${esc(trLabels[tr.state]||tr.state)}</strong></div>${trProvider?`<div class="line-item"><span>Carrier</span><strong>${esc(trProvider)}</strong></div>`:''}${Number.isInteger(tr.rate_cents)?`<div class="line-item"><span>Carrier rate</span><strong>${money(tr.rate_cents)}</strong></div>`:''}${tr.quote_expires_at?`<div class="line-item"><span>Rate quote expires</span><strong>${esc(new Date(tr.quote_expires_at*1000).toLocaleString())}</strong></div>`:''}${tr.pickup_window_start&&tr.pickup_window_end?`<div class="line-item"><span>Pickup window</span><strong>${esc(new Date(tr.pickup_window_start*1000).toLocaleDateString())} – ${esc(new Date(tr.pickup_window_end*1000).toLocaleDateString())}</strong></div>`:''}${tr.delivery_window_start&&tr.delivery_window_end?`<div class="line-item"><span>Estimated delivery window</span><strong>${esc(new Date(tr.delivery_window_start*1000).toLocaleDateString())} – ${esc(new Date(tr.delivery_window_end*1000).toLocaleDateString())}</strong></div>`:''}${tr.bol_reference?`<div class="line-item"><span>Bill of lading (BOL)</span><strong>${esc(tr.bol_reference)}</strong></div>`:''}${tr.tracking_url?`<a class="online-step" href="${esc(tr.tracking_url)}" target="_blank" rel="noopener noreferrer">Open live carrier tracking ↗</a>`:''}<p>${tr.state==='quoted'?'A carrier rate quote is an estimate only; vehicle dispatch requires carrier acceptance and an electronic bill of lading.':'Carrier dispatch and delivery milestones are verified with the selling dealer and carrier.'}</p></section>`:''}${order.online_actions?.length?`<section class="online-steps"><h3>Complete your purchase</h3>${order.online_actions.map(a=>`<a class="online-step" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(onlineLabels[a.kind])} ↗</a>`).join('')}<p>Your purchase stays tracked here. Required signing or bank services open securely. Completion requires verification.</p></section>`:''}<div id="embedded-payment" class="embedded-payment"></div><div class="form-row"><button id="refresh-order" class="secondary">Refresh status</button>${['requested','quoted','quote_expired','checkout_pending','deposit_paid'].includes(order.state)?'<button id="cancel-order" class="secondary">Cancel request</button>':''}</div><button id="report-issue" class="text-button">Report a purchase issue</button><div id="issue-form" hidden><label>Issue type<select id="issue-kind"><option value="other">Purchase question</option><option value="return">Return request</option><option value="warranty">Warranty question</option><option value="transport_damage">Transport damage</option><option value="title_delay">Title processing</option></select></label><label>Describe the issue<textarea id="issue-description" minlength="5" maxlength="1000" rows="4"></textarea></label><button id="send-issue" class="secondary">Submit for review</button></div><button id="delete-request" class="text-button">Request personal-data deletion</button><p id="order-error" class="form-error" role="alert"></p>`;
    $('save-access').addEventListener('click',()=>{
      const content=JSON.stringify({request_id:access.id,private_access_code:access.token,site:rootURL.href,instructions:'Keep this receipt private. Open Your purchase request to restore access.'},null,2);
      const url=URL.createObjectURL(new Blob([content],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='vehicle-request-access.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
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
    $('gallery-thumbs').innerHTML=galleryPhotos.map((x,i)=>`<button class="gallery-thumb ${i===galleryIndex?'active':''}" data-photo="${i}" aria-label="${esc(x.title)} — photo ${i+1}"><img src="${esc(x.url)}" loading="lazy" alt="${esc(x.title)}" referrerpolicy="no-referrer"></button>`).join('');
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
    $('purchase-availability').hidden=apiReady;
    $('business-status').textContent=apiReady?'Find your Tesla · Reserve online for $250 · Delivery arranged with the selling dealer':'Explore Teslas · Browse vehicle photos · Save your favorites';
    $('order-button').hidden=false;$('order-button').textContent=apiReady?'Your purchase':'Your saved deal';
    if(apiReady)$('hero-description').innerHTML='The Tesla you want. A price you can explore. Reserve online for <strong>$250, refundable.</strong>';
    if(items.length)applyFilters();
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
