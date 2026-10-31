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
    consent: Literal[True]

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address')
        return value.lower()

class Quote(StrictModel):
    acquisition_cents: int = Field(gt=0, le=100_000_000)
    vehicle_price_cents: int = Field(gt=0, le=100_000_000)
    tax_cents: int = Field(ge=0, le=10_000_000)
    title_registration_cents: int = Field(ge=0, le=1_000_000)
    documentation_cents: int = Field(ge=0, le=1_000_000)
    delivery_charge_cents: int = Field(ge=0, le=2_000_000)
    transport_cost_cents: int = Field(ge=0, le=2_000_000)
    inspection_recon_cents: int = Field(ge=0, le=2_000_000)
    warranty_return_reserve_cents: int = Field(ge=0, le=2_000_000)
    acquisition_marketing_cents: int = Field(ge=0, le=2_000_000)
    other_cost_cents: int = Field(ge=0, le=2_000_000)
    seller_hold_until: int
    valid_until: int
    seller_hold_reference: str = Field(min_length=5, max_length=500)
    title_history_reference: str = Field(min_length=5, max_length=500)
    lien_payoff_reference: str = Field(min_length=5, max_length=500)
    inspection_reference: str = Field(min_length=5, max_length=500)
    equipment_reference: str = Field(min_length=5, max_length=500)
    recall_reference: str = Field(min_length=5, max_length=500)
    tax_quote_reference: str = Field(min_length=5, max_length=500)
    carrier_quote_reference: str = Field(min_length=5, max_length=500)
    buyers_guide_reference: str = Field(min_length=5, max_length=500)
    buyers_guide_basis: Literal['provided', 'exempt_vehicle'] = 'provided'
    warranty_terms_reference: str = Field(min_length=5, max_length=500)
    return_terms_reference: str = Field(min_length=5, max_length=500)
    deposit_terms_reference: str = Field(min_length=5, max_length=500)
    title_status: Literal['clean_verified']
    condition_status: Literal['accepted']
    recall_disposition: Literal['clear', 'remedied']

    @model_validator(mode='after')
    def validity(self):
        if self.valid_until > self.seller_hold_until:
            raise ValueError('Quote cannot outlive the source dealer hold')
        return self

    @field_validator('buyers_guide_reference','warranty_terms_reference','return_terms_reference','deposit_terms_reference')
    @classmethod
    def public_terms(cls,value):
        from urllib.parse import urlsplit
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Customer terms require an HTTPS document URL')
        return value

    @property
    def total_cents(self):
        return (self.vehicle_price_cents + self.tax_cents + self.title_registration_cents
                + self.documentation_cents + self.delivery_charge_cents)

    @property
    def contribution_cents(self):
        # Taxes and registration are pass-through liabilities, never revenue.
        return (self.vehicle_price_cents + self.documentation_cents + self.delivery_charge_cents
                - self.acquisition_cents - self.transport_cost_cents - self.inspection_recon_cents
                - self.warranty_return_reserve_cents - self.acquisition_marketing_cents - self.other_cost_cents)

class Transition(StrictModel):
    state: Literal['contracted', 'funded', 'purchased', 'in_transit', 'delivered', 'completed']
    evidence: dict[str, str] = Field(min_length=1, max_length=15)

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
