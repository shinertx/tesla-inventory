import stripe
stripe.default_http_client = stripe.new_default_http_client(timeout=10)

class StripePayments:
    def __init__(self, settings):
        self.settings = settings

    def create_checkout(self, order, quote, expires_at):
        presentation=({'ui_mode':'embedded_page','redirect_on_completion':'never'}
            if self.settings.checkout_ui_mode=='embedded_page' else {
                'ui_mode':'hosted_page','success_url':self.settings.origin+'/?checkout=returned',
                'cancel_url':self.settings.origin+'/?checkout=cancelled'})
        return stripe.checkout.Session.create(
            api_key=self.settings.stripe_key, stripe_account=order['payment_account'], mode='payment',
            payment_method_types=['card'], client_reference_id=order['id'],
            metadata={'order_id':order['id'],'quote_version':str(order['quote_version'])},
            line_items=[{'price_data':{'currency':'usd','unit_amount':25000,
                'product_data':{'name':'Refundable vehicle reservation deposit',
                    'description':f"VIN {order['vin']}; quote {order['quote_version']}"}},'quantity':1}],
            expires_at=expires_at,
            **presentation,
            idempotency_key=f"checkout:{order['id']}:{order['quote_version']}",
        )

    def verify_event(self, raw, signature):
        return stripe.Webhook.construct_event(raw,signature,self.settings.webhook_secret)

    def retrieve_checkout(self, session_id, account):
        return stripe.checkout.Session.retrieve(session_id,api_key=self.settings.stripe_key,stripe_account=account)

    def refund(self, order):
        return stripe.Refund.create(payment_intent=order['payment_id'],amount=25000,
            api_key=self.settings.stripe_key,stripe_account=order['payment_account'],idempotency_key=f"refund:{order['id']}:deposit")

    def dealer_can_charge(self,account):
        data=stripe.Account.retrieve(account,api_key=self.settings.stripe_key)
        return bool(data.get('charges_enabled') and data.get('details_submitted'))

    def expire_checkout(self, session_id, account):
        return stripe.checkout.Session.expire(session_id,api_key=self.settings.stripe_key,stripe_account=account)
