from pathlib import Path
from typing import Annotated
import hashlib, hmac, json, secrets, sqlite3, time, uuid
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .config import Settings, ROOT
from .models import PurchaseRequest, Quote, Transition, Cancellation, CheckoutAcceptance, SellerHold, CustomerCase, CaseResolution, AccessRecovery
from .store import Store
from .payments import StripePayments

DEPOSIT = 25000
TRANSITIONS = {
    'deposit_paid': ('contracted', {'signed_purchase_agreement','identity_check','deposit_reconciled'}),
    'contracted': ('funded', {'cleared_balance','funding_reference','fraud_review'}),
    'funded': ('purchased', {'source_bill_of_sale','title_chain','lien_release','acquisition_payment'}),
    'purchased': ('in_transit', {'carrier_insurance','bill_of_lading','pickup_condition','dispatch_reference'}),
    'in_transit': ('delivered', {'delivery_receipt','delivery_condition','tesla_app_transfer'}),
    'delivered': ('completed', {'title_registration','tax_remittance','return_window_resolved','final_reconciliation'}),
}

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def create_app(settings=None, payments=None):
    settings=settings or Settings.from_env()
    store=Store(settings.db_path)
    payments=payments or StripePayments(settings)
    inventory=json.loads(settings.inventory_path.read_text())
    vehicles={x['vin']:x for x in inventory['items']}
    app=FastAPI(title='Tesla marketplace',docs_url=None,redoc_url=None)
    app.state.store=store

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

    def public(row):
        q=json.loads(row['quote']) if row['quote'] else None
        summary=None
        if q:
            parsed=Quote.model_validate(q)
            summary={k:q[k] for k in ['vehicle_price_cents','tax_cents','title_registration_cents',
                'documentation_cents','delivery_charge_cents','valid_until']}
            summary.update(total_cents=parsed.total_cents,deposit_cents=DEPOSIT,
                balance_after_deposit_cents=parsed.total_cents-DEPOSIT,
                terms={k:q[k] for k in ['buyers_guide_reference','warranty_terms_reference','return_terms_reference','deposit_terms_reference']})
        return {'id':row['id'],'vin':row['vin'],'state':row['state'],'quote':summary,
                'quote_version':row['quote_version'],'action_due_at':row['action_due_at']}

    @app.get('/api/config')
    def config():
        return {'mode':'own_dealership','license_status':'verified' if settings.dealer_ready else 'pending',
            'dealer':{'name':settings.dealer_name,'gdn':settings.dealer_gdn,'address':settings.dealer_address} if settings.dealer_ready else None,
            'supported_states':settings.supported_states,'payments_enabled':settings.payments_ready,
            'deposit_cents':DEPOSIT,'requests_enabled':True}

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
                raise HTTPException(409,'This vehicle is already reserved or purchased. Choose another listing.')
            order_id=str(uuid.uuid4())
            c.execute('INSERT INTO orders(id,access_hash,request_key,request_hash,vin,customer,state,created_at,updated_at,action_due_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',(order_id,digest(token),digest(idempotency_key),request_hash,body.vin,raw,'requested',now,now,now+86400))
            store.event(c,order_id,'request_received',{'vin':body.vin},True)
            return {**public(get_order(c,order_id)),'access_token':token}

    @app.get('/api/orders/{order_id}')
    def status(order_id:str,authorization:Annotated[str|None,Header()]=None):
        with store.transaction() as c:
            store.expire(c,int(time.time()))
            return public(order_access(c,order_id,authorization))

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
        if not settings.dealer_ready:raise HTTPException(409,'Dealership licensing is pending')
        now=int(time.time())
        if body.valid_until<now+1900:raise HTTPException(409,'Quote and seller hold need at least 32 minutes remaining')
        if body.contribution_cents<settings.min_contribution_cents:raise HTTPException(409,'Quote fails contribution requirement')
        if body.total_cents<DEPOSIT:raise HTTPException(409,'Deposit exceeds total')
        with store.transaction() as c:
            row=get_order(c,order_id)
            if row['state'] not in ('requested','quoted','quote_expired'):raise HTTPException(409,'Order cannot be requoted')
            customer=json.loads(row['customer'])
            if customer.get('state') not in settings.supported_states:raise HTTPException(409,'Destination is not supported')
            c.execute("UPDATE orders SET quote=?,quote_version=quote_version+1,state='quoted',checkout_id=NULL,updated_at=?,action_due_at=? WHERE id=?",(body.model_dump_json(),now,body.valid_until,order_id))
            c.execute('INSERT INTO source_holds VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET expires_at=excluded.expires_at,reference=excluded.reference',(order_id,body.seller_hold_until,body.seller_hold_reference))
            store.event(c,order_id,'quote_approved',{'contribution_cents':body.contribution_cents},True)
            return public(get_order(c,order_id))

    @app.post('/api/orders/{order_id}/checkout')
    def checkout(order_id:str,body:CheckoutAcceptance,request:Request,authorization:Annotated[str|None,Header()]=None):
        if not settings.payments_ready:raise HTTPException(409,'Paid checkout is unavailable while dealership setup is pending')
        now=int(time.time())
        with store.transaction() as c:
            store.expire(c,now)
            row=order_access(c,order_id,authorization)
            if row['state'] not in ('quoted','checkout_pending'):raise HTTPException(409,'A verified quote is required')
            q=Quote.model_validate_json(row['quote'])
            if body.quote_version!=row['quote_version']:raise HTTPException(409,'Quote changed; review the current quote')
            if min(q.valid_until,q.seller_hold_until)<now+1900:raise HTTPException(409,'Quote needs renewal')
            try:
                c.execute('INSERT INTO holds(vin,order_id,expires_at) VALUES(?,?,?) ON CONFLICT(order_id) DO NOTHING',(row['vin'],order_id,now+1800))
            except sqlite3.IntegrityError:raise HTTPException(409,'Another customer currently holds this vehicle')
            if row['checkout_id']:
                try:session=payments.retrieve_checkout(row['checkout_id'])
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
            try:session=payments.retrieve_checkout(obj['id'])
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
                    usable=(settings.payments_ready and row['state']=='checkout_pending' and hold and hold['expires_at']>now
                        and min(q.valid_until,q.seller_hold_until)>now)
                    state='deposit_paid' if usable else 'refund_pending'
                    c.execute('UPDATE orders SET state=?,payment_id=?,updated_at=?,action_due_at=? WHERE id=?',(state,session['payment_intent'],now,now+86400,row['id']))
                    if usable:c.execute('UPDATE holds SET expires_at=NULL WHERE order_id=?',(row['id'],))
                    else:c.execute('DELETE FROM holds WHERE order_id=?',(row['id'],))
                    store.event(c,row['id'],state,{'payment_id':session['payment_intent']},True)
            elif kind=='checkout.session.expired':
                row=c.execute('SELECT * FROM orders WHERE checkout_id=?',(obj['id'],)).fetchone()
                if row and row['state']=='checkout_pending':
                    c.execute("UPDATE orders SET state='quote_expired',updated_at=? WHERE id=?",(now,row['id']))
                    c.execute('DELETE FROM holds WHERE order_id=?',(row['id'],))
                    store.event(c,row['id'],'checkout_expired',{},True)
            elif kind in ('refund.updated','refund.created'):
                row=c.execute('SELECT * FROM orders WHERE payment_id=?',(obj.get('payment_intent',''),)).fetchone()
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
        if body.state in ('contracted','purchased') and not settings.dealer_ready:raise HTTPException(409,'Dealership authority must be confirmed')
        with store.transaction() as c:
            row=get_order(c,order_id);rule=TRANSITIONS.get(row['state'])
            if not rule or body.state!=rule[0]:raise HTTPException(409,'Invalid order transition')
            if body.state in ('contracted','funded','purchased'):
                hold=c.execute('SELECT expires_at FROM source_holds WHERE order_id=?',(order_id,)).fetchone()
                if not hold or hold['expires_at']<=int(time.time()):raise HTTPException(409,'Source dealer hold expired; reconfirm before proceeding')
            if any(len(body.evidence.get(key,'').strip())<5 for key in rule[1]):
                raise HTTPException(409,'Required transaction evidence is missing')
            c.execute('UPDATE orders SET state=?,updated_at=?,action_due_at=? WHERE id=?',(body.state,int(time.time()),int(time.time())+86400,order_id))
            store.event(c,order_id,body.state,body.evidence,True)
            return public(get_order(c,order_id))

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
            if row['state'] not in ('deposit_paid','contracted','funded'):raise HTTPException(409,'Hold cannot be renewed in this state')
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
    @app.get('/inventory.json')
    def published_inventory():
        with store.transaction() as c:
            store.expire(c,int(time.time()))
            occupied={r[0] for r in c.execute('SELECT vin FROM holds')}
        items=[x for x in inventory['items'] if x['vin'] not in occupied and (not x.get('expires_at') or datetime.fromisoformat(x['expires_at']).timestamp()>time.time())]
        return {**inventory,'meta':{**inventory.get('meta',{}),'count':len(items)},'items':items}
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
