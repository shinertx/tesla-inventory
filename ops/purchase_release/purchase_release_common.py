"""Strict, side-effect-free helpers for the reviewed purchase-flow release."""
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import os
import re
import stat
import tarfile
import tempfile

ROOT_FILES = frozenset({'index.html','404.html','inventory.json','sitemap.xml','robots.txt',
    'llms.txt','llms-full.txt','openapi.json','search-release.json',
    'voltsandvins-indexnow-key.txt','CNAME','.nojekyll','favicon.ico','favicon.svg',
    'manifest.webmanifest','requirements.txt'})
PAGE_DIRS = ('v','browse','models','years','states','deals')
ASSETS = frozenset({'.js','.css','.svg','.png','.jpg','.jpeg','.webp','.avif','.gif',
    '.ico','.woff','.woff2','.webmanifest'})
DATA = frozenset({'data/us_zip_centers.json','data/us_city_centers.json'})
META = 'DEPLOY_BUNDLE.json'
FIXTURE_VIN = '7SAYGDEE0TEST0001'
VIN = re.compile(r'(?:5YJ|7SA|7G2)[A-HJ-NPR-Z0-9]{14}', re.I)
SHA = re.compile(r'[0-9a-f]{40}')
MAX_FILE = 160 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def _history_signature(info):
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,
            info.st_ctime_ns,info.st_mode,info.st_uid,info.st_gid)


def stable_history_read(path):
    """Refuse links, partial writes, and replacements during a history read."""
    path=Path(path);before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise ValueError('Private history is not a regular file')
    with path.open('rb') as stream:
        if _history_signature(os.fstat(stream.fileno()))!=_history_signature(before):
            raise ValueError('Private history changed before reading')
        value=stream.read();after=os.fstat(stream.fileno())
    if (_history_signature(before)!=_history_signature(after)
            or _history_signature(after)!=_history_signature(path.lstat())):
        raise ValueError('Private history changed during reading')
    return value,before


def _packet_business_bytes(raw):
    def unique_object(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Private history has duplicate JSON keys')
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=unique_object)
    if (not isinstance(value,dict) or 'updated_at' not in value
            or type(value['updated_at']) not in (str,int,float)):
        raise ValueError('Deal packets lack a scalar update timestamp')
    timestamp_type=type(value.pop('updated_at'))
    return timestamp_type,json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def refresh_private_history(active,staged,expected):
    """Only refresh top-level packet timestamps; every business value must match."""
    active=Path(active);staged=Path(staged);result=dict(expected)
    for name,expected_hash in expected.items():
        source=active/name;target=staged/name
        latest,_=stable_history_read(source);copied,target_info=stable_history_read(target)
        latest_hash=hashlib.sha256(latest).hexdigest();copied_hash=hashlib.sha256(copied).hexdigest()
        if latest_hash==expected_hash and copied_hash==expected_hash:continue
        if (name!='.data/deal_packets.json' or expected_hash not in (latest_hash,copied_hash)
                or _packet_business_bytes(latest)!=_packet_business_bytes(copied)):
            raise ValueError('Private business history changed; stage a fresh release')
        # Re-read immediately around the copy. A changing producer fails closed.
        if stable_history_read(source)[0]!=latest or stable_history_read(target)[0]!=copied:
            raise ValueError('Private history changed before timestamp refresh')
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(prefix='.packet-timestamp-',dir=target.parent,delete=False) as stream:
                temporary=Path(stream.name);stream.write(latest);stream.flush();os.fsync(stream.fileno())
                os.fchmod(stream.fileno(),stat.S_IMODE(target_info.st_mode))
                info=os.fstat(stream.fileno())
                if (info.st_uid,info.st_gid)!=(target_info.st_uid,target_info.st_gid):
                    os.fchown(stream.fileno(),target_info.st_uid,target_info.st_gid)
            os.replace(temporary,target);temporary=None
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
        if stable_history_read(source)[0]!=latest or stable_history_read(target)[0]!=latest:
            raise ValueError('Private history changed during timestamp refresh')
        result[name]=latest_hash
    return result


