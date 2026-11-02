"""Exact private-image routing and network protections, without provider calls."""
import hashlib
import json
import socket
import threading

import pytest

from app.catalog import public_catalog,public_photo_url,stock_id_for
from app import image_proxy as proxy

VIN='7SAYGDED1RF039277'
STOCK='VV-6C2CD3B68849'
URL='https://photos.example.test/'+VIN+'/front.jpg'
IMAGE=hashlib.sha256(URL.encode()).hexdigest()[:20]
PNG=b'\x89PNG\r\n\x1a\n'+b'synthetic image bytes'


def vehicle():
    return {'vin':VIN,'photo':URL,'photos':[{'url':URL,'title':'VIN '+VIN,'category':'photos','source_url':'PRIVATE'}]}


def test_public_photo_identity_is_hidden_without_altering_private_urls():
    url=public_photo_url(VIN,URL)
    assert url==f'https://api.voltsandvins.com/api/vehicles/{STOCK}/images/{IMAGE}'
    for raw in [URL.lower(),URL.replace(VIN,'%37%53%41%59%47%44%45%44%31%52%46%30%33%39%32%37%37')]:
        assert '/images/'+hashlib.sha256(raw.encode()).hexdigest()[:20] in public_photo_url(VIN,raw)
    normal='https://photos.example.test/actual-image.jpg'
    assert public_photo_url(VIN,normal)==normal
    original=vehicle();public=public_catalog({'items':[original]})['items'][0]
    assert VIN not in json.dumps(public) and VIN in original['photo']
    assert public['photo']==url and public['photos'][0]['url']==url
    assert set(public['photos'][0])=={'url','title','category'}


def test_known_hash_returns_exact_image_with_private_cache_and_safe_headers(tmp_path):
    calls=[]
    def fetch(url):calls.append(url);return proxy.FetchedImage(PNG,'image/png')
    response=proxy.image_response(vehicle(),STOCK,IMAGE,tmp_path,fetcher=fetch)
    assert response.status_code==200 and response.body==PNG and calls==[URL]
    assert response.headers['content-type']=='image/png'
    assert response.headers['x-content-type-options']=='nosniff'
    assert response.headers['cross-origin-resource-policy']=='cross-origin'
    assert VIN not in str(dict(response.headers)) and URL not in str(dict(response.headers))
    cached=proxy.image_response(vehicle(),STOCK,IMAGE,tmp_path,fetcher=lambda _:pytest.fail('Cache miss'))
    assert cached.body==PNG
    assert (tmp_path/STOCK/(IMAGE+'.bin')).stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('stock,image',[(STOCK,'0'*20),(stock_id_for('5YJSA1S22FF087484'),IMAGE),
    ('../../private',IMAGE),(STOCK,'../'+IMAGE),(VIN,IMAGE)])
def test_unknown_image_or_stock_never_fetches(stock,image,tmp_path):
    response=proxy.image_response(vehicle(),stock,image,tmp_path,fetcher=lambda _:pytest.fail('Unexpected fetch'))
    assert response.status_code==404 and b'7SAY' not in response.body


def test_provider_errors_do_not_reveal_urls_or_vehicle_identity(tmp_path):
    def broken(_):raise RuntimeError('Secret provider detail '+URL)
    response=proxy.image_response(vehicle(),STOCK,IMAGE,tmp_path,fetcher=broken)
    assert response.status_code==502 and response.body==b'Vehicle image unavailable'
    assert response.headers['cache-control']=='no-store'


class FakeResponse:
    def __init__(self,status=200,headers=None,body=PNG):
        self.status=status;self.headers={'Content-Type':'image/png',**(headers or {})};self.body=body
    def getheader(self,key):return self.headers.get(key)
    def read1(self,size):
        chunk=self.body[:size];self.body=self.body[size:];return chunk
    def close(self):pass


def connections(responses,calls):
    class Connection:
        def __init__(self,host,address,timeout):
            calls.append({'host':host,'address':address,'timeout':timeout})
        def request(self,method,path,headers):calls[-1].update(method=method,path=path,headers=headers)
        def getresponse(self):return responses.pop(0)
        def close(self):pass
    return Connection


@pytest.mark.parametrize('url',[
    'http://public.example.test/a.jpg','https://127.0.0.1/a.jpg','https://[::1]/a.jpg',
    'https://user:password@public.example.test/a.jpg','https://public.example.test:444/a.jpg',
    'https://public.example.test/a\r\nX-Injected:yes',
])
def test_invalid_transport_targets_are_refused_before_connection(url):
    with pytest.raises(proxy.ImageUnavailable):
        proxy.fetch_image(url,resolver=lambda *a:['8.8.8.8'],
                          connection_factory=lambda *a:pytest.fail('Unsafe target connected'))


