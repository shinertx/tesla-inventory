from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import re

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class PurchaseRequest(StrictModel):
    vin: str = Field(pattern=r'^[A-HJ-NPR-Z0-9]{17}$')
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=254)
    state: str = Field(pattern=r'^[A-Z]{2}$')
    zip: str = Field(pattern=r'^\d{5}$')
    demand_channel: str = Field(default="direct",pattern=r"^[a-z0-9_-]{1,60}$")
    campaign_id: str = Field(default="",max_length=100)
    payment_preference: Literal['cash','partner_financing'] = 'cash'
    expected_vehicle_price_cents: int | None = Field(default=None, gt=0, le=100_000_000, strict=True)
    consent: Literal[True]

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address')
        return value.lower()

class Dealer(StrictModel):
    id: str = Field(pattern=r'^[a-z0-9-]{3,60}$')
    legal_name: str = Field(min_length=3,max_length=150)
    license_number: str = Field(min_length=3,max_length=100)
    address: str = Field(min_length=5,max_length=300)
    supported_states: list[str] = Field(min_length=1)
    stripe_account: str = Field(pattern=r'^acct_[A-Za-z0-9]+$')
    online_portal_hosts: list[str] = Field(default_factory=list)
    agreement_reference: str = Field(min_length=5,max_length=500)
    license_evidence: str = Field(min_length=5,max_length=500)
    verified: bool = False

    @field_validator('supported_states')
    @classmethod
    def states(cls,values):
        if any(not re.fullmatch(r'[A-Z]{2}',x) for x in values):raise ValueError('Use two-letter state codes')
        return sorted(set(values))

class Quote(StrictModel):
    dealer_id: str = Field(min_length=3,max_length=60)
    dealer_vehicle_net_cents: int = Field(gt=0,le=100_000_000)
    vehicle_price_cents: int = Field(gt=0,le=100_000_000)
    tax_cents: int = Field(ge=0,le=10_000_000)
    title_registration_cents: int = Field(ge=0,le=1_000_000)
    documentation_cents: int = Field(ge=0,le=1_000_000)
    delivery_charge_cents: int = Field(ge=0,le=2_000_000)
    demand_cost_cents: int = Field(ge=0,le=2_000_000)
    platform_service_cost_cents: int = Field(ge=0,le=2_000_000)
    platform_payment_cost_cents: int = Field(ge=0,le=2_000_000)
    platform_risk_reserve_cents: int = Field(ge=0,le=2_000_000)
    other_platform_cost_cents: int = Field(ge=0,le=2_000_000)
    supplier_commitment_reference: str = Field(min_length=5,max_length=500)
    spread_agreement_reference: str = Field(min_length=5,max_length=500)
    seller_hold_until: int
    valid_until: int
    seller_hold_reference: str = Field(min_length=5,max_length=500)
    title_history_reference: str = Field(min_length=5,max_length=500)
    lien_payoff_reference: str = Field(min_length=5,max_length=500)
    inspection_reference: str = Field(min_length=5,max_length=500)
    equipment_reference: str = Field(min_length=5,max_length=500)
    recall_reference: str = Field(min_length=5,max_length=500)
    tax_quote_reference: str = Field(min_length=5,max_length=500)
    carrier_quote_reference: str = Field(min_length=5,max_length=500)
    buyers_guide_reference: str = Field(min_length=5,max_length=500)
    buyers_guide_basis: Literal['provided','exempt_vehicle'] = 'provided'
    warranty_terms_reference: str = Field(min_length=5,max_length=500)
    return_terms_reference: str = Field(min_length=5,max_length=500)
    deposit_terms_reference: str = Field(min_length=5,max_length=500)
    title_status: Literal['clean_verified']
    condition_status: Literal['accepted']
    recall_disposition: Literal['clear','remedied']

    @model_validator(mode='after')
    def validity(self):
        if self.valid_until>self.seller_hold_until:raise ValueError('Quote cannot outlive dealer commitment')
        if self.vehicle_price_cents<self.dealer_vehicle_net_cents:raise ValueError('Dealer net exceeds customer vehicle price')
        return self

    @field_validator('buyers_guide_reference','warranty_terms_reference','return_terms_reference','deposit_terms_reference')
    @classmethod
    def public_terms(cls,value):
        from urllib.parse import urlsplit
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Customer terms require HTTPS')
        return value

    @property
    def total_cents(self):
        return self.vehicle_price_cents+self.tax_cents+self.title_registration_cents+self.documentation_cents+self.delivery_charge_cents

    @property
    def spread_cents(self):return self.vehicle_price_cents-self.dealer_vehicle_net_cents

    @property
    def platform_cost_cents(self):
        return self.demand_cost_cents+self.platform_service_cost_cents+self.platform_payment_cost_cents+self.platform_risk_reserve_cents+self.other_platform_cost_cents

    @property
    def contribution_cents(self):return self.spread_cents-self.platform_cost_cents

class Transition(StrictModel):
    state: Literal['dealer_confirmed','dealer_funded','in_transit','delivered','settlement_pending']
    evidence: dict[str,str] = Field(min_length=1,max_length=15)