def allowed(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts or '\\' in name:return False
    if name==META:return True
    if len(p.parts)==1:return name in ROOT_FILES or bool(re.fullmatch(r'google[0-9a-z]+\.html',name))
    if p.parts[0] in ('app','tools'):return p.suffix=='.py' and '__pycache__' not in p.parts
    if p.parts[0]=='web':return p.suffix.lower() in ASSETS
    if len(p.parts)==2 and p.parts[0] in PAGE_DIRS:return p.suffix=='.html'
    if len(p.parts)==2 and p.parts[0]=='media':return bool(re.fullmatch(r'[0-7][0-9a-f]\.json',p.name))
    return name in DATA


def catalog_module(root):
    spec=importlib.util.spec_from_file_location('prepared_catalog',Path(root)/'app/catalog.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def private_matches(root,private_file,*,allow_fixture=False):
    private=json.loads(Path(private_file).read_text())
    public=json.loads((Path(root)/'inventory.json').read_text())
    module=catalog_module(root)
    expected=module.public_catalog(private)
    for row in expected['items']:row.pop('photos',None)
    if expected!=public:raise ValueError('Private inventory does not match the public artifact')
    vins=[row.get('vin') for row in private['items']]
    if len(vins)!=len(set(vins)) or not all(module.VIN_PATTERN.fullmatch(str(v)) for v in vins):
        raise ValueError('Private inventory identity set is invalid')
    if not allow_fixture and any('TEST' in v for v in vins):
        raise ValueError('Synthetic inventory cannot enter production')
    return private


def unpack_bundle(bundle,destination,expected_sha):
    """Extract known regular files only. Never extract private data or tar links."""
    if not SHA.fullmatch(expected_sha):raise ValueError('Use a complete reviewed commit SHA')
    destination=Path(destination)
    if any(destination.iterdir()):raise ValueError('Bundle destination must be empty')
    seen=set();total=0
    with tarfile.open(bundle,'r:gz') as archive:
        for member in archive:
            if not member.isfile() or not allowed(member.name) or member.name in seen:
                raise ValueError('Bundle contains an unexpected path or non-regular entry')
            if member.size<0 or member.size>MAX_FILE:raise ValueError('Bundle member is too large')
            total+=member.size
            if total>MAX_TOTAL:raise ValueError('Bundle is too large')
            seen.add(member.name)
            target=destination/member.name;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as source,target.open('xb') as out:
                import shutil
                shutil.copyfileobj(source,out)
            target.chmod(0o644)
    meta=json.loads((destination/META).read_text())
    if meta.get('revision')!=expected_sha:raise ValueError('Bundle revision mismatch')
    hashes=meta.get('files',{})
    if set(hashes)!=(seen-{META}):raise ValueError('Bundle file set mismatch')
    if any(digest(destination/name)!=value for name,value in hashes.items()):
        raise ValueError('Bundle file hash mismatch')
    required={'app/main.py','app/catalog.py','web/app.js','web/pricing.js','web/styles.css',
              'index.html','inventory.json','requirements.txt','tools/public_site.py'}
    if not required<=seen:raise ValueError('Bundle lacks required runtime files')
    for name in seen:
        if name==META or name.startswith(('app/','tools/')) or name=='requirements.txt':continue
        if VIN.search(name):raise ValueError('Public path contains a complete VIN')
        if Path(name).suffix.lower() in {'.html','.json','.xml','.txt','.js','.css','.svg','.webmanifest'}:
            if VIN.search((destination/name).read_text()):raise ValueError('Public file contains a complete VIN')
    return meta


def parse_env(raw):
    result={}
    for line in raw.decode().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key,sep,value=line.partition('=')
            if not sep or key in result:raise ValueError('Environment has duplicate or invalid fields')
            result[key]=value.strip().strip('"').strip("'")
    return result


def inventory_env(raw,path):
    """Change exactly one environment field and preserve all other original bytes."""
    lines=raw.decode().splitlines(keepends=True);matches=0
    for i,line in enumerate(lines):
        if line.startswith('INVENTORY_JSON='):
            ending='\r\n' if line.endswith('\r\n') else '\n'
            lines[i]='INVENTORY_JSON='+str(path)+ending;matches+=1
    if matches!=1:raise ValueError('Expected exactly one existing inventory environment field')
    changed=''.join(lines).encode()
    before=parse_env(raw);after=parse_env(changed)
    if {k:v for k,v in before.items() if k!='INVENTORY_JSON'}!={k:v for k,v in after.items() if k!='INVENTORY_JSON'}:
        raise ValueError('An unrelated environment field changed')
    return changed


def reject_links(root):
    for path in Path(root).rglob('*'):
        if path.is_symlink():raise ValueError('Release or artifact contains a symlink')


def safe_json(path,value,mode=0o600):
    Path(path).write_text(json.dumps(value,sort_keys=True,separators=(',',':')))
    Path(path).chmod(mode)
