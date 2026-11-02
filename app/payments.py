import re
import stripe
stripe.default_http_client = stripe.new_default_http_client(timeout=10)
stripe.api_version = '2026-03-25.dahlia'

def _as_dict(resource):
    return resource.to_dict() if hasattr(resource, 'to_dict') else dict(resource)

class StripePayments:
    def __init__(self, settings):
        self.settings = settings

    def _platform_pin(self):
        pin=getattr(self.settings,'stripe_platform_account','')
        return pin if isinstance(pin,str) and re.fullmatch(r'acct_[A-Za-z0-9]+',pin) else None

    def _scope(self, account, *, new_checkout=False):
        if not isinstance(account,str) or not re.fullmatch(r'acct_[A-Za-z0-9]+',account):
            raise ValueError('A valid bound payment account is required')
        mode=getattr(self.settings,'deposit_collection_mode','dealer_direct')
        if mode not in {'dealer_direct','platform'}:raise ValueError('Unknown deposit collection mode')
        pin=self._platform_pin()
        if mode=='platform' and not pin:raise ValueError('Platform deposit account pin is not configured')
        if new_checkout:
            if mode=='platform' and account!=pin:
                raise ValueError('Platform checkout account does not match its configured pin')
            if mode=='dealer_direct' and pin and account==pin:
                raise ValueError('Dealer-direct checkout cannot charge the platform deposit account')
        # Existing orders retain their exact account scope after collection mode changes.
        if pin and account==pin:return {'api_key':self.settings.stripe_key}
        return {'api_key':self.settings.stripe_key,'stripe_account':account}

    def create_checkout(self, order, quote, expires_at):
        scope=self._scope(order['payment_account'],new_checkout=True)
        platform=getattr(self.settings,'deposit_collection_mode','dealer_direct')=='platform'
        collector=getattr(self.settings,'platform_collection_legal_name','')
        if platform and (not isinstance(collector,str) or not collector.strip()):
            raise ValueError('Platform collector legal name is not configured')
        if platform and not self.dealer_can_charge(order['payment_account']):
            raise ValueError('Platform payment account identity or charging capability is not verified')
        capture_method=order.get('deposit_capture_method',getattr(self.settings,'deposit_capture_method','automatic'))
        if capture_method not in ('automatic','manual'):raise ValueError('Invalid deposit capture method')
        manual=capture_method=='manual'
        methods=list(self.settings.payment_method_types)
        if manual and methods!=['card']:raise ValueError('Manual reservation holds require card payments')
        message=(f'Authorized by {collector.strip()} for Volts & VINs. '
                 'This $250 card hold is not charged now. Uncaptured holds are released under the reservation terms.' if manual else
                 f'Charged by {collector.strip()} for Volts & VINs. This $250 reservation deposit is refundable under the accepted reservation terms.')
        branding=({'branding_settings':{'display_name':'Volts & VINs'},
            'custom_text':{'submit':{'message':message}}} if platform else {})
        presentation=({'ui_mode':'embedded_page','redirect_on_completion':'never'}
            if self.settings.checkout_ui_mode=='embedded_page' else {
                'ui_mode':'hosted_page','success_url':self.settings.origin+'/?checkout=returned',
                'cancel_url':self.settings.origin+'/?checkout=cancelled'})
        options={'payment_method_options':{'us_bank_account':{'financial_connections':{'permissions':['payment_method']},'verification_method':'automatic'}}} if 'us_bank_account' in methods else {}
        metadata={'order_id':order['id'],'quote_version':str(order['quote_version']),'vin':order['vin'],
                  'payment_stage':'deposit','brand':'Volts & VINs'}
        if manual:
            options['payment_intent_data']={'capture_method':'manual','metadata':metadata}
        from .catalog import stock_id_for
        return _as_dict(stripe.checkout.Session.create(
            **scope, mode='payment',
            payment_method_types=methods, client_reference_id=order['id'],
            metadata=metadata,
            line_items=[{'price_data':{'currency':'usd','unit_amount':25000,
                'product_data':{'name':('Volts & VINs — $250 reservation card hold' if manual else ('Volts & VINs — $250 refundable reservation deposit' if platform else 'Refundable vehicle reservation deposit')),
                    'description':f"Stock {stock_id_for(order['vin'])}; quote {order['quote_version']}"}},'quantity':1}],
            expires_at=expires_at,
            **options,
            **branding,
            **presentation,
            idempotency_key=f"checkout:{order['id']}:{order['quote_version']}",
        ))

    def create_balance_ach_checkout(self, order, quote, expires_at):
        if getattr(self.settings,'deposit_collection_mode','dealer_direct')=='platform':
            raise ValueError('Platform deposit collection does not support vehicle balance checkout')
        scope=self._scope(order['payment_account'],new_checkout=True)
        total_cents = quote.total_cents if hasattr(quote, 'total_cents') else int(quote['total_cents'])
        balance_cents = total_cents - 25000
        if balance_cents <= 0:
            raise ValueError('Balance after deposit must be positive')
        presentation=({'ui_mode':'embedded_page','redirect_on_completion':'never'}
            if self.settings.checkout_ui_mode=='embedded_page' else {
                'ui_mode':'hosted_page','success_url':self.settings.origin+'/?checkout=balance_returned',
                'cancel_url':self.settings.origin+'/?checkout=balance_cancelled'})
        return _as_dict(stripe.checkout.Session.create(
            **scope, mode='payment',
            payment_method_types=['us_bank_account'], client_reference_id=order['id'],
            payment_method_options={'us_bank_account':{'financial_connections':{'permissions':['payment_method']},'verification_method':'instant'}},
            metadata={'order_id':order['id'],'quote_version':str(order['quote_version']),'payment_stage':'balance_ach'},
            line_items=[{'price_data':{'currency':'usd','unit_amount':balance_cents,
                'product_data':{'name':'Vehicle purchase balance (ACH bank transfer)',
                    'description':f"VIN {order['vin']}; quote {order['quote_version']}"}},'quantity':1}],
            expires_at=expires_at,
            **presentation,
            idempotency_key=f"balance_ach:{order['id']}:{order['quote_version']}",
        ))

    def verify_event(self, raw, signature):
        return _as_dict(stripe.Webhook.construct_event(raw,signature,self.settings.webhook_secret))

    def retrieve_checkout(self, session_id, account):
        return _as_dict(stripe.checkout.Session.retrieve(session_id,**self._scope(account)))

    def retrieve_payment_intent(self, payment_id, account):
        return _as_dict(stripe.PaymentIntent.retrieve(payment_id,expand=['latest_charge'],**self._scope(account)))

    def capture_authorization(self, order):
        return _as_dict(stripe.PaymentIntent.capture(order['payment_id'],amount_to_capture=25000,
            **self._scope(order['payment_account']),idempotency_key=f"capture:{order['id']}:{order['quote_version']}:deposit"))

    def release_authorization(self, order):
        return _as_dict(stripe.PaymentIntent.cancel(order['payment_id'],
            **self._scope(order['payment_account']),idempotency_key=f"release:{order['id']}:{order['quote_version']}:deposit"))

    def refund(self, order):
        return _as_dict(stripe.Refund.create(payment_intent=order['payment_id'],amount=25000,
            **self._scope(order['payment_account']),idempotency_key=f"refund:{order['id']}:deposit"))

    def dealer_can_charge(self,account):
        scope=self._scope(account,new_checkout=True)
        own_account='stripe_account' not in scope
        data=_as_dict(stripe.Account.retrieve(**scope) if own_account else stripe.Account.retrieve(account,api_key=self.settings.stripe_key))
        return bool((not own_account or data.get('id')==self._platform_pin())
                    and data.get('charges_enabled') is True and data.get('details_submitted') is True)

    def expire_checkout(self, session_id, account):
        return _as_dict(stripe.checkout.Session.expire(session_id,**self._scope(account)))
