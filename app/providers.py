"""Pricing estimates only; no carrier booking or availability commitment.

Contract: Super Dispatch Pricing Insights v1 official Quickstart/Response Handling.
Schema fixtures do not establish account entitlement or live service access.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
import time
import urllib.error
import urllib.request

__all__ = ['SuperDispatchPricingClient', 'CarrierPriceEstimate',
           'ProviderNotConfigured', 'ProviderUnavailable', 'UnsupportedRoute']
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
