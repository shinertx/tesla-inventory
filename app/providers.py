"""Nonbinding pricing estimates and disabled unverified provider placeholders.

Contract: Super Dispatch Pricing Insights v1 official Quickstart/Response Handling.
Schema fixtures do not establish account entitlement or live service access.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Protocol
import json
import re
import time
import urllib.error
import urllib.request

__all__ = [
    'SuperDispatchPricingClient',
    'CarrierPriceEstimate',
    'ProviderNotConfigured',
    'ProviderUnavailable',
    'UnsupportedRoute',
    'TransportQuoteResult',
    'FinancingOfferResult',
    'STATE_TAX_RATES',
    'shipping_tier_cents',
    'build_instant_quote_payload',
    'SuperDispatchPricingAdapter',
    'RunBuggyAdapter',
    'AutoFiLendingAdapter',
]
_ENDPOINT = 'https://pricing-insights.superdispatch.com/api/v1/recommended-price'
_MAX_CENTS = 2_000_000  # $20,000 estimate ceiling; fail closed outside supported retail bounds.


class ProviderUnavailable(RuntimeError):
    def __init__(self, reason='unavailable'):
        self.reason = reason
        super().__init__('Transport pricing unavailable: ' + reason)


class ProviderNotConfigured(ProviderUnavailable):
    pass


class UnsupportedRoute(ProviderUnavailable):
    pass


@dataclass(frozen=True)
class CarrierPriceEstimate:
    provider: str
    carrier_estimate_cents: int
    customer_estimate_cents: int
    confidence: float | None
    distance_miles: float | None
    observed_at: int


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _number(value, *, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ProviderUnavailable('malformed_response')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not minimum <= number <= maximum:
            raise ProviderUnavailable('malformed_response')
        return number
    except (InvalidOperation, ValueError):
        raise ProviderUnavailable('malformed_response') from None


def _location(value):
    if not isinstance(value, dict):
        raise ValueError('Location must be an object')
    zip_code = value.get('zip')
    if isinstance(zip_code, str) and re.fullmatch(r'\d{5}', zip_code):
        return {'zip': zip_code}
    city, state = value.get('city'), value.get('state')
    if isinstance(city, str) and 1 <= len(city.strip()) <= 100 and isinstance(state, str) and re.fullmatch('[A-Z]{2}', state):
        return {'city': city.strip(), 'state': state}
    raise ValueError('Location requires a ZIP or city and state')


class SuperDispatchPricingClient:
    def __init__(self, api_key, margin_buffer_cents=20000):
        self._api_key = api_key.strip() if isinstance(api_key, str) else ''
        if isinstance(margin_buffer_cents, bool) or not isinstance(margin_buffer_cents, int) or not 0 <= margin_buffer_cents <= _MAX_CENTS:
            raise ValueError('Invalid margin buffer')
        if '\r' in self._api_key or '\n' in self._api_key:
            raise ProviderNotConfigured('invalid_key')
        self.margin_buffer_cents = margin_buffer_cents

    def _open(self, request):
        # No redirect can forward the credential to another host. No automatic retry.
        return urllib.request.build_opener(_NoRedirect()).open(request, timeout=10)

    def recommended_price(self, *, pickup: dict, delivery: dict, vehicle: dict) -> CarrierPriceEstimate:
        if not self._api_key:
            raise ProviderNotConfigured('missing_key')
        if not isinstance(vehicle, dict):
            raise ValueError('Vehicle must be an object')
        vehicle_payload = {}
        for field in ('type', 'make', 'model'):
            value = vehicle.get(field)
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100:
                raise ValueError('Vehicle requires type, make, and model')
            vehicle_payload[field] = value.strip()
        if vehicle_payload['type'] not in {'sedan', 'suv', 'van', 'coupe_2_doors', 'pickup_2_doors', 'pickup_4_doors'}:
            raise ValueError('Unsupported vehicle type')
        year = str(vehicle.get('year', ''))
        if not re.fullmatch(r'\d{4}', year) or not 1886 <= int(year) <= 2100:
            raise ValueError('Invalid vehicle year')
        operable = vehicle.get('is_inoperable')
        if not isinstance(operable, bool):
            raise ValueError('Invalid operability')
        vehicle_payload.update(year=year, is_inoperable=operable)
        payload = {'trailer_type': 'open', 'pickup': _location(pickup),
                   'delivery': _location(delivery), 'vehicles': [vehicle_payload]}
        request = urllib.request.Request(_ENDPOINT, data=json.dumps(payload).encode(),
            headers={'X-API-Key': self._api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
        try:
            with self._open(request) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ProviderUnavailable('malformed_response')
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ProviderNotConfigured('authentication') from None
            if exc.code == 403:
                raise ProviderNotConfigured('quota') from None
            if exc.code == 429:
                raise ProviderUnavailable('rate_limited') from None
            if exc.code == 400:
                try:
                    error = json.loads(exc.read(65536)).get('data', {}).get('type')
                except (ValueError, AttributeError, TypeError):
                    error = None
                if error in ('SAME_ZIP_CODES', 'NO_ROUTE_AVAILABLE'):
                    raise UnsupportedRoute(error.lower()) from None
            raise ProviderUnavailable('http_error') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderUnavailable('network') from None
        try:
            result = json.loads(raw, parse_float=Decimal)
            if not isinstance(result, dict) or result.get('meta', {}).get('status') != 'success' or not isinstance(result.get('data'), dict):
                raise ProviderUnavailable('malformed_response')
            data = result['data']
            amount = _number(data.get('price'), minimum=Decimal('0.01'), maximum=Decimal(_MAX_CENTS) / 100)
            cents = int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if cents + self.margin_buffer_cents > _MAX_CENTS:
                raise ProviderUnavailable('amount_out_of_bounds')
            confidence = None if data.get('confidence') is None else float(_number(data['confidence'], minimum=0, maximum=100))
            distance = None if data.get('distance_miles') is None else float(_number(data['distance_miles'], minimum=0, maximum=100000))
        except (ValueError, TypeError, AttributeError, KeyError, InvalidOperation):
            raise ProviderUnavailable('malformed_response') from None
        return CarrierPriceEstimate('Super Dispatch', cents, cents + self.margin_buffer_cents,
                                    confidence, distance, int(time.time()))


@dataclass(frozen=True)
class TransportQuoteResult:
    provider: str
    rate_cents: int
    quote_expires_at: int
    pickup_window_start: int
    pickup_window_end: int
    delivery_window_start: int
    delivery_window_end: int
    quote_reference: str
    tracking_url: str = ''
    bol_reference: str = ''


@dataclass(frozen=True)
class FinancingOfferResult:
    provider: str
    state: str
    apr_bps: int
    term_months: int
    approved_amount_cents: int
    monthly_payment_cents: int
    application_url: str
    lender_name: str = ''
    stipulations: tuple[str, ...] = ()


STATE_TAX_RATES = {
    'AL': 0.02, 'AK': 0.0, 'AZ': 0.056, 'AR': 0.065, 'CA': 0.0725, 'CO': 0.029,
    'CT': 0.0635, 'DE': 0.0, 'DC': 0.06, 'FL': 0.06, 'GA': 0.07, 'HI': 0.04,
    'ID': 0.06, 'IL': 0.0625, 'IN': 0.07, 'IA': 0.05, 'KS': 0.065, 'KY': 0.06,
    'LA': 0.0445, 'ME': 0.055, 'MD': 0.06, 'MA': 0.0625, 'MI': 0.06, 'MN': 0.06875,
    'MS': 0.05, 'MO': 0.04225, 'MT': 0.0, 'NE': 0.055, 'NV': 0.0825, 'NH': 0.0,
    'NJ': 0.06625, 'NM': 0.04, 'NY': 0.04, 'NC': 0.03, 'ND': 0.05, 'OH': 0.0575,
    'OK': 0.045, 'OR': 0.0, 'PA': 0.06, 'RI': 0.07, 'SC': 0.05, 'SD': 0.04,
    'TN': 0.07, 'TX': 0.0625, 'UT': 0.0685, 'VT': 0.06, 'VA': 0.0415, 'WA': 0.065,
    'WV': 0.06, 'WI': 0.05, 'WY': 0.04,
}


def shipping_tier_cents(distance_miles: int | float) -> int:
    """Illustrative distance-band delivery estimate; not a carrier quote or income."""
    if isinstance(distance_miles, bool) or not isinstance(distance_miles, (int, float)):
        raise ValueError('distance_miles must be a finite non-negative number')
    distance = Decimal(str(distance_miles))
    if not distance.is_finite() or distance < 0:
        raise ValueError('distance_miles must be a finite non-negative number')
    if distance <= 50:
        return 20000
    if distance <= 250:
        return 59000
    if distance <= 600:
        return 79000
    if distance <= 1200:
        return 109000
    return 139000


def build_instant_quote_payload(
    *,
    dealer_id: str,
    dealer_vehicle_net_cents: int,
    vehicle_price_cents: int,
    buyer_state: str,
    distance_miles: int | float,
    terms_base_url: str = 'https://voltsandvins.com/terms',
    title_registration_cents: int = 28500,
    documentation_cents: int = 0,
    deposit_cents: int = 25000,
    valid_seconds: int = 86400 * 3,
) -> dict:
    """Return an estimate only, never a payable Quote payload.

    The legacy name and input signature remain for callers. Dealer identity,
    acquisition cost, terms URL and validity duration do not establish evidence.
    They intentionally create no approval, hold, terms links or expiry.
    Tax uses a state base-rate assumption, excluding local fees and exceptions.
    """
    amounts = (vehicle_price_cents, title_registration_cents, documentation_cents, deposit_cents)
    if any(type(amount) is not int or amount < 0 for amount in amounts):
        raise ValueError('Estimate amounts must be non-negative integer cents')
    state_code = buyer_state.strip().upper()
    if state_code not in STATE_TAX_RATES:
        raise ValueError(f'Unsupported state code: {buyer_state}')
    tax_cents = int((Decimal(vehicle_price_cents) * Decimal(str(STATE_TAX_RATES[state_code]))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    delivery_cents = shipping_tier_cents(distance_miles)
    return {
        'estimate_only': True,
        'binding': False,
        'carrier_booked': False,
        'vehicle_price_cents': vehicle_price_cents,
        'estimated_tax_cents': tax_cents,
        'estimated_title_registration_cents': title_registration_cents,
        'estimated_documentation_cents': documentation_cents,
        'estimated_delivery_cents': delivery_cents,
        'estimated_total_cents': vehicle_price_cents + tax_cents + title_registration_cents + documentation_cents + delivery_cents,
        'illustrative_deposit_cents': deposit_cents,
        'calculation_basis': 'state_base_tax_rate_and_illustrative_distance_tier',
        'notice': 'Estimate only. Local taxes, fees, carrier rate, seller hold, vehicle history, condition, and terms require verification before a payable quote.',
    }


class TransportProvider(Protocol):
    def quote_lane(self, *, vin: str, origin_zip: str, destination_zip: str, operable: bool = True) -> TransportQuoteResult: ...


class FinancingProvider(Protocol):
    def create_application_session(self, *, order_id: str, vin: str, vehicle_price_cents: int, buyer_name: str, buyer_email: str, buyer_zip: str, buyer_state: str) -> FinancingOfferResult: ...


class SuperDispatchPricingAdapter:
    """Disabled legacy placeholder. This is not the verified pricing client."""

    def __init__(self, api_key: str, base_url: str | None = None, margin_buffer_cents: int = 20000):
        raise ProviderNotConfigured('Legacy Super Dispatch adapter is disabled. Use SuperDispatchPricingClient for nonbinding estimates; carrier booking requires a verified contract.')


class RunBuggyAdapter:
    """Disabled until an authorized, documented provider contract is implemented."""

    def __init__(self, api_token: str, base_url: str | None = None, margin_buffer_cents: int = 20000):
        raise ProviderNotConfigured('RunBuggy adapter is disabled. Obtain authorized API documentation and implement the verified contract before activation.')


class AutoFiLendingAdapter:
    """Disabled. Credentials alone do not establish a lender API contract."""

    def __init__(self, api_key: str, dealer_code: str, base_url: str | None = None):
        raise ProviderNotConfigured('AutoFi adapter is disabled. Obtain authorized lender API documentation and implement the verified contract; no application, APR, or approval is inferred.')
