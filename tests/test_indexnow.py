"""IndexNow batch and validation contracts. Every HTTP request is intercepted."""
import json
from urllib.error import HTTPError, URLError
import pytest
from tools.indexnow import build_indexnow_payload, ping_indexnow, IndexNowSubmissionError

BASE='https://voltsandvins.com/'


def interceptor(monkeypatch, statuses):
    calls=[];responses=iter(statuses)
    class Response:
        def __init__(self,status):self.status=status
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def open_(request,timeout):
        calls.append(json.loads(request.data));assert timeout==15 and request.method=='POST'
        status=next(responses)
        if isinstance(status,Exception):raise status
        return Response(status)
    monkeypatch.setattr('urllib.request.urlopen',open_)
    return calls


@pytest.mark.parametrize('count,sizes',[(10000,[10000]),(10001,[10000,1]),(20001,[10000,10000,1])])
def test_exact_boundary_batches_and_deterministic_order(monkeypatch,count,sizes):
    calls=interceptor(monkeypatch,[200]*len(sizes))
    urls=[BASE+f'v/{i:05}.html' for i in reversed(range(count))]
    result=ping_indexnow(urls)
    assert [len(c['urlList']) for c in calls]==sizes
    assert [u for c in calls for u in c['urlList']]==sorted(urls)
    assert result['submitted']==count and result['total_urls']==count and result['accepted'] is True
    assert [b['status'] for b in result['batches']]==[200]*len(sizes)


def test_deduplication_precedes_batching_and_normalizes_host_default_port(monkeypatch):
    calls=interceptor(monkeypatch,[202])
    result=ping_indexnow([BASE+'b',BASE+'a',BASE+'a','https://VOLTSANDVINS.COM:443/b'])
    assert calls[0]['urlList']==[BASE+'a',BASE+'b']
    assert result['submitted']==2 and result['batches'][0]['receipt']=='key_validation_pending'


@pytest.mark.parametrize('unsafe',[
    'https://foreign.test/x','http://voltsandvins.com/x','//voltsandvins.com/x',
    'https://voltsandvins.com.evil.test/x','https://user:pass@voltsandvins.com/x',
    'https://@voltsandvins.com/x','https://voltsandvins.com:8443/x',BASE+'x#fragment',BASE+'x y',BASE+'x\ny',
    'https://voltsandvins.com\\@evil.test/x',None,'',BASE+'\x00x'])
def test_entire_input_rejected_before_any_network(monkeypatch,unsafe):
    calls=interceptor(monkeypatch,[])
    with pytest.raises(ValueError):ping_indexnow([BASE+f'x{i}' for i in range(10001)]+[unsafe])
    assert calls==[]


def test_empty_input_is_an_explicit_noop(monkeypatch):
    calls=interceptor(monkeypatch,[]);result=ping_indexnow([])
    assert calls==[] and result['submitted']==0 and result['batches']==[]
    assert result['skipped'] is True and result['accepted'] is False and result['status'] is None
    assert build_indexnow_payload([])['urlList']==[]


@pytest.mark.parametrize('failure',[429,500,HTTPError('https://api.indexnow.org/indexnow',403,'Forbidden',{},None),URLError('fixture timeout')])
def test_failed_second_batch_reports_accepted_first_batch_and_stops(monkeypatch,failure):
    calls=interceptor(monkeypatch,[200,failure])
    with pytest.raises(IndexNowSubmissionError) as error:ping_indexnow([BASE+f'x{i}' for i in range(20001)])
    result=error.value.result
    assert len(calls)==2 and result['submitted']==10000 and result['accepted'] is False
    assert result['batches'][0]['accepted'] is True and result['batches'][1]['accepted'] is False
    assert 'batch 2 failed' in str(error.value) and '10000 of 20001' in str(error.value)


def test_single_payload_compatibility_and_oversize_rejection():
    payload=build_indexnow_payload([BASE])
    assert payload['host']=='voltsandvins.com' and payload['urlList']==[BASE]
    with pytest.raises(ValueError,match='10,000'):build_indexnow_payload([BASE+f'x{i}' for i in range(10001)])
    with pytest.raises(ValueError):build_indexnow_payload(BASE)
