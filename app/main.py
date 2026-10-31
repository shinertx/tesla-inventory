from pathlib import Path
from typing import Annotated
import hashlib, hmac, json, secrets, sqlite3, time, uuid
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings, ROOT
from .models import PurchaseRequest, Quote, Transition, Cancellation, CheckoutAcceptance, SellerHold, CustomerCase, CaseResolution, AccessRecovery, Dealer, Settlement, SettlementReversal, OnlineAction
from .store import Store
from .payments import StripePayments
from .media import VehicleMedia

DEPOSIT = 25000
ONLINE_STATES={
    'sign_contract':{'deposit_paid'},
    'pay_balance':{'dealer_confirmed'},
    'submit_title_documents':{'dealer_confirmed','dealer_funded','in_transit','delivered'},
    'track_delivery':{'in_transit','delivered'},
}

TRANSITIONS = {
    'deposit_paid': ('dealer_confirmed', {'dealer_sale_contract','dealer_order_acceptance','identity_check','deposit_reconciled'}),
    'dealer_confirmed': ('dealer_funded', {'dealer_received_balance','dealer_funding_reference','fraud_review'}),
    'dealer_funded': ('in_transit', {'dealer_dispatch','carrier_insurance','bill_of_lading','pickup_condition'}),
    'in_transit': ('delivered', {'delivery_receipt','delivery_condition','tesla_app_transfer'}),
    'delivered': ('settlement_pending', {'dealer_title_to_buyer','dealer_tax_remittance','return_window_resolved','dealer_sale_statement'}),
}

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

_INVENTORY_CACHE={}
def _load_inventory(path):
    stat=path.stat()
    key=(str(path),stat.st_mtime_ns,stat.st_size)
    if _INVENTORY_CACHE.get('key')!=key:
        inv=json.loads(path.read_text())
        _INVENTORY_CACHE['key']=key
        _INVENTORY_CACHE['inv']=inv
        _INVENTORY_CACHE['vehicles']={x['vin']:x for x in inv['items']}
    return _INVENTORY_CACHE['inv'],_INVENTORY_CACHE['vehicles']

