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
  let items=[], byVIN=new Map(), filtered=[], limit=36, activeVIN=null, apiReady=false, config=null;
  let saved=new Set(), zip='', requestKey=null, discovery='all',mediaVersion='';
  const galleryShards=new Map();
  let galleryPhotos=[],galleryIndex=0;let galleryRequest=0;const failedPhotos=new Set();
  try { saved=new Set(JSON.parse(localStorage.getItem('marketplace_saved') || '[]')); zip=localStorage.getItem('marketplace_zip') || ''; } catch {}
  if (!/^\d{5}$/.test(zip)) zip='';
  const stages=['requested','quoted','checkout_pending','deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending','completed'];
  const onlineLabels={sign_contract:'Sign your purchase agreement',pay_balance:'Pay the selling dealer',submit_title_documents:'Complete your title documents',track_delivery:'Track your delivery'};
  const stageNames={requested:'Preparing your deal',quoted:'Complete quote ready',checkout_pending:'Secure checkout opened',deposit_paid:'Deposit verified',dealer_confirmed:'Dealer accepted your purchase',dealer_funded:'Dealer confirmed your payment',settlement_pending:'Final paperwork and settlement',in_transit:'Carrier has the vehicle',delivered:'Vehicle delivered',completed:'Title and settlement complete',refund_pending:'Deposit refund pending',refunded:'Deposit refunded',quote_expired:'Quote expired',cancelled:'Request cancelled',payment_review:'Payment needs review'};

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
  function image(item,cls=''){
    return item.photo?`<img class="${cls}" src="${esc(item.photo)}" alt="${esc(item.year+' Tesla '+item.model)}" loading="lazy" referrerpolicy="no-referrer">`:`<span class="photo-fallback">${esc(item.model)}</span>`;
  }
  function attachImageFallbacks(container){container.querySelectorAll('img').forEach(img=>{
    const ready=()=>img.classList.add('loaded');if(img.complete&&img.naturalWidth)ready();img.addEventListener('load',ready,{once:true});
    img.addEventListener('error',()=>{const card=img.closest('.card');if(card&&$('photos-only').checked){failedPhotos.add(card.dataset.vin);queueMicrotask(applyFilters);return;}const fallback=document.createElement('span');fallback.className='photo-fallback';fallback.textContent='Photo coming soon';img.replaceWith(fallback);},{once:true});
  });}
  const saving=x=>x.reference_sample>=5&&x.reference_price>x.display_price?x.reference_price-x.display_price:0;
  function applyFilters(){
    const search=$('search').value.trim().toLowerCase();
    filtered=items.filter(x=>(!$('photos-only').checked||(!!x.photo&&!failedPhotos.has(x.vin)))&&(discovery!=='finds'||saving(x)>=500)&&(!$('model').value||x.model===$('model').value)&&(!$('year').value||x.year===Number($('year').value))&&(!$('state').value||x.state===$('state').value)&&x.display_price<=Number($('price').value)&&x.mileage<=Number($('mileage').value)&&(!$('saved-only').checked||saved.has(x.vin))&&(!search||[x.vin,x.model,x.trim,x.stock_number,x.city,x.state].join(' ').toLowerCase().includes(search)));
    const sort=$('sort').value;
    filtered.sort((a,b)=>sort==='recommended'?(Number(Boolean(b.photo))-Number(Boolean(a.photo))||Number(saving(b)>=500)-Number(saving(a)>=500)||Math.abs(a.display_price-35000)-Math.abs(b.display_price-35000)):sort==='price-desc'?b.display_price-a.display_price:sort==='mileage'?a.mileage-b.mileage:sort==='year'?b.year-a.year:a.display_price-b.display_price);
    limit=36;render();
  }
  function render(){
    $('result-count').textContent=`${filtered.length.toLocaleString()} Tesla listings`;
    $('cards').innerHTML=filtered.slice(0,limit).map(x=>`<article class="card" data-vin="${x.vin}"><div class="photo-wrap">${image(x)}${(x.photo_count||x.photos?.length)>1?`<span class="photo-count">▧ ${x.photo_count||x.photos.length}</span>`:''}${saving(x)>=500?`<span class="find-badge">✦ Price find</span>`:''}<button class="save" data-save="${x.vin}" aria-label="${saved.has(x.vin)?'Remove saved':'Save'} ${esc(x.year+' '+x.model)}" aria-pressed="${saved.has(x.vin)}">${saved.has(x.vin)?'♥':'♡'}</button></div><a class="card-main" href="?vin=${x.vin}" data-open="${x.vin}"><h3>${x.year} Tesla ${esc(x.model)}</h3><div class="trim">${esc(x.trim)}<br>${x.mileage.toLocaleString()} miles</div><div class="price">${dollars(x.display_price)}</div><div class="price-label">Estimated vehicle price<br>Tax, title, and delivery quoted separately</div>${saving(x)>=500?`<span class="price-win" title="Median of ${x.reference_sample} comparable advertised listings on this site. Not an appraisal.">${dollars(saving(x))} below similar listings</span>`:''}</a><div class="card-footer"><span>${esc(x.city||'Vehicle location')}${x.state!=='US'?', '+esc(x.state):''}</span><span class="reserve-note">${apiReady?'Reserve for $250':'View vehicle'}</span></div></article>`).join('');
    $('empty').hidden=filtered.length>0;$('load-more').hidden=limit>=filtered.length;
    attachImageFallbacks($('cards'));
  }
  $('cards').addEventListener('click',e=>{const save=e.target.closest('[data-save]');if(save){toggleSave(save.dataset.save);return;}const link=e.target.closest('[data-open]');if(link){e.preventDefault();showVehicle(link.dataset.open);}});
  function showVehicle(vin){
    const x=byVIN.get(vin);if(!x){notify('This vehicle is not in the current published snapshot.');return;}
    activeVIN=vin;
    const url=new URL(location.href);url.searchParams.delete('reservation');url.searchParams.delete('session_id');url.searchParams.delete('test_mode');url.searchParams.set('vin',vin);history.replaceState(null,'',url);
    $('vehicle-content').innerHTML=`<button class="close" data-close="vehicle-dialog" aria-label="Close vehicle details">×</button><div class="vehicle-top"><div class="vehicle-media"><div class="vehicle-image"><div id="gallery-stage">${image(x)}</div><button id="gallery-prev" class="gallery-arrow left" aria-label="Previous vehicle photo">‹</button><button id="gallery-next" class="gallery-arrow right" aria-label="Next vehicle photo">›</button><button id="photo-expand" class="photo-expand">⤢ View photos <span id="gallery-count"></span></button></div><div id="gallery-thumbs" class="gallery-thumbs"></div><div class="gallery-status"><span id="gallery-status" role="status"></span><button id="gallery-retry" class="secondary" hidden>Retry photos</button></div></div><div class="vehicle-summary"><p class="eyebrow">KNOW THE DETAILS</p><h2>${x.year} Tesla ${esc(x.model)}</h2><p>${esc(x.trim)} · ${x.mileage.toLocaleString()} miles</p><div class="price">${dollars(x.display_price)}</div><p class="price-label">Estimated vehicle price. Your complete quote includes tax, title, and delivery.</p><button id="vehicle-request" class="primary" ${apiReady?'':'disabled'}>${apiReady?'Reserve this Tesla · $250':'Online reservations coming soon'}</button><p class="price-label">Refundable reservation. Review your complete quote before payment.</p></div></div><div class="vehicle-body"><div class="vehicle-tabs" role="tablist" aria-label="Vehicle information"><button class="tab" role="tab" id="tab-details" aria-controls="vehicle-panel" aria-selected="true" data-tab="details">Vehicle details</button><button class="tab" role="tab" id="tab-pricing" aria-controls="vehicle-panel" aria-selected="false" data-tab="pricing">Price and delivery</button><button class="tab" role="tab" id="tab-process" aria-controls="vehicle-panel" aria-selected="false" data-tab="process">Purchase steps</button></div><div id="vehicle-panel" role="tabpanel" aria-labelledby="tab-details"></div></div>`;
    $('vehicle-request').addEventListener('click',()=>startRequest(vin));
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
    if(tab==='details')$('vehicle-panel').innerHTML=`<div class="spec-grid">${spec('Vehicle identification number',x.vin)}${spec('Stock number',x.stock_number)}${spec('Advertised trim',x.trim)}${spec('Model year',x.year)}${spec('Title history','Not yet verified')}${spec('Autopilot hardware','Vehicle-specific evidence required')}${spec('Inspection','No inspection report on file')}${spec('Availability','Seller confirmation required')}</div><div class="notice">The fulfilling dealer confirms vehicle condition, title, equipment, and availability before you reserve. Your purchase documents identify that dealer as the seller.</div>`;
    if(tab==='pricing')$('vehicle-panel').innerHTML=`<div class="line-item"><span>Estimated vehicle price</span><strong>${dollars(x.display_price)}</strong></div><div class="line-item"><span>Sales tax and registration</span><strong>Quote required</strong></div><div class="line-item"><span>Transport to ${zip?esc(zip):'your ZIP'}</span><strong>Carrier quote required</strong></div><div class="notice">Your final quote will identify the licensed seller, complete price, inspection evidence, and written purchase terms. Financing and trade-in acceptance are not currently offered here.</div>${x.reference_price?`<p>Similar advertised vehicles have a median estimated price of ${dollars(x.reference_price)} across ${x.reference_sample} listings. Asking prices do not establish actual sale values.</p>`:''}`;
    if(tab==='process')$('vehicle-panel').innerHTML=stages.filter(s=>s!=='checkout_pending').map(s=>`<div class="order-stage">${esc(stageNames[s])}</div>`).join('')+'<p>Paid reservation is available only after a supported licensed seller, written vehicle hold, complete quote, and deposit terms are confirmed.</p>';
  }
  function channel(){const value=new URLSearchParams(location.search).get('utm_source')||'direct';return /^[a-z0-9_-]{1,60}$/.test(value)?value:'direct';}
  async function startRequest(vin){
    activeVIN=vin;const x=byVIN.get(vin);$('request-car').textContent=`${x.year} ${x.model} · VIN ${vin}`;
    $('request-error').textContent='';requestKey=crypto.randomUUID();
    $('request-form').reset();$('request-form').elements.zip.value=zip;
    close('vehicle-dialog');open('request-dialog');
    if(!apiReady){$('request-error').textContent='The request service is not connected. No personal details have been submitted.';$('submit-request').disabled=true;}else $('submit-request').disabled=false;
  }
  $('request-form').addEventListener('submit',async e=>{
    e.preventDefault();if(!apiReady)return;const form=e.currentTarget;const b=$('submit-request');b.disabled=true;
    const data=new FormData(form);
    try{
      const order=await api('requests',{method:'POST',headers:{'Idempotency-Key':requestKey},body:JSON.stringify({vin:activeVIN,name:data.get('name'),email:data.get('email'),state:String(data.get('state')).toUpperCase(),zip:data.get('zip'),demand_channel:channel(),campaign_id:new URLSearchParams(location.search).get('utm_campaign')?.slice(0,100)||'',consent:data.get('consent')==='on'})});
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
    const q=order.quote;const access=currentAccess();
    $('order-content').innerHTML=`<p class="eyebrow">YOUR PURCHASE REQUEST</p><h2>${esc(stageNames[order.state]||order.state)}</h2><p>VIN ${esc(order.vin)}</p><p class="price-label">Request ${esc(order.id)}</p><button id="save-access" class="text-button">Save private access receipt</button><p>${order.state==='requested'?'Your deal is being prepared. Your complete quote and selling dealer will appear here. Then reserve securely online for $250.':'Refresh this page to check the latest recorded status.'}</p>${q?`<h3>Your written quote</h3><p>Sold and fulfilled by <strong>${esc(q.seller.legal_name)}</strong><br>License ${esc(q.seller.license_number)} · ${esc(q.seller.address)}</p>${[['Vehicle price',q.vehicle_price_cents],['Sales tax',q.tax_cents],['Title and registration',q.title_registration_cents],['Documentation',q.documentation_cents],['Delivery',q.delivery_charge_cents],['Complete purchase price',q.total_cents]].map(([label,value])=>`<div class="line-item"><span>${label}</span><strong>${money(value)}</strong></div>`).join('')}<p>Quote expires ${esc(new Date(q.valid_until*1000).toLocaleString())}.</p><ul class="terms-list">${Object.entries(q.terms).map(([label,url])=>`<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label.replaceAll('_',' '))}</a></li>`).join('')}</ul>`:''}${q&&order.state==='quoted'&&config?.payments_enabled?'<label class="check"><input id="accept-quote" type="checkbox">I accept this complete quote and the linked deposit, return, and warranty terms.</label><button id="pay-deposit" class="primary">Continue to secure $250 deposit</button>':''}${order.online_actions?.length?`<section class="online-steps"><h3>Your next step</h3>${order.online_actions.map(a=>`<a class="online-step" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(onlineLabels[a.kind])} ↗</a>`).join('')}<p>Continue securely with your selling dealer. Your status updates after completion is verified.</p></section>`:''}<div class="form-row"><button id="refresh-order" class="secondary">Refresh status</button>${['requested','quoted','quote_expired','checkout_pending','deposit_paid'].includes(order.state)?'<button id="cancel-order" class="secondary">Cancel request</button>':''}</div><button id="report-issue" class="text-button">Report a purchase issue</button><div id="issue-form" hidden><label>Issue type<select id="issue-kind"><option value="other">Purchase question</option><option value="return">Return request</option><option value="warranty">Warranty question</option><option value="transport_damage">Transport damage</option><option value="title_delay">Title processing</option></select></label><label>Describe the issue<textarea id="issue-description" minlength="5" maxlength="1000" rows="4"></textarea></label><button id="send-issue" class="secondary">Submit for review</button></div><button id="delete-request" class="text-button">Request personal-data deletion</button><p id="order-error" class="form-error" role="alert"></p>`;
    $('save-access').addEventListener('click',()=>{
      const content=JSON.stringify({request_id:access.id,private_access_code:access.token,site:rootURL.href,instructions:'Keep this receipt private. Open Your purchase request to restore access.'},null,2);
      const url=URL.createObjectURL(new Blob([content],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='vehicle-request-access.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
    $('refresh-order').addEventListener('click',refreshOrder);
    $('report-issue').addEventListener('click',()=>{$('issue-form').hidden=!$('issue-form').hidden;});
    $('send-issue').addEventListener('click',async()=>{
      try{await api(`orders/${access.id}/cases`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({kind:$('issue-kind').value,description:$('issue-description').value})});$('issue-form').hidden=true;notify('Your issue was recorded for partner support review.');}catch(e){$('order-error').textContent=e.message;}
    });
    $('cancel-order')?.addEventListener('click',async()=>{try{const result=await api(`orders/${access.id}/cancel`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({reason:'Customer requested cancellation'})});showOrder(result);}catch(e){$('order-error').textContent=e.message;}});
    $('delete-request').addEventListener('click',async()=>{try{await api(`orders/${access.id}/privacy`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:'{}'});notify('Deletion request recorded for review against transaction retention requirements.');}catch(e){$('order-error').textContent=e.message;}});
    $('pay-deposit')?.addEventListener('click',async()=>{
      if(!$('accept-quote').checked){$('order-error').textContent='Review and accept the quote and linked terms first.';return;}
      $('pay-deposit').disabled=true;
      try{const result=await api(`orders/${access.id}/checkout`,{method:'POST',headers:{Authorization:'Bearer '+access.token},body:JSON.stringify({quote_version:order.quote_version,terms_accepted:true})});const target=new URL(result.url);if(target.protocol!=='https:'||target.hostname!=='checkout.stripe.com')throw new Error('Unexpected payment destination');location.assign(target.href);}catch(e){$('order-error').textContent=e.message;$('pay-deposit').disabled=false;}
    });
    open('order-dialog');
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
    $('shortlist-content').innerHTML=favorites.length?favorites.map(x=>`<button class="shortlist-car" data-shortlist-open="${x.vin}">${image(x)}<span><strong>${x.year} Tesla ${esc(x.model)}</strong><small>${esc(x.trim)} · ${x.mileage.toLocaleString()} mi</small><b>${dollars(x.display_price)}</b></span><span>→</span></button>`).join(''):'<div class="shortlist-empty">♡<h3>Start with a favorite.</h3><p>Tap a heart while you explore. Your shortlist will be right here.</p></div>';
    $('compare-saved').hidden=favorites.length<2;
    $('shortlist-content').querySelectorAll('[data-shortlist-open]').forEach(b=>b.addEventListener('click',()=>{close('saved-dialog');showVehicle(b.dataset.shortlistOpen);}));attachImageFallbacks($('shortlist-content'));open('saved-dialog');
  }
  $('compare-saved').addEventListener('click',()=>{
    const xs=items.filter(x=>saved.has(x.vin)).slice(0,3);
    $('compare-content').innerHTML=`<div class="comparison-grid">${xs.map(x=>`<article>${image(x)}<h3>${x.year} ${esc(x.model)}</h3><div class="price">${dollars(x.display_price)}</div><p>${esc(x.trim)}</p><p>${x.mileage.toLocaleString()} miles</p><p>${esc(x.city)}, ${esc(x.state)}</p><button class="primary" data-compare-open="${x.vin}">Explore this Tesla</button></article>`).join('')}</div>`;
    $('compare-content').querySelectorAll('[data-compare-open]').forEach(b=>b.addEventListener('click',()=>{close('compare-dialog');showVehicle(b.dataset.compareOpen);}));close('saved-dialog');open('compare-dialog');
  });
  document.querySelectorAll('[data-discover]').forEach(button=>button.addEventListener('click',()=>{
    discovery=button.dataset.discover;document.querySelectorAll('[data-discover]').forEach(b=>b.classList.toggle('active',b===button));
    $('model').value=['Model Y','Model 3','Cybertruck'].includes(discovery)?discovery:'';
    $('price').value=discovery==='under30'?'30000':'999999';$('mileage').value=discovery==='lowmiles'?'30000':'999999';$('search').value='';applyFilters();
  }));
  ['model','year','state','price','mileage','sort','saved-only','photos-only'].forEach(id=>$(id).addEventListener('change',applyFilters));
  let searchTimer;$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(applyFilters,140);});
  $('reset').addEventListener('click',()=>{['model','year','state','search'].forEach(id=>$(id).value='');$('price').value='999999';$('mileage').value='999999';$('saved-only').checked=false;discovery='all';$('photos-only').checked=true;applyFilters();});
  $('load-more').addEventListener('click',()=>{limit+=36;render();});
  $('saved-button').addEventListener('click',showShortlist);
  $('mobile-filters').addEventListener('click',()=>$('filters').classList.toggle('expanded'));
  $('zip-label').textContent=zip||'Set ZIP';$('zip-button').addEventListener('click',()=>{$('zip-input').value=zip;open('zip-dialog');});
  $('zip-form').addEventListener('submit',e=>{e.preventDefault();zip=$('zip-input').value;try{localStorage.setItem('marketplace_zip',zip);}catch{}$('zip-label').textContent=zip;close('zip-dialog');});
  $('privacy-button').addEventListener('click',()=>open('privacy-dialog'));
  $('order-button').addEventListener('click',refreshOrder);updateSaved();
  function purchaseAvailability(){
    $('purchase-availability').hidden=apiReady;
    $('business-status').textContent=apiReady?'Find your Tesla · Reserve online for $250 · Delivery arranged with the selling dealer':'Explore Teslas · Browse vehicle photos · Save your favorites';
    $('order-button').hidden=!apiReady;
    if(apiReady)$('hero-description').innerHTML='The Tesla you want. A price you can explore. Reserve online for <strong>$250, refundable.</strong>';
    if(items.length)applyFilters();
    const button=$('vehicle-request');if(button){button.disabled=!apiReady;button.textContent=apiReady?'Reserve this Tesla · $250':'Online reservations coming soon';}
  }
  purchaseAvailability();
  api('config').then(c=>{config=c;apiReady=!!c.requests_enabled;purchaseAvailability();}).catch(()=>{apiReady=false;purchaseAvailability();});
  fetch(new URL('inventory.json?v='+(new URL(scriptURL).searchParams.get('v')||'current'),rootURL)).then(r=>{if(!r.ok)throw new Error('Inventory unavailable');return r.json();}).then(payload=>{
    mediaVersion=payload.meta?.media_version||'';
    items=payload.items.filter(x=>!x.expires_at||new Date(x.expires_at).getTime()>Date.now());byVIN=new Map(items.map(x=>[x.vin,x]));
    options('model',[...new Set(items.map(x=>x.model))].sort());options('year',[...new Set(items.map(x=>x.year))].sort((a,b)=>b-a));options('state',[...new Set(items.map(x=>x.state))].filter(x=>x!=='US').sort());
    $('snapshot-status').textContent='Your next favorite is in here.';
    const preset=document.body.dataset.preset;if(preset){const [key,value]=preset.split(':');if($(key))$(key).value=value;}
    applyFilters();
    const vin=new URLSearchParams(location.search).get('vin');if(vin)showVehicle(vin);
    // Redirect parameters never prove payment. Only an authenticated server order does.
    if(new URLSearchParams(location.search).has('checkout')&&currentAccess())refreshOrder();
  }).catch(()=>{$('result-count').textContent='Inventory is temporarily unavailable';$('snapshot-status').textContent='Please try again later. No request or payment was created.';});
})();
