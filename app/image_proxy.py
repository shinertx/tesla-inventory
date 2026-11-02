"""Bounded image relay for exact private vehicle photos. No caller-supplied URLs."""
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit

from starlette.responses import Response

from .catalog import STOCK_ID_PATTERN, stock_id_for

MAX_IMAGE_BYTES=8*1024*1024
MAX_REDIRECTS=3
CONNECT_TIMEOUT=5
TOTAL_TIMEOUT=15
CACHE_SECONDS=86400
IMAGE_ID_PATTERN=re.compile(r'^[0-9a-f]{20}$')
MIME_TYPES=frozenset({'image/jpeg','image/png','image/webp','image/avif','image/gif'})
_DNS_POOL=ThreadPoolExecutor(max_workers=4,thread_name_prefix='vehicle-image-dns')
_DNS_SLOTS=threading.BoundedSemaphore(4)


class ImageUnavailable(ValueError):
    """Deliberately contains no provider URL or vehicle identity."""


@dataclass(frozen=True)
class FetchedImage:
    body: bytes
    content_type: str


def _resolve(host,port):
    return [row[4][0] for row in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM,proto=socket.IPPROTO_TCP)]


def _bounded_resolve(resolver,host,port,deadline):
    if not _DNS_SLOTS.acquire(blocking=False):
        raise ImageUnavailable('Image response is unavailable')
    try:future=_DNS_POOL.submit(resolver,host,port)
    except BaseException:
        _DNS_SLOTS.release();raise
    future.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:return future.result(timeout=max(0,min(CONNECT_TIMEOUT,deadline-time.monotonic())))
    except (FutureTimeout,OSError,ValueError):
        future.cancel()
        raise ImageUnavailable('Image response is unavailable') from None