def create_app(settings=None, payments=None):
    settings=settings or Settings.from_env()
    store=Store(settings.db_path)
    payments=payments or StripePayments(settings)
    inventory,vehicles=_load_inventory(settings.inventory_path)
    app=FastAPI(title='Tesla marketplace',docs_url=None,redoc_url=None)
    app.state.store=store
    media=VehicleMedia(store,settings.sourcing_path)

    @app.middleware('http')
    async def security(request, call_next):
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and request.url.path!='/api/stripe/webhook':
            if origin and origin!=settings.origin:
                return __import__('fastapi').responses.JSONResponse({'detail':'Origin rejected'},status_code=403)
            if 'application/json' not in request.headers.get('content-type',''):
                return __import__('fastapi').responses.JSONResponse({'detail':'JSON required'},status_code=415)
        size=request.headers.get('content-length','0')
        if not size.isdigit() or int(size)>65536:
            return __import__('fastapi').responses.JSONResponse({'detail':'Request too large'},status_code=413)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    def admin(authorization: Annotated[str|None, Header()]=None):
        token=(authorization or '').removeprefix('Bearer ')
        if len(settings.admin_token)<32 or not hmac.compare_digest(token,settings.admin_token):
            raise HTTPException(401,'Operator authentication required')

    def order_access(c,order_id,authorization):
        row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
        token=(authorization or '').removeprefix('Bearer ')
        if not row or not hmac.compare_digest(digest(token),row['access_hash']):
            raise HTTPException(404,'Request not found')
        return row

    def get_order(c,order_id):
        row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
        if not row:raise HTTPException(404,'Request not found')
        return row

    def dealer_for(c,dealer_id):
        stored=c.execute('SELECT profile FROM dealers WHERE id=?',(dealer_id,)).fetchone()
        if not stored:raise HTTPException(409,'Fulfilling dealer has not been onboarded')
        dealer=Dealer.model_validate_json(stored['profile'])
        if not dealer.verified:raise HTTPException(409,'Fulfilling dealer is not approved')
        return dealer

    def dealer_for_order(c,row):
        if row['workflow_model']!='dealer_fulfillment' or not row['payment_account']:
            raise HTTPException(409,'Legacy resale order requires manual review')
        dealer=dealer_for(c,row['dealer_id'])
        if dealer.stripe_account!=row['payment_account']:
            raise HTTPException(409,'Dealer payment account changed; reconcile the existing order')
        original=json.loads(row['dealer_profile'])
        if any(original[k]!=getattr(dealer,k) for k in ('legal_name','license_number','address')):
            raise HTTPException(409,'Selling dealer identity changed; review the quote')
        return dealer

    def public(row):
        q=json.loads(row['quote']) if row['quote'] and row['workflow_model']=='dealer_fulfillment' else None
        summary=None
        if q:
            parsed=Quote.model_validate(q)
            summary={k:q[k] for k in ['vehicle_price_cents','tax_cents','title_registration_cents',
                'documentation_cents','delivery_charge_cents','valid_until']}
            profile=json.loads(row['dealer_profile'])
            summary['seller']={k:profile[k] for k in ('legal_name','license_number','address')}
            summary['inventory_owner']='fulfilling_dealer'
            summary.update(total_cents=parsed.total_cents,deposit_cents=DEPOSIT,
                balance_after_deposit_cents=parsed.total_cents-DEPOSIT,
                terms={k:q[k] for k in ['buyers_guide_reference','warranty_terms_reference','return_terms_reference','deposit_terms_reference']})
        return {'id':row['id'],'vin':row['vin'],'state':row['state'],'quote':summary,
                'quote_version':row['quote_version'],'action_due_at':row['action_due_at']}

    @app.get('/api/config')
    def config():
        with store.connect() as c:
            approved=sum(bool(json.loads(r['profile']).get('verified')) for r in c.execute('SELECT profile FROM dealers'))
        return {'mode':'dealer_fulfillment','partner_onboarding_status':'ready' if approved and settings.platform_agreements_verified else 'pending',
            'supported_states':settings.supported_states,'payments_enabled':bool(settings.payments_ready and approved),
            'deposit_cents':DEPOSIT,'requests_enabled':True,'inventory_owner':'fulfilling_dealer'}

    @app.put('/api/admin/dealers/{dealer_id}',dependencies=[Depends(admin)])
    def onboard_dealer(dealer_id:str,body:Dealer):
        if dealer_id!=body.id:raise HTTPException(409,'Dealer ID mismatch')
        with store.transaction() as c:
            c.execute('INSERT INTO dealers VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET profile=excluded.profile,updated_at=excluded.updated_at',(dealer_id,body.model_dump_json(),int(time.time())))
        return {'id':dealer_id,'verified':body.verified}

    @app.get('/api/admin/arbitrage',dependencies=[Depends(admin)])
    def arbitrage():
        path=ROOT/'.data/arbitrage_opportunities.json'
        if not path.is_file():return {'items':[]}
        data=json.loads(path.read_text())
        return {**data,'items':data.get('items',[])[:200]}

    @app.get('/api/admin/sourcing',dependencies=[Depends(admin)])
    def sourcing(vin:str|None=None):
        if not settings.sourcing_path.is_file():return {'items':[]}
        data=json.loads(settings.sourcing_path.read_text())
        rows=data.get('items',[])
        return {'items':[x for x in rows if not vin or x.get('vin')==vin][:200]}

    @app.get('/api/admin/dealers',dependencies=[Depends(admin)])
    def dealers():
        with store.connect() as c:return [json.loads(r['profile']) for r in c.execute('SELECT profile FROM dealers')]

    @app.get('/api/vehicles/{vin}/photos')
    def vehicle_photos(vin:str,request:Request):
        if vin not in vehicles:raise HTTPException(404,'Vehicle not found')
        if not store.rate_limit('media:'+digest(request.client.host if request.client else 'unknown'),limit=120):raise HTTPException(429,'Photo lookup limit reached')
        published=vehicles[vin].get('photos',[])
        shard=settings.inventory_path.parent/'media'/(format(int(vin[-3:])%128,'02x')+'.json')
        if shard.is_file():published=json.loads(shard.read_text()).get(vin,published)
        return media.gallery(vin,vehicles[vin].get('photo',''),published)

    @app.post('/api/requests',status_code=201)
    def purchase(body:PurchaseRequest,request:Request,idempotency_key:Annotated[str,Header()]):
        if not 16<=len(idempotency_key)<=100:raise HTTPException(400,'Use a unique request key')
        if body.vin not in vehicles:raise HTTPException(404,'Vehicle not in published inventory')
        expires=vehicles[body.vin].get('expires_at')
        if expires and datetime.fromisoformat(expires).timestamp()<=time.time():raise HTTPException(409,'This source snapshot has expired; refresh the vehicle first')
        if not store.rate_limit(digest(request.client.host if request.client else 'unknown')):
            raise HTTPException(429,'Too many requests. Try again later.')
        raw=body.model_dump_json();request_hash=digest(raw);now=int(time.time())
        # Token derivation permits an idempotent retry without storing a plaintext bearer token.
        token=hmac.new(idempotency_key.encode(),raw.encode(),hashlib.sha256).hexdigest()
        with store.transaction() as c:
            row=c.execute('SELECT * FROM orders WHERE request_key=?',(digest(idempotency_key),)).fetchone()
            if row:
                if row['request_hash']!=request_hash:raise HTTPException(409,'Request key already used')
                return {**public(row),'access_token':token}
            store.expire(c,now)
            if c.execute('SELECT 1 FROM holds WHERE vin=?',(body.vin,)).fetchone():
                raise HTTPException(409,'This vehicle is already reserved or sold. Choose another listing.')
            order_id=str(uuid.uuid4())
            c.execute('INSERT INTO orders(id,access_hash,request_key,request_hash,vin,customer,state,created_at,updated_at,action_due_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',(order_id,digest(token),digest(idempotency_key),request_hash,body.vin,raw,'requested',now,now,now+86400))
            c.execute("UPDATE orders SET workflow_model='dealer_fulfillment' WHERE id=?",(order_id,))
            store.event(c,order_id,'request_received',{'vin':body.vin,'demand_channel':body.demand_channel,'campaign_id':body.campaign_id},True)
            return {**public(get_order(c,order_id)),'access_token':token}

    @app.get('/api/orders/{order_id}')
    def status(order_id:str,authorization:Annotated[str|None,Header()]=None):
        with store.transaction() as c:
            store.expire(c,int(time.time()))
            row=order_access(c,order_id,authorization)
            actions=[{'kind':x['kind'],'url':x['url']} for x in c.execute('SELECT * FROM online_actions WHERE order_id=?',(order_id,)) if row['state'] in ONLINE_STATES[x['kind']]]
            return {**public(row),'online_actions':actions}

    @app.post('/api/orders/{order_id}/privacy')
    def privacy(order_id:str,authorization:Annotated[str|None,Header()]=None):
        with store.transaction() as c:
            row=order_access(c,order_id,authorization)
            store.event(c,order_id,'privacy_deletion_requested',{},True)
        return {'recorded':True}

    @app.get('/api/admin/orders',dependencies=[Depends(admin)])
    def work_queue():
        with store.transaction() as c:
            store.expire(c,int(time.time()))
            return [dict(r) for r in c.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT 200')]

    @app.get('/api/admin/outbox',dependencies=[Depends(admin)])
    def outbox():
        with store.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM outbox WHERE acknowledged_at IS NULL ORDER BY id LIMIT 200')]

    @app.post('/api/admin/outbox/{event_id}/ack',dependencies=[Depends(admin)])
    def acknowledge(event_id:int):
        with store.transaction() as c:
            if not c.execute('UPDATE outbox SET acknowledged_at=? WHERE id=?',(int(time.time()),event_id)).rowcount:
                raise HTTPException(404,'Notification not found')
        return {'acknowledged':True}

    @app.post('/api/admin/orders/{order_id}/quote',dependencies=[Depends(admin)])
    def quote(order_id:str,body:Quote):
        if not settings.platform_agreements_verified:raise HTTPException(409,'Platform transaction agreements are pending')
        now=int(time.time())
        if body.valid_until<now+1900:raise HTTPException(409,'Quote and seller hold need at least 32 minutes remaining')
        if body.contribution_cents<settings.min_contribution_cents:raise HTTPException(409,'Quote fails contribution requirement')
        if body.total_cents<DEPOSIT:raise HTTPException(409,'Deposit exceeds total')
        with store.transaction() as c:
            row=get_order(c,order_id)
            if row['state'] not in ('requested','quoted','quote_expired'):raise HTTPException(409,'Order cannot be requoted')
            dealer=dealer_for(c,body.dealer_id)
            customer=json.loads(row['customer'])
            if customer.get('state') not in dealer.supported_states or customer.get('state') not in settings.supported_states:raise HTTPException(409,'Destination is not supported')
            c.execute("UPDATE orders SET quote=?,quote_version=quote_version+1,state='quoted',checkout_id=NULL,updated_at=?,action_due_at=? WHERE id=?",(body.model_dump_json(),now,body.valid_until,order_id))
            c.execute("UPDATE orders SET workflow_model='dealer_fulfillment',dealer_id=?,payment_account=?,dealer_profile=? WHERE id=?",(dealer.id,dealer.stripe_account,dealer.model_dump_json(),order_id))
            c.execute('INSERT INTO source_holds VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET expires_at=excluded.expires_at,reference=excluded.reference',(order_id,body.seller_hold_until,body.seller_hold_reference))
            store.event(c,order_id,'quote_approved',{'contribution_cents':body.contribution_cents,'expected_spread_cents':body.spread_cents,'dealer_id':dealer.id},True)
            return public(get_order(c,order_id))

    @app.post('/api/orders/{order_id}/checkout')
    def checkout(order_id:str,body:CheckoutAcceptance,request:Request,authorization:Annotated[str|None,Header()]=None):
        if not settings.payments_ready:raise HTTPException(409,'Partner checkout is not yet configured')
        now=int(time.time())
        with store.transaction() as c:
            store.expire(c,now)
            row=order_access(c,order_id,authorization)
            if row['state'] not in ('quoted','checkout_pending'):raise HTTPException(409,'A verified quote is required')
            dealer=dealer_for_order(c,row)
            destination=json.loads(row['customer']).get('state')
            if destination not in dealer.supported_states or destination not in settings.supported_states:raise HTTPException(409,'Destination is no longer supported')
            try:capable=payments.dealer_can_charge(row['payment_account'])
            except Exception:raise HTTPException(503,'Dealer payment capability could not be verified')
            if not capable:raise HTTPException(409,'Dealer payment account cannot accept charges')
            q=Quote.model_validate_json(row['quote'])
            if body.quote_version!=row['quote_version']:raise HTTPException(409,'Quote changed; review the current quote')
            if min(q.valid_until,q.seller_hold_until)<now+1900:raise HTTPException(409,'Quote needs renewal')
            try:
                c.execute('INSERT INTO holds(vin,order_id,expires_at) VALUES(?,?,?) ON CONFLICT(order_id) DO NOTHING',(row['vin'],order_id,now+1800))
            except sqlite3.IntegrityError:raise HTTPException(409,'Another customer currently holds this vehicle')
            if row['checkout_id']:
                try:session=payments.retrieve_checkout(row['checkout_id'],row['payment_account'])
                except Exception:raise HTTPException(503,'Payment provider unavailable; retry safely')
                if session.get('status')!='open':raise HTTPException(409,'Checkout is no longer open; check order status')
                return {'url':session['url']}
            try:session=payments.create_checkout(dict(row),q,now+1800)
            except Exception:raise HTTPException(503,'Payment provider unavailable; retry safely')
            c.execute("UPDATE orders SET state='checkout_pending',checkout_id=?,updated_at=?,action_due_at=? WHERE id=?",(session['id'],now,now+1800,order_id))
            store.event(c,order_id,'checkout_created',{'session_id':session['id'],'accepted_quote_version':body.quote_version,'terms_accepted_at':now})
            return {'url':session['url']}

    @app.post('/api/stripe/webhook')
    async def webhook(request:Request):
        if not settings.webhook_secret:raise HTTPException(503,'Webhook verification is not configured')
        raw=await request.body()
        if len(raw)>65536:raise HTTPException(413,'Request too large')
        try:event=payments.verify_event(raw,request.headers.get('stripe-signature',''))
        except Exception:raise HTTPException(400,'Invalid webhook signature')
        kind=event['type'];obj=event['data']['object'];now=int(time.time())
        # Fetch canonical provider data; URL parameters never mutate payment state.
        session=None
        if kind in ('checkout.session.completed','checkout.session.async_payment_succeeded'):
            with store.connect() as lookup:
                bound=lookup.execute('SELECT payment_account FROM orders WHERE checkout_id=?',(obj['id'],)).fetchone()
            if not bound or not event.get('account') or event['account']!=bound['payment_account']:
                raise HTTPException(409,'Webhook account does not match the fulfilling dealer')
            try:session=payments.retrieve_checkout(obj['id'],bound['payment_account'])
            except Exception:raise HTTPException(503,'Payment verification unavailable')
        with store.transaction() as c:
            if c.execute('SELECT 1 FROM stripe_events WHERE id=?',(event['id'],)).fetchone():return {'received':True}
            if session:
                row=c.execute('SELECT * FROM orders WHERE checkout_id=?',(session['id'],)).fetchone()
                if not row:raise HTTPException(409,'Unknown checkout session')
                meta=session.get('metadata',{})
                valid=(session.get('payment_status')=='paid' and session.get('amount_total')==DEPOSIT
                    and session.get('currency')=='usd' and session.get('mode')=='payment'
                    and meta.get('order_id')==row['id'] and meta.get('quote_version')==str(row['quote_version'])
                    and bool(session.get('livemode'))==settings.stripe_key.startswith('sk_live_') and session.get('payment_intent'))
                if not valid:raise HTTPException(409,'Payment does not match this order')
                if row['payment_id']:
                    if row['payment_id']!=session['payment_intent']:raise HTTPException(409,'Different payment already recorded')
                else:
                    q=Quote.model_validate_json(row['quote']);hold=c.execute('SELECT * FROM holds WHERE order_id=?',(row['id'],)).fetchone()
                    partner=c.execute('SELECT profile FROM dealers WHERE id=?',(row['dealer_id'],)).fetchone()
                    partner_valid=bool(partner and json.loads(partner['profile']).get('verified') and json.loads(partner['profile']).get('stripe_account')==row['payment_account'])
                    usable=(partner_valid and settings.payments_ready and row['state']=='checkout_pending' and hold and hold['expires_at']>now
                        and min(q.valid_until,q.seller_hold_until)>now)
                    state='deposit_paid' if usable else 'refund_pending'
                    c.execute('UPDATE orders SET state=?,payment_id=?,updated_at=?,action_due_at=? WHERE id=?',(state,session['payment_intent'],now,now+86400,row['id']))
                    if usable:c.execute('UPDATE holds SET expires_at=NULL WHERE order_id=?',(row['id'],))
                    else:c.execute('DELETE FROM holds WHERE order_id=?',(row['id'],))
                    store.event(c,row['id'],state,{'payment_id':session['payment_intent']},True)
            elif kind=='checkout.session.expired':
                row=c.execute('SELECT * FROM orders WHERE checkout_id=?',(obj['id'],)).fetchone()
                if row and row['payment_account']!=event.get('account'):raise HTTPException(409,'Webhook account mismatch')
                if row and row['state']=='checkout_pending':
                    c.execute("UPDATE orders SET state='quote_expired',updated_at=? WHERE id=?",(now,row['id']))
                    c.execute('DELETE FROM holds WHERE order_id=?',(row['id'],))
                    store.event(c,row['id'],'checkout_expired',{},True)
            elif kind in ('refund.updated','refund.created'):
                row=c.execute('SELECT * FROM orders WHERE payment_id=?',(obj.get('payment_intent',''),)).fetchone()
                if row and row['payment_account']!=event.get('account'):raise HTTPException(409,'Webhook account mismatch')
                if row and obj.get('amount')==DEPOSIT and obj.get('status')=='succeeded':
                    if row['state']=='refund_pending':
                        c.execute("UPDATE orders SET state='refunded',updated_at=? WHERE id=?",(now,row['id']))
                        c.execute('DELETE FROM holds WHERE order_id=?',(row['id'],))
                        store.event(c,row['id'],'refund_completed',{'refund_id':obj['id']},True)
                    elif row['state']!='refunded':
                        c.execute("UPDATE orders SET state='payment_review',updated_at=? WHERE id=?",(now,row['id']))
                        store.event(c,row['id'],'unexpected_refund',{'refund_id':obj['id']},True)
            elif kind=='charge.dispute.created':
                row=c.execute('SELECT * FROM orders WHERE payment_id=?',(obj.get('payment_intent',''),)).fetchone()
                if row and row['payment_account']!=event.get('account'):raise HTTPException(409,'Webhook account mismatch')
                if row:
                    c.execute("UPDATE orders SET state='payment_review',updated_at=? WHERE id=?",(now,row['id']))
                    store.event(c,row['id'],'dispute_received',{'dispute_id':obj['id']},True)
            c.execute('INSERT INTO stripe_events VALUES(?,?)',(event['id'],now))
        return {'received':True}

    @app.post('/api/orders/{order_id}/cancel')
    def cancel(order_id:str,body:Cancellation,authorization:Annotated[str|None,Header()]=None):
        now=int(time.time())
        with store.transaction() as c:
            row=order_access(c,order_id,authorization)
            if row['state'] in ('cancelled','refunded','refund_pending'):return public(row)
            if row['state'] in TRANSITIONS and row['state']!='deposit_paid':
                store.event(c,order_id,'cancellation_review_requested',{'reason':body.reason},True)
                return {'state':row['state'],'message':'Cancellation requires review of the signed purchase terms.'}
            if row['state'] not in ('requested','quoted','quote_expired','checkout_pending','deposit_paid'):
                raise HTTPException(409,'Contact the dealership to resolve this order')
            state='refund_pending' if row['payment_id'] else 'cancelled'
            c.execute('UPDATE orders SET state=?,updated_at=? WHERE id=?',(state,now,order_id))
            # Keep unpaid checkout lock until provider expiration; late payments trigger refund_pending.
            if not row['checkout_id'] or row['payment_id']:c.execute('DELETE FROM holds WHERE order_id=?',(order_id,))
            store.event(c,order_id,'cancellation_requested',{'reason':body.reason,'state':state},True)
            return public(get_order(c,order_id))

    @app.post('/api/admin/orders/{order_id}/refund',dependencies=[Depends(admin)])
    def refund(order_id:str):
        with store.transaction() as c:
            row=get_order(c,order_id)
            if row['state']=='refunded':return public(row)
            if row['workflow_model']!='dealer_fulfillment' or not row['payment_account']:raise HTTPException(409,'Legacy payment requires manual review')
            if row['state']!='refund_pending' or not row['payment_id']:raise HTTPException(409,'No pending deposit refund')
            try:result=payments.refund(dict(row))
            except Exception:raise HTTPException(503,'Refund failed; retry with the same order')
            if result.get('amount')!=DEPOSIT or result.get('payment_intent')!=row['payment_id']:
                raise HTTPException(409,'Refund does not match payment')
            if result['status']=='succeeded':
                c.execute("UPDATE orders SET state='refunded',updated_at=? WHERE id=?",(int(time.time()),order_id))
                c.execute('DELETE FROM holds WHERE order_id=?',(order_id,))
            store.event(c,order_id,'refund_submitted',{'refund_id':result['id'],'status':result['status']},True)
            return public(get_order(c,order_id))

    @app.post('/api/admin/orders/{order_id}/transition',dependencies=[Depends(admin)])
    def transition(order_id:str,body:Transition):
        if not settings.platform_agreements_verified:raise HTTPException(409,'Platform transaction agreements are pending')
        with store.transaction() as c:
            row=get_order(c,order_id);dealer_for_order(c,row);rule=TRANSITIONS.get(row['state'])
            if not rule or body.state!=rule[0]:raise HTTPException(409,'Invalid order transition')
            if body.state in ('dealer_confirmed','dealer_funded','in_transit'):
                hold=c.execute('SELECT expires_at FROM source_holds WHERE order_id=?',(order_id,)).fetchone()
                if not hold or hold['expires_at']<=int(time.time()):raise HTTPException(409,'Source dealer hold expired; reconfirm before proceeding')
            if any(len(body.evidence.get(key,'').strip())<5 for key in rule[1]):
                raise HTTPException(409,'Required transaction evidence is missing')
            c.execute('UPDATE orders SET state=?,updated_at=?,action_due_at=? WHERE id=?',(body.state,int(time.time()),int(time.time())+86400,order_id))
            store.event(c,order_id,body.state,body.evidence,True)
            return public(get_order(c,order_id))

    @app.post('/api/admin/orders/{order_id}/online-actions',dependencies=[Depends(admin)])
    def online_action(order_id:str,body:OnlineAction):
        from urllib.parse import urlsplit
        url=urlsplit(body.url)
        with store.transaction() as c:
            row=get_order(c,order_id);dealer=dealer_for_order(c,row)
            if row['state'] not in ONLINE_STATES[body.kind]:raise HTTPException(409,'This online step is not available yet')
            if url.scheme!='https' or url.hostname not in dealer.online_portal_hosts or url.username or url.password:
                raise HTTPException(409,'Use an approved secure dealer portal')
            c.execute('INSERT INTO online_actions VALUES(?,?,?,?) ON CONFLICT(order_id,kind) DO UPDATE SET url=excluded.url,evidence_reference=excluded.evidence_reference',(order_id,body.kind,body.url,body.evidence_reference))
            store.event(c,order_id,'online_step_ready',{'kind':body.kind},True)
        return {'ready':True}

    @app.post('/api/admin/orders/{order_id}/settle',dependencies=[Depends(admin)])
    def settle(order_id:str,body:Settlement):
        with store.transaction() as c:
            row=get_order(c,order_id)
            if row['workflow_model']!='dealer_fulfillment':raise HTTPException(409,'Legacy resale order requires review')
            existing=c.execute('SELECT * FROM settlements WHERE order_id=?',(order_id,)).fetchone()
            if existing:
                if json.loads(existing['evidence'])!=body.model_dump():raise HTTPException(409,'Settlement already recorded with different evidence')
                return public(row)
            if row['state']!='settlement_pending':raise HTTPException(409,'Dealer fulfillment must finish before spread settlement')
            q=Quote.model_validate_json(row['quote'])
            if body.received_cents+body.adjustment_cents!=q.spread_cents:raise HTTPException(409,'Dealer remittance does not reconcile to the agreed spread')
            now=int(time.time())
            try:c.execute('INSERT INTO settlement_receipts VALUES(?,?)',(body.receipt_reference,order_id))
            except sqlite3.IntegrityError:raise HTTPException(409,'Receipt reference was already used for another order')
            c.execute('INSERT INTO settlements VALUES(?,?,?,?,?,?,?)',(order_id,q.spread_cents,body.received_cents,body.adjustment_cents,body.actual_platform_cost_cents,body.model_dump_json(),now))
            c.execute("UPDATE orders SET state='completed',updated_at=? WHERE id=?",(now,order_id))
            store.event(c,order_id,'spread_settled',{'received_cents':body.received_cents,'actual_contribution_cents':body.received_cents-body.actual_platform_cost_cents},True)
            return public(get_order(c,order_id))

    @app.post('/api/admin/orders/{order_id}/settlement-reversal',dependencies=[Depends(admin)])
    def reverse_settlement(order_id:str,body:SettlementReversal):
        with store.transaction() as c:
            row=c.execute('SELECT * FROM settlements WHERE order_id=?',(order_id,)).fetchone()
            if not row:raise HTTPException(409,'No received spread to reverse')
            prior=c.execute('SELECT * FROM settlement_reversals WHERE reference=?',(body.reference,)).fetchone()
            if prior:
                if prior['order_id']!=order_id or prior['amount_cents']!=body.amount_cents:raise HTTPException(409,'Reversal reference already used')
                return {'recorded':True}
            reversed_cents=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM settlement_reversals WHERE order_id=?',(order_id,)).fetchone()[0]
            if reversed_cents+body.amount_cents>row['received_cents']:raise HTTPException(409,'Cannot reverse more spread than was received')
            c.execute('INSERT INTO settlement_reversals VALUES(?,?,?,?)',(body.reference,order_id,body.amount_cents,int(time.time())))
            store.event(c,order_id,'spread_reversed',body.model_dump(),True)
        return {'recorded':True}

    @app.get('/api/admin/economics',dependencies=[Depends(admin)])
    def economics():
        with store.connect() as c:
            rows=c.execute('SELECT o.customer,s.*,(SELECT COALESCE(SUM(r.amount_cents),0) FROM settlement_reversals r WHERE r.order_id=s.order_id) AS reversed_cents FROM settlements s JOIN orders o ON o.id=s.order_id').fetchall()
        channels={}
        for row in rows:
            channel=json.loads(row['customer']).get('demand_channel','direct')
            stats=channels.setdefault(channel,{'settled_sales':0,'spread_received_cents':0,'spread_reversed_cents':0,'net_spread_cents':0,'actual_platform_cost_cents':0,'contribution_cents':0})
            stats['settled_sales']+=1;stats['spread_received_cents']+=row['received_cents'];stats['actual_platform_cost_cents']+=row['actual_platform_cost_cents'];stats['spread_reversed_cents']+=row['reversed_cents'];stats['net_spread_cents']+=row['received_cents']-row['reversed_cents'];stats['contribution_cents']+=row['received_cents']-row['reversed_cents']-row['actual_platform_cost_cents']
        return {'basis':'dealer remittances, not vehicle GMV or refundable deposits','channels':channels}

    @app.post('/api/admin/orders/{order_id}/access',dependencies=[Depends(admin)])
    def recover_access(order_id:str,body:AccessRecovery):
        token=secrets.token_urlsafe(32)
        with store.transaction() as c:
            row=get_order(c,order_id)
            if row['customer']=='{}':raise HTTPException(409,'Personal data has been removed')
            c.execute('UPDATE orders SET access_hash=? WHERE id=?',(digest(token),order_id))
            store.event(c,order_id,'customer_access_recovered',body.model_dump(),True)
        return {'id':order_id,'access_token':token}

    @app.post('/api/admin/orders/{order_id}/hold',dependencies=[Depends(admin)])
    def renew_source_hold(order_id:str,body:SellerHold):
        if body.expires_at<=int(time.time()):raise HTTPException(409,'Hold must extend into the future')
        with store.transaction() as c:
            row=get_order(c,order_id)
            if row['state'] not in ('deposit_paid','dealer_confirmed','dealer_funded'):raise HTTPException(409,'Hold cannot be renewed in this state')
            c.execute('INSERT INTO source_holds VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET expires_at=excluded.expires_at,reference=excluded.reference',(order_id,body.expires_at,body.reference))
            store.event(c,order_id,'source_hold_reconfirmed',body.model_dump(),True)
        return {'renewed':True}

    @app.post('/api/orders/{order_id}/cases',status_code=201)
    def customer_case(order_id:str,body:CustomerCase,authorization:Annotated[str|None,Header()]=None):
        with store.transaction() as c:
            order_access(c,order_id,authorization)
            if c.execute("SELECT count(*) FROM cases WHERE order_id=? AND status!='resolved'",(order_id,)).fetchone()[0]>=5:
                raise HTTPException(409,'Please use the existing open case')
            case_id=str(uuid.uuid4());now=int(time.time())
            c.execute('INSERT INTO cases(id,order_id,kind,description,status,created_at,due_at) VALUES(?,?,?,?,?,?,?)',(case_id,order_id,body.kind,body.description,'open',now,now+86400))
            store.event(c,order_id,'customer_case_opened',{'case_id':case_id,'kind':body.kind},True)
            return {'id':case_id,'status':'open'}

    @app.get('/api/admin/cases',dependencies=[Depends(admin)])
    def cases():
        with store.connect() as c:return [dict(r) for r in c.execute("SELECT * FROM cases WHERE status!='resolved' ORDER BY due_at LIMIT 200")]

    @app.post('/api/admin/cases/{case_id}',dependencies=[Depends(admin)])
    def resolve_case(case_id:str,body:CaseResolution):
        with store.transaction() as c:
            row=c.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if not row:raise HTTPException(404,'Case not found')
            if row['status']=='resolved':raise HTTPException(409,'Case already resolved')
            c.execute('UPDATE cases SET status=?,owner=?,evidence=? WHERE id=?',(body.status,body.owner,body.evidence,case_id))
            store.event(c,row['order_id'],'customer_case_'+body.status,{'case_id':case_id,**body.model_dump()},True)
            return {'status':body.status}

    @app.post('/api/admin/privacy/purge',dependencies=[Depends(admin)])
    def purge_inactive_requests():
        # Transaction evidence has separate retention duties; only inactive, unpaid leads are anonymized.
        cutoff=int(time.time())-settings.retention_days*86400
        with store.transaction() as c:
            rows=c.execute("SELECT id FROM orders WHERE payment_id IS NULL AND state IN ('requested','quoted','quote_expired','cancelled') AND updated_at<? AND customer!='{}'",(cutoff,)).fetchall()
            for row in rows:
                c.execute("UPDATE orders SET customer='{}',access_hash='',request_hash='' WHERE id=?",(row['id'],))
                store.event(c,row['id'],'personal_data_purged')
        return {'anonymized':len(rows)}

    @app.get('/healthz')
    def health():return {'ok':True}

    # Explicit public assets only. Never expose .data, source files, or configuration.
    app.mount('/web',StaticFiles(directory=ROOT/'web'),name='assets')
    if (settings.inventory_path.parent/'media').is_dir():
        app.mount('/media',StaticFiles(directory=settings.inventory_path.parent/'media'),name='vehicle-photos')
    @app.get('/inventory.json')
    def published_inventory():
        with store.transaction() as c:
            store.expire(c,int(time.time()))
            occupied={r[0] for r in c.execute('SELECT vin FROM holds')}
        items=[x for x in inventory['items'] if x['vin'] not in occupied and (not x.get('expires_at') or datetime.fromisoformat(x['expires_at']).timestamp()>time.time())]
        from .catalog import public_catalog
        return public_catalog({**inventory,'meta':{**inventory.get('meta',{}),'count':len(items)},'items':items})
    @app.get('/data/us_zip_centers.json')
    def zip_centers():return FileResponse(ROOT/'data/us_zip_centers.json',media_type='application/json')
    @app.get('/sitemap.xml')
    def sitemap():return FileResponse(ROOT/'sitemap.xml',media_type='application/xml')
    @app.get('/robots.txt')
    def robots():return FileResponse(ROOT/'robots.txt',media_type='text/plain')
    @app.get('/')
    def home():return FileResponse(ROOT/'index.html')
    @app.get('/{group}/{slug}.html')
    def category(group:str,slug:str):
        if group not in ('models','years','states') or not slug.replace('-','').isalnum():raise HTTPException(404)
        path=ROOT/group/(slug+'.html')
        if not path.is_file():raise HTTPException(404)
        return FileResponse(path)
    return app

app=create_app()
