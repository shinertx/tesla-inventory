"""Copy only customer-facing files into a fresh static deployment directory."""
import argparse
import json
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES=frozenset({'index.html','404.html','inventory.json','sitemap.xml','robots.txt',
    'llms.txt','llms-full.txt','openapi.json','search-release.json',
    'voltsandvins-indexnow-key.txt','CNAME','.nojekyll','favicon.ico','favicon.svg',
    'manifest.webmanifest'})
PAGE_DIRECTORIES=('v','browse','models','years','states','deals')
DATA_FILES=('us_zip_centers.json','us_city_centers.json')
ASSET_SUFFIXES=frozenset({'.js','.css','.svg','.png','.jpg','.jpeg','.webp','.avif',
    '.gif','.ico','.woff','.woff2','.webmanifest'})
TEXT_SUFFIXES=frozenset({'.html','.json','.xml','.txt','.js','.css','.svg','.webmanifest'})
VIN_RE=re.compile(r'(?:5YJ|7SA|7G2)[A-HJ-NPR-Z0-9]{14}',re.I)


def is_public_artifact(path):
    """Shared path boundary for deployment copies and scheduled Git publication."""
    path=Path(path)
    if path.is_absolute() or '..' in path.parts:return False
    parts=path.parts
    if len(parts)==1:return path.name in ROOT_FILES or bool(re.fullmatch(r'google[0-9a-z]+\.html',path.name))
    if len(parts)==2 and parts[0] in PAGE_DIRECTORIES:return path.suffix=='.html'
    if parts[0]=='web':return path.suffix.lower() in ASSET_SUFFIXES
    if len(parts)==2 and parts[0]=='media':return bool(re.fullmatch(r'[0-7][0-9a-f]\.json',path.name))
    return len(parts)==2 and parts[0]=='data' and path.name in DATA_FILES


def public_files(source=ROOT):
    """Validate and list public files without copying or running external actions."""
    source=Path(source).resolve()
    if not source.is_dir():raise ValueError('Public source directory is missing')
    paths=[]
    for path in source.iterdir():
        verification=bool(re.fullmatch(r'google[0-9a-z]+\.html',path.name))
        if path.is_file() and verification and path.read_text().strip()!='google-site-verification: '+path.name:
            raise ValueError('Google verification file has unexpected content')
        if path.is_file() and (path.name in ROOT_FILES or verification):
            paths.append(path)
    for directory in PAGE_DIRECTORIES:
        paths.extend((source/directory).glob('*.html'))
    paths.extend(p for p in (source/'web').rglob('*') if p.is_file() and p.suffix.lower() in ASSET_SUFFIXES)
    paths.extend(p for p in (source/'media').glob('*.json') if is_public_artifact(p.relative_to(source)))
    paths.extend(source/'data'/name for name in DATA_FILES if (source/'data'/name).is_file())
    paths=sorted(set(paths))
    relative={p.relative_to(source).as_posix() for p in paths}
    required={'index.html','inventory.json','sitemap.xml','robots.txt','web/app.js','web/pricing.js','web/styles.css'}
    if not required<=relative:
        raise ValueError('Required customer assets are missing')
    # Validate before creating the destination, so a failure cannot publish a partial site.
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError('Public files must not link outside the source directory')
        if VIN_RE.search(path.relative_to(source).as_posix()):
            raise ValueError('Public filename contains a full vehicle identity')
        if path.suffix.lower() in TEXT_SUFFIXES:
            if VIN_RE.search(path.read_text()):
                raise ValueError('Public asset contains a full vehicle identity')
    return paths


def build_public_site(source=ROOT,output=None):
    source=Path(source).resolve()
    output=Path(output or source/'dist').resolve()
    if not source.is_dir() or output==source or source.is_relative_to(output):
        raise ValueError('Use a separate public deployment directory')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Public deployment directory must be empty')
    paths=public_files(source)
    relative={p.relative_to(source).as_posix() for p in paths}
    output.mkdir(parents=True,exist_ok=True)
    total=0
    for path in paths:
        dest=output/path.relative_to(source)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest)
        total+=dest.stat().st_size
    return {'count':len(paths),'bytes':total,'files':sorted(relative)}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=build_public_site(args.source,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='files'}))
