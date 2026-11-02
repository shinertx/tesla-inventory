'use strict';
// Keep older saved vehicle links usable without publishing a VIN-to-stock index.
(async function () {
  const match=location.pathname.match(/\/v\/([A-HJ-NPR-Z0-9]{17})\.html$/i);
  if(!match||!globalThis.crypto?.subtle)return;
  const raw=await crypto.subtle.digest('SHA-256',new TextEncoder().encode('volts-and-vins:'+match[1].toUpperCase()));
  const stock='VV-'+[...new Uint8Array(raw)].map(b=>b.toString(16).padStart(2,'0')).join('').slice(0,12).toUpperCase();
  const target=new URL(location.href),params=new URLSearchParams(target.search);
  target.pathname=target.pathname.replace(match[1]+'.html',stock+'.html');target.search='';target.hash='';
  for(const key of ['utm_source','utm_medium','utm_campaign','utm_term','utm_content']){
    if(params.has(key))target.searchParams.set(key,params.get(key).slice(0,500));
  }
  location.replace(target.href);
})().catch(()=>{});