def _target(url,resolver):
    try:
        parsed=urlsplit(url)
        host=(parsed.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
        if (parsed.scheme!='https' or not host or parsed.port not in (None,443)
                or parsed.username is not None or parsed.password is not None
                or '%' in host or any(ord(c)<33 for c in url)):
            raise ValueError()
        try:ipaddress.ip_address(host)
        except ValueError:pass
        else:raise ValueError()
        addresses=tuple(dict.fromkeys(resolver(host,443)))
        if not addresses:raise ValueError()
        for address in addresses:
            ip=ipaddress.ip_address(address)
            if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified
                    or ip.is_loopback or ip.is_link_local or getattr(ip,'is_site_local',False)):
                raise ValueError()
        path=(parsed.path or '/')+('?' + parsed.query if parsed.query else '')
        return host,path,addresses[0]
    except (ValueError,UnicodeError,OSError,TypeError):
        raise ImageUnavailable('Image source is unavailable') from None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self,host,address,timeout):
        super().__init__(host,port=443,timeout=timeout,context=ssl.create_default_context())
        self._pinned_address=address
        self._pinned_socket=None

    def connect(self):
        # Connect only to the validated numeric address. TLS still verifies the DNS host.
        raw=socket.create_connection((self._pinned_address,443),self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:
            raw.close();raise
        self._pinned_socket=self.sock


def _abort(connection):
    sock=getattr(connection,'_pinned_socket',None) or getattr(connection,'sock',None)
    if sock is not None:
        try:sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        try:sock.close()
        except OSError:pass


def _validate_image(image):
    if not isinstance(image,FetchedImage) or not isinstance(image.body,bytes):
        raise ImageUnavailable('Image response is unavailable')
    content_type=image.content_type.lower().split(';',1)[0].strip()
    body=image.body
    if content_type not in MIME_TYPES or not body or len(body)>MAX_IMAGE_BYTES:
        raise ImageUnavailable('Image response is unavailable')
    signature={
        'image/jpeg':body.startswith(b'\xff\xd8\xff'),
        'image/png':body.startswith(b'\x89PNG\r\n\x1a\n'),
        'image/gif':body.startswith((b'GIF87a',b'GIF89a')),
        'image/webp':body.startswith(b'RIFF') and body[8:12]==b'WEBP',
        'image/avif':len(body)>=16 and body[4:8]==b'ftyp' and any(x in body[8:32] for x in (b'avif',b'avis')),
    }[content_type]
    if not signature:raise ImageUnavailable('Image response is unavailable')
    return FetchedImage(body,content_type)


def fetch_image(url,*,resolver=_resolve,connection_factory=_PinnedHTTPSConnection):
    """Revalidate DNS and pin each redirect connection. No cookies or credentials."""
    deadline=time.monotonic()+TOTAL_TIMEOUT
    visited=set()
    current=url
    try:
        for redirect in range(MAX_REDIRECTS+1):
            if current in visited:raise ImageUnavailable('Image response is unavailable')
            visited.add(current)
            host,path,address=_target(current,lambda h,p:_bounded_resolve(resolver,h,p,deadline))
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ImageUnavailable('Image response is unavailable')
            connection=connection_factory(host,address,min(CONNECT_TIMEOUT,remaining))
            timer=threading.Timer(remaining,_abort,args=(connection,));timer.daemon=True;timer.start()
            response=None
            try:
                connection.request('GET',path,headers={'Host':host,'Accept':', '.join(sorted(MIME_TYPES)),
                    'Accept-Encoding':'identity','User-Agent':'Volts-and-VINs-vehicle-images/1.0'})
                response=connection.getresponse()
                if response.status in {301,302,303,307,308}:
                    location=response.getheader('Location')
                    if not location or redirect==MAX_REDIRECTS:
                        raise ImageUnavailable('Image response is unavailable')
                    current=urljoin(current,location)
                    continue
                if response.status!=200:raise ImageUnavailable('Image response is unavailable')
                if (response.getheader('Content-Encoding') or 'identity').lower()!='identity':
                    raise ImageUnavailable('Image response is unavailable')
                content_type=(response.getheader('Content-Type') or '').split(';',1)[0].lower().strip()
                if content_type not in MIME_TYPES:raise ImageUnavailable('Image response is unavailable')
                length=response.getheader('Content-Length')
                if length is not None and (not length.isdigit() or int(length)>MAX_IMAGE_BYTES):
                    raise ImageUnavailable('Image response is unavailable')
                chunks=[];total=0
                while True:
                    if time.monotonic()>=deadline:raise ImageUnavailable('Image response is unavailable')
                    chunk=response.read1(min(65536,MAX_IMAGE_BYTES-total+1))
                    if not chunk:break
                    total+=len(chunk)
                    if total>MAX_IMAGE_BYTES:raise ImageUnavailable('Image response is unavailable')
                    chunks.append(chunk)
                return _validate_image(FetchedImage(b''.join(chunks),content_type))
            finally:
                timer.cancel()
                if response is not None:response.close()
                connection.close()
    except (ImageUnavailable,OSError,ValueError,UnicodeError,http.client.HTTPException):
        raise ImageUnavailable('Image response is unavailable') from None
    raise ImageUnavailable('Image response is unavailable')


def _private_url(vehicle,image_id):
    urls=[vehicle.get('photo')]
    for photo in vehicle.get('photos') or []:
        urls.append(photo.get('url') if isinstance(photo,dict) else photo)
    return next((url for url in urls if isinstance(url,str) and
                 hashlib.sha256(url.encode()).hexdigest()[:20]==image_id),None)


def _cached(directory,image_id):
    try:
        body_path=directory/(image_id+'.bin')
        if time.time()-body_path.stat().st_mtime>CACHE_SECONDS:return None
        if body_path.stat().st_size>MAX_IMAGE_BYTES:return None
        content_type=json.loads((directory/(image_id+'.json')).read_text())['content_type']
        return _validate_image(FetchedImage(body_path.read_bytes(),content_type))
    except (OSError,ValueError,KeyError,TypeError):return None


def _save_cache(directory,image_id,image):
    try:
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        for suffix,data in (('.bin',image.body),('.json',json.dumps({'content_type':image.content_type}).encode())):
            with tempfile.NamedTemporaryFile(dir=directory,delete=False) as handle:
                temp=Path(handle.name);handle.write(data)
            temp.chmod(0o600);os.replace(temp,directory/(image_id+suffix))
    except OSError:
        # Cache failure does not change image identity or expose the source URL.
        try:temp.unlink(missing_ok=True)
        except (OSError,UnboundLocalError):pass


def image_response(vehicle,stock_id,image_id,cache_dir,fetcher=None):
    """Resolve a known private image hash and return safe bytes or a generic failure."""
    headers={'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
             'Cross-Origin-Resource-Policy':'cross-origin'}
    def failure(status):
        return Response('Vehicle image unavailable',status_code=status,media_type='text/plain',
                        headers={**headers,'Cache-Control':'no-store'})
    try:
        if (not isinstance(vehicle,dict) or not isinstance(stock_id,str)
                or not STOCK_ID_PATTERN.fullmatch(stock_id) or not isinstance(image_id,str)
                or not IMAGE_ID_PATTERN.fullmatch(image_id)
                or stock_id_for(vehicle.get('vin'))!=stock_id):return failure(404)
        url=_private_url(vehicle,image_id)
        if not url:return failure(404)
    except (ValueError,TypeError):return failure(404)
    directory=Path(cache_dir)/stock_id
    image=_cached(directory,image_id)
    if image is None:
        try:image=_validate_image((fetcher or fetch_image)(url))
        except Exception:return failure(502)
        _save_cache(directory,image_id,image)
    return Response(image.body,media_type=image.content_type,headers={**headers,
        'Cache-Control':f'public, max-age={CACHE_SECONDS}',
        'ETag':'"'+hashlib.sha256(image.body).hexdigest()+'"'})