@pytest.mark.parametrize('addresses',[['127.0.0.1'],['10.0.0.1'],['169.254.169.254'],
    ['100.100.100.200'],['::1'],['fe80::1'],['8.8.8.8','192.168.1.2'],['224.0.0.1']])
def test_every_dns_answer_must_be_public(addresses):
    with pytest.raises(proxy.ImageUnavailable):
        proxy.fetch_image('https://public.example.test/a.jpg',resolver=lambda *a:addresses,
                          connection_factory=lambda *a:pytest.fail('Unsafe DNS answer connected'))


def test_redirect_revalidates_dns_and_does_not_forward_credentials():
    calls=[];dns=[]
    def resolve(host,port):dns.append((host,port));return ['8.8.8.8'] if host=='first.example.test' else ['10.0.0.1']
    responses=[FakeResponse(302,{'Location':'https://internal.example.test/a.jpg'})]
    with pytest.raises(proxy.ImageUnavailable):
        proxy.fetch_image('https://first.example.test/a.jpg',resolver=resolve,connection_factory=connections(responses,calls))
    assert dns==[('first.example.test',443),('internal.example.test',443)] and len(calls)==1
    assert calls[0]['address']=='8.8.8.8' and calls[0]['headers']['Host']=='first.example.test'
    assert not {'Authorization','Cookie','Referer'}&calls[0]['headers'].keys()


def test_valid_redirects_keep_original_tls_host_and_have_a_strict_limit():
    calls=[];responses=[FakeResponse(302,{'Location':f'https://cdn.example.test/{i}.png'}) for i in range(4)]
    with pytest.raises(proxy.ImageUnavailable):
        proxy.fetch_image(URL,resolver=lambda *a:['8.8.8.8'],connection_factory=connections(responses,calls))
    assert len(calls)==4
    success=[]
    image=proxy.fetch_image('https://public.example.test/a.png',resolver=lambda *a:['8.8.8.8'],
                            connection_factory=connections([FakeResponse()],success))
    assert image.body==PNG and success[0]['timeout']<=5


def test_connection_uses_numeric_ip_and_verifies_original_hostname(monkeypatch):
    calls=[];raw=object();wrapped=object()
    monkeypatch.setattr(socket,'create_connection',lambda address,timeout:(calls.append((address,timeout)) or raw))
    class Context:
        def wrap_socket(self,sock,server_hostname):
            assert sock is raw and server_hostname=='photos.example.test';return wrapped
    connection=proxy._PinnedHTTPSConnection('photos.example.test','8.8.8.8',3)
    connection._context=Context();connection.connect()
    assert calls==[(('8.8.8.8',443),3)] and connection.sock is wrapped


@pytest.mark.parametrize('headers,body',[
    ({'Content-Type':'text/html'},PNG),({'Content-Type':'image/svg+xml'},b'<svg/>'),
    ({'Content-Type':'image/png'},b'<html>not an image</html>'),
    ({'Content-Length':str(proxy.MAX_IMAGE_BYTES+1)},PNG),
    ({'Content-Length':'invalid'},PNG),({'Content-Encoding':'gzip'},PNG),
])
def test_mime_magic_encoding_and_declared_size_rejections(headers,body):
    with pytest.raises(proxy.ImageUnavailable):
        proxy.fetch_image(URL,resolver=lambda *a:['8.8.8.8'],
            connection_factory=connections([FakeResponse(headers=headers,body=body)],[]))


def test_streamed_size_is_capped_without_content_length(monkeypatch):
    monkeypatch.setattr(proxy,'MAX_IMAGE_BYTES',16)
    with pytest.raises(proxy.ImageUnavailable):
        proxy.fetch_image(URL,resolver=lambda *a:['8.8.8.8'],
            connection_factory=connections([FakeResponse(body=PNG)],[]))


def test_dns_timeout_is_bounded_without_connecting(monkeypatch):
    release=threading.Event()
    monkeypatch.setattr(proxy,'CONNECT_TIMEOUT',0.01)
    def slow(*args):release.wait(1);return ['8.8.8.8']
    try:
        with pytest.raises(proxy.ImageUnavailable):
            proxy.fetch_image(URL,resolver=slow,connection_factory=lambda *a:pytest.fail('Unexpected connect'))
    finally:release.set()
