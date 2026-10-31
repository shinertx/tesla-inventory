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
  let saved=new Set(), zip='', requestKey=null;
  try { saved=new Set(JSON.parse(localStorage.getItem('marketplace_saved') || '[]')); zip=localStorage.getItem('marketplace_zip') || ''; } catch {}
  if (!/^\d{5}$/.test(zip)) zip='';
  const stages=['requested','quoted','checkout_pending','deposit_paid','dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending','completed'];
  const stageNames={requested:'Verification requested',quoted:'Complete quote ready',checkout_pending:'Secure checkout opened',deposit_paid:'Deposit verified',dealer_confirmed:'Dealer accepted your purchase',dealer_funded:'Dealer confirmed your payment',settlement_pending:'Final paperwork and settlement',in_transit:'Carrier has the vehicle',delivered:'Vehicle delivered',completed:'Title and settlement complete',refund_pending:'Deposit refund pending',refunded:'Deposit refunded',quote_expired:'Quote expired',cancelled:'Request cancelled',payment_review:'Payment needs review'};

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
  function toggleSave(vin){saved.has(vin)?saved.delete(vin):saved.add(vin);updateSaved();applyFilters();}
  function options(id,values){const select=$(id);values.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;select.append(option);});}
  function image(item,cls=''){
    return item.photo?`<img class="${cls}" src="${esc(item.photo)}" alt="${esc(item.year+' Tesla '+item.model)}" loading="lazy" referrerpolicy="no-referrer">`:`<span class="photo-fallback">${esc(item.model)}</span>`;
  }
  function attachImageFallbacks(container){container.querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>{const fallback=document.createElement('span');fallback.className='photo-fallback';fallback.textContent='Vehicle photo unavailable';img.replaceWith(fallback);},{once:true}));}
  function applyFilters(){
    const search=$('search').value.trim().toLowerCase();
    filtered=items.filter(x=>(!$('model').value||x.model===$('model').value)&&(!$('year').value||x.year===Number($('year').value))&&(!$('state').value||x.state===$('state').value)&&x.display_price<=Number($('price').value)&&x.mileage<=Number($('mileage').value)&&(!$('saved-only').checked||saved.has(x.vin))&&(!search||[x.vin,x.model,x.trim,x.stock_number,x.city,x.state].join(' ').toLowerCase().includes(search)));
    const sort=$('sort').value;
    filtered.sort((a,b)=>sort==='recommended'?(Number(Boolean(b.photo))-Number(Boolean(a.photo))||Math.abs(a.display_price-35000)-Math.abs(b.display_price-35000)):sort==='price-desc'?b.display_price-a.display_price:sort==='mileage'?a.mileage-b.mileage:sort==='year'?b.year-a.year:a.display_price-b.display_price);
    limit=36;render();
  }
  function render(){
    $('result-count').textContent=`${filtered.length.toLocaleString()} Tesla listings`;
    $('cards').innerHTML=filtered.slice(0,limit).map(x=>`<article class="card" data-vin="${x.vin}"><div class="photo-wrap">${image(x)}<button class="save" data-save="${x.vin}" aria-label="${saved.has(x.vin)?'Remove saved':'Save'} ${esc(x.year+' '+x.model)}" aria-pressed="${saved.has(x.vin)}">${saved.has(x.vin)?'♥':'♡'}</button></div><a class="card-main" href="?vin=${x.vin}" data-open="${x.vin}"><h3>${x.year} Tesla ${esc(x.model)}</h3><div class="trim">${esc(x.trim)}<br>${x.mileage.toLocaleString()} miles</div><div class="price">${dollars(x.display_price)}</div><div class="price-label">Estimated vehicle price<br>Tax, title, and delivery quoted separately</div><span class="pill">Availability needs confirmation</span></a><div class="card-footer"><span>${esc(x.city||'Vehicle location')}${x.state!=='US'?', '+esc(x.state):''}</span><span>Stock ${esc(x.stock_number)}</span></div></article>`).join('');
    $('empty').hidden=filtered.length>0;$('load-more').hidden=limit>=filtered.length;
    attachImageFallbacks($('cards'));
  }
  $('cards').addEventListener('click',e=>{const save=e.target.closest('[data-save]');if(save){toggleSave(save.dataset.save);return;}const link=e.target.closest('[data-open]');if(link){e.preventDefault();showVehicle(link.dataset.open);}});
  function showVehicle(vin){
    const x=byVIN.get(vin);if(!x){notify('This vehicle is not in the current published snapshot.');return;}
    activeVIN=vin;
    const url=new URL(location.href);url.searchParams.delete('reservation');url.searchParams.delete('session_id');url.searchParams.delete('test_mode');url.searchParams.set('vin',vin);history.replaceState(null,'',url);
    $('vehicle-content').innerHTML=`<button class="close" data-close="vehicle-dialog" aria-label="Close vehicle details">×</button><div class="vehicle-top"><div class="vehicle-image">${image(x)}</div><div class="vehicle-summary"><p class="eyebrow">KNOW THE DETAILS</p><h2>${x.year} Tesla ${esc(x.model)}</h2><p>${esc(x.trim)} · ${x.mileage.toLocaleString()} miles</p><div class="price">${dollars(x.display_price)}</div><p class="price-label">Estimated vehicle price. Your complete quote includes tax, title, and delivery.</p><button id="vehicle-request" class="primary" ${apiReady?'':'disabled'}>${apiReady?'Start your purchase · $0 due':'Online requests are not connected'}</button><p class="price-label">No deposit or exclusive hold is created by a request.</p></div></div><div class="vehicle-body"><div class="vehicle-tabs" role="tablist" aria-label="Vehicle information"><button class="tab" role="tab" id="tab-details" aria-controls="vehicle-panel" aria-selected="true" data-tab="details">Vehicle details</button><button class="tab" role="tab" id="tab-pricing" aria-controls="vehicle-panel" aria-selected="false" data-tab="pricing">Price and delivery</button><button class="tab" role="tab" id="tab-process" aria-controls="vehicle-panel" aria-selected="false" data-tab="process">Purchase steps</button></div><div id="vehicle-panel" role="tabpanel" aria-labelledby="tab-details"></div></div>`;
    $('vehicle-request').addEventListener('click',()=>startRequest(vin));
    $('vehicle-content').querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>vehicleTab(b.dataset.tab)));
    $('vehicle-content').querySelector('[role=tablist]').addEventListener('keydown',e=>{
      if(!['ArrowLeft','ArrowRight'].includes(e.key))return;
      const tabs=[...$('vehicle-content').querySelectorAll('[data-tab]')];const index=tabs.indexOf(document.activeElement);
      if(index<0)return;e.preventDefault();const next=tabs[(index+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];next.click();next.focus();
    });
    attachImageFallbacks($('vehicle-content'));vehicleTab('details');open('vehicle-dialog');
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
      form.reset();close('request-dialog');showOrder(order);notify('Your request was saved. No payment was collected.');
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
    $('order-content').innerHTML=`<p class="eyebrow">YOUR PURCHASE REQUEST</p><h2>${esc(stageNames[order.state]||order.state)}</h2><p>VIN ${esc(order.vin)}</p><p class="price-label">Request ${esc(order.id)}</p><button id="save-access" class="text-button">Save private access receipt</button><p>${order.state==='requested'?'Your purchase request is saved. We’ll confirm the vehicle and match it to a fulfilling dealer before preparing your quote.':'Refresh this page to check the latest recorded status.'}</p>${q?`<h3>Your written quote</h3><p>Sold and fulfilled by <strong>${esc(q.seller.legal_name)}</strong><br>License ${esc(q.seller.license_number)} · ${esc(q.seller.address)}</p>${[['Vehicle price',q.vehicle_price_cents],['Sales tax',q.tax_cents],['Title and registration',q.title_registration_cents],['Documentation',q.documentation_cents],['Delivery',q.delivery_charge_cents],['Complete purchase price',q.total_cents]].map(([label,value])=>`<div class="line-item"><span>${label}</span><strong>${money(value)}</strong></div>`).join('')}<p>Quote expires ${esc(new Date(q.valid_until*1000).toLocaleString())}.</p><ul class="terms-list">${Object.entries(q.terms).map(([label,url])=>`<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label.replaceAll('_',' '))}</a></li>`).join('')}</ul>`:''}${q&&order.state==='quoted'&&config?.payments_enabled?'<label class="check"><input id="accept-quote" type="checkbox">I accept this complete quote and the linked deposit, return, and warranty terms.</label><button id="pay-deposit" class="primary">Continue to secure $250 deposit</button>':''}<div class="form-row"><button id="refresh-order" class="secondary">Refresh status</button>${['requested','quoted','quote_expired','checkout_pending','deposit_paid'].includes(order.state)?'<button id="cancel-order" class="secondary">Cancel request</button>':''}</div><button id="report-issue" class="text-button">Report a purchase issue</button><div id="issue-form" hidden><label>Issue type<select id="issue-kind"><option value="other">Purchase question</option><option value="return">Return request</option><option value="warranty">Warranty question</option><option value="transport_damage">Transport damage</option><option value="title_delay">Title processing</option></select></label><label>Describe the issue<textarea id="issue-description" minlength="5" maxlength="1000" rows="4"></textarea></label><button id="send-issue" class="secondary">Submit for review</button></div><button id="delete-request" class="text-button">Request personal-data deletion</button><p id="order-error" class="form-error" role="alert"></p>`;
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
  ['model','year','state','price','mileage','sort','saved-only'].forEach(id=>$(id).addEventListener('change',applyFilters));
  let searchTimer;$('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(applyFilters,140);});
  $('reset').addEventListener('click',()=>{['model','year','state','search'].forEach(id=>$(id).value='');$('price').value='999999';$('mileage').value='999999';$('saved-only').checked=false;applyFilters();});
  $('load-more').addEventListener('click',()=>{limit+=36;render();});
  $('saved-button').addEventListener('click',()=>{$('saved-only').checked=!$('saved-only').checked;applyFilters();$('inventory').scrollIntoView({behavior:'smooth'});});
  $('mobile-filters').addEventListener('click',()=>$('filters').classList.toggle('expanded'));
  $('zip-label').textContent=zip||'Set ZIP';$('zip-button').addEventListener('click',()=>{$('zip-input').value=zip;open('zip-dialog');});
  $('zip-form').addEventListener('submit',e=>{e.preventDefault();zip=$('zip-input').value;try{localStorage.setItem('marketplace_zip',zip);}catch{}$('zip-label').textContent=zip;close('zip-dialog');});
  $('privacy-button').addEventListener('click',()=>open('privacy-dialog'));
  $('order-button').addEventListener('click',refreshOrder);updateSaved();
  api('config').then(c=>{config=c;apiReady=true;$('business-status').textContent=c.partner_onboarding_status==='ready'?'Shop online · Dealer-owned vehicles · Complete quote before reservation':'Partner verification in progress · Browse vehicles and request a complete quote';}).catch(()=>{apiReady=false;$('business-status').textContent='Browse vehicles · Online purchase requests are not connected';});
  fetch(new URL('inventory.json',rootURL)).then(r=>{if(!r.ok)throw new Error('Inventory unavailable');return r.json();}).then(payload=>{
    items=payload.items.filter(x=>!x.expires_at||new Date(x.expires_at).getTime()>Date.now());byVIN=new Map(items.map(x=>[x.vin,x]));
    options('model',[...new Set(items.map(x=>x.model))].sort());options('year',[...new Set(items.map(x=>x.year))].sort((a,b)=>b-a));options('state',[...new Set(items.map(x=>x.state))].filter(x=>x!=='US').sort());
    $('snapshot-status').textContent='Dealer-owned vehicles · Availability confirmed before reservation';
    const preset=document.body.dataset.preset;if(preset){const [key,value]=preset.split(':');if($(key))$(key).value=value;}
    applyFilters();
    const vin=new URLSearchParams(location.search).get('vin');if(vin)showVehicle(vin);
    // Redirect parameters never prove payment. Only an authenticated server order does.
    if(new URLSearchParams(location.search).has('checkout')&&currentAccess())refreshOrder();
  }).catch(()=>{$('result-count').textContent='Inventory is temporarily unavailable';$('snapshot-status').textContent='Please try again later. No request or payment was created.';});
})();
