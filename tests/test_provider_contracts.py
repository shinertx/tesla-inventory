"""Official public schema fixtures only; not live provider/account proof."""
import io
import json
import urllib.error
import urllib.request
import pytest
from app.providers import (SuperDispatchPricingClient, CarrierPriceEstimate,
                           ProviderNotConfigured, ProviderUnavailable, UnsupportedRoute)

INPUT = dict(pickup={'zip': '89506'}, delivery={'city': 'Gardena', 'state': 'CA'},
             vehicle={'type': 'sedan', 'make': 'Tesla', 'model': 'Model 3', 'year': 2023, 'is_inoperable': False})


def response(client, monkeypatch, body):
    seen = []
    def call(req):
        seen.append(req)
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(client, '_open', call)
    return seen


def test_documented_contract_and_decimal_cents(monkeypatch):
    client = SuperDispatchPricingClient('fixture-key')
    seen = response(client, monkeypatch, {'meta': {'status': 'success'}, 'data': {
        'price': 550.29, 'confidence': 69, 'distance_miles': 1450}})
    estimate = client.recommended_price(**INPUT)
    assert isinstance(estimate, CarrierPriceEstimate)
    assert estimate.carrier_estimate_cents == 55029
    assert estimate.customer_estimate_cents == 75029
    assert estimate.confidence == 69 and estimate.distance_miles == 1450
    assert estimate.observed_at > 0
    assert set(estimate.__dataclass_fields__) == {'provider', 'carrier_estimate_cents', 'customer_estimate_cents', 'confidence', 'distance_miles', 'observed_at'}
    req = seen[0]
    assert req.full_url == 'https://pricing-insights.superdispatch.com/api/v1/recommended-price'
    assert req.get_header('X-api-key') == 'fixture-key'
    assert req.get_header('Authorization') is None
    body = json.loads(req.data)
    assert body == {'trailer_type': 'open', 'pickup': {'zip': '89506'}, 'delivery': INPUT['delivery'],
                    'vehicles': [dict(INPUT['vehicle'], year='2023', is_inoperable=False)]}
    assert req.get_method() == 'POST' and len(seen) == 1


def test_absent_key_never_calls_transport(monkeypatch):
    client = SuperDispatchPricingClient('')
    monkeypatch.setattr(client, '_open', lambda req: pytest.fail('Network called'))
    with pytest.raises(ProviderNotConfigured, match='missing_key'):
        client.recommended_price(**INPUT)


def test_unknown_operability_is_not_assumed(monkeypatch):
    client = SuperDispatchPricingClient('fixture')
    monkeypatch.setattr(client, '_open', lambda req: pytest.fail('Network called'))
    vehicle={key:value for key,value in INPUT['vehicle'].items() if key!='is_inoperable'}
    with pytest.raises(ValueError,match='operability'):
        client.recommended_price(**{**INPUT,'vehicle':vehicle})


@pytest.mark.parametrize('price', [None, 0, -1, True, 'NaN', 'Infinity', 'abc', 20001, {}, []])
def test_invalid_amount_fails_closed(monkeypatch, price):
    client = SuperDispatchPricingClient('fixture')
    response(client, monkeypatch, {'meta': {'status': 'success'}, 'data': {'price': price}})
    with pytest.raises(ProviderUnavailable): client.recommended_price(**INPUT)


@pytest.mark.parametrize('body', [{}, [], {'meta': None}, {'meta': {'status': 'fail'}, 'data': {'price': 500}},
    {'meta': {'status': 'success'}, 'data': {'price': 500, 'confidence': 101}},
    {'meta': {'status': 'success'}, 'data': {'price': 500, 'distance_miles': -1}}])
def test_bad_envelope_and_metrics(monkeypatch, body):
    client = SuperDispatchPricingClient('fixture')
    response(client, monkeypatch, body)
    with pytest.raises(ProviderUnavailable): client.recommended_price(**INPUT)


@pytest.mark.parametrize('code,error,kind,reason', [
    (401, None, ProviderNotConfigured, 'authentication'), (403, None, ProviderNotConfigured, 'quota'),
    (429, None, ProviderUnavailable, 'rate_limited'), (500, None, ProviderUnavailable, 'http_error'),
    (400, 'SAME_ZIP_CODES', UnsupportedRoute, 'same_zip_codes'),
    (400, 'NO_ROUTE_AVAILABLE', UnsupportedRoute, 'no_route_available'),
    (422, None, ProviderUnavailable, 'http_error'), (302, None, ProviderUnavailable, 'http_error')])
def test_http_errors_are_distinct_without_retries(monkeypatch, code, error, kind, reason):
    client = SuperDispatchPricingClient('fixture'); calls = []
    def fail(req):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, code, 'private provider text', {},
            io.BytesIO(json.dumps({'data': {'type': error}}).encode()))
    monkeypatch.setattr(client, '_open', fail)
    with pytest.raises(kind) as caught: client.recommended_price(**INPUT)
    assert caught.value.reason == reason and len(calls) == 1
    assert 'private provider text' not in str(caught.value)


def test_no_invented_optional_fields(monkeypatch):
    client = SuperDispatchPricingClient('fixture', margin_buffer_cents=0)
    response(client, monkeypatch, {'meta': {'status': 'success'}, 'data': {'price': 1272}})
    estimate = client.recommended_price(**INPUT)
    assert estimate.confidence is None and estimate.distance_miles is None


def test_default_transport_refuses_redirects(monkeypatch):
    client = SuperDispatchPricingClient('fixture'); captured = []
    class Opener:
        def open(self, request, timeout):
            assert timeout == 10
            return io.BytesIO(b'{}')
    def build(handler):
        captured.append(handler)
        return Opener()
    monkeypatch.setattr(urllib.request, 'build_opener', build)
    client._open(urllib.request.Request('https://pricing-insights.superdispatch.com/'))
    assert captured[0].redirect_request(None, None, 302, '', {}, 'https://other.example/') is None


def test_wrong_api_vehicle_enum_rejected_before_network(monkeypatch):
    client = SuperDispatchPricingClient('fixture')
    monkeypatch.setattr(client, '_open', lambda req: pytest.fail('Network called'))
    with pytest.raises(ValueError, match='Unsupported vehicle type'):
        client.recommended_price(**dict(INPUT, vehicle=dict(INPUT['vehicle'], type='pickup')))