class Settlement(StrictModel):
    received_cents: int = Field(ge=0,le=100_000_000)
    adjustment_cents: int = Field(ge=0,le=100_000_000)
    actual_platform_cost_cents: int = Field(ge=0,le=100_000_000)
    dealer_statement_reference: str = Field(min_length=5,max_length=500)
    receipt_reference: str = Field(min_length=5,max_length=500)
    adjustment_reference: str = Field(min_length=5,max_length=500)

class Cancellation(StrictModel):
    reason: str = Field(min_length=3, max_length=500)

class CheckoutAcceptance(StrictModel):
    quote_version: int = Field(ge=1)
    terms_accepted: Literal[True]

class SellerHold(StrictModel):
    expires_at: int
    reference: str = Field(min_length=5,max_length=500)

class CustomerCase(StrictModel):
    kind: Literal['return','warranty','transport_damage','title_delay','other']
    description: str = Field(min_length=5,max_length=1000)

class CaseResolution(StrictModel):
    status: Literal['in_review','resolved']
    owner: str = Field(min_length=2,max_length=100)
    evidence: str = Field(min_length=5,max_length=1000)

class AccessRecovery(StrictModel):
    verification_reference: str = Field(min_length=5,max_length=500)

class SettlementReversal(StrictModel):
    amount_cents: int = Field(gt=0,le=100_000_000)
    reference: str = Field(min_length=5,max_length=500)

class OnlineAction(StrictModel):
    kind: Literal['sign_contract','pay_balance','submit_title_documents','track_delivery']
    url: str = Field(min_length=10,max_length=2048)
    evidence_reference: str = Field(min_length=5,max_length=500)

class PaymentPreferenceUpdate(StrictModel):
    payment_preference: Literal['cash','partner_financing']

class BalanceCheckoutAcceptance(StrictModel):
    quote_version: int = Field(ge=1)
    ach_authorization_accepted: bool = False
    terms_accepted: bool = False

    @model_validator(mode='after')
    def check_accepted(self):
        if not (self.ach_authorization_accepted or self.terms_accepted):
            raise ValueError('Explicit ACH authorization or terms acceptance is required')
        return self

class FinancingUpdate(StrictModel):
    state: Literal['application_ready','application_submitted','prequalified','conditional_approval','contract_signed','lender_funded','declined']
    provider: str = Field(min_length=2,max_length=80)
    reference: str = Field(min_length=5,max_length=500)
    approved_amount_cents: int = Field(default=0,ge=0,le=100_000_000)
    funded_amount_cents: int = Field(default=0,ge=0,le=100_000_000)
    stipulations: list[str] = Field(default_factory=list,max_length=20)
    application_url: str = Field(default='',max_length=2048)

    @field_validator('application_url')
    @classmethod
    def check_app_url(cls,value):
        if not value:return value
        from urllib.parse import urlsplit
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Financing application URL requires HTTPS')
        return value

    @model_validator(mode='after')
    def check_funding(self):
        if self.state=='application_ready' and not self.application_url:
            raise ValueError('Application-ready state requires the approved lender application URL')
        if self.state in {'application_ready','application_submitted'} and (self.approved_amount_cents or self.funded_amount_cents):
            raise ValueError('Application readiness or submission is not approval or funded proceeds')
        if self.state=='lender_funded' and self.funded_amount_cents<=0:
            raise ValueError('Lender-funded state requires positive funded_amount_cents')
        return self

class TransportUpdate(StrictModel):
    state: Literal['quoted','carrier_accepted','dispatched','delivered','exception']
    provider: str = Field(min_length=2,max_length=80)
    quote_reference: str = Field(min_length=5,max_length=500)
    rate_cents: int = Field(ge=0,le=2_000_000)
    quote_expires_at: int
    pickup_window_start: int | None = None
    pickup_window_end: int | None = None
    delivery_window_start: int | None = None
    delivery_window_end: int | None = None
    carrier_acceptance_reference: str = Field(default='',max_length=500)
    bol_reference: str = Field(default='',max_length=500)
    tracking_url: str = Field(default='',max_length=2048)
    notes: str = Field(default='',max_length=500)

    @field_validator('tracking_url')
    @classmethod
    def check_tracking_url(cls,value):
        if not value:return value
        from urllib.parse import urlsplit
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Carrier tracking URL requires HTTPS')
        return value

    @model_validator(mode='after')
    def check_carrier_progression(self):
        if self.state in ('carrier_accepted','dispatched','delivered'):
            if len(self.carrier_acceptance_reference)<5:
                raise ValueError('Carrier acceptance requires carrier_acceptance_reference')
            if not self.pickup_window_start or not self.pickup_window_end or self.pickup_window_end<self.pickup_window_start:
                raise ValueError('Carrier acceptance requires a valid pickup window')
        if self.state in ('dispatched','delivered') and len(self.bol_reference)<5:
            raise ValueError('Dispatch and delivery require electronic bill of lading reference')
        return self
