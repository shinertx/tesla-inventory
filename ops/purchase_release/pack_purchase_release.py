"""Build a public/runtime tar from one reviewed Git SHA. Private JSON stays separate."""
from pathlib import Path
import argparse
import io
import json
import os
import subprocess
import tarfile
import tempfile
from purchase_release_common import (SHA,META,allowed,digest,private_matches,unpack_bundle,safe_json)


def build(repo,revision,private_inventory,output):
    repo=Path(repo).resolve();private_inventory=Path(private_inventory).resolve();output=Path(output).resolve()
    if not SHA.fullmatch(revision):raise ValueError('Use a complete reviewed commit SHA')
    resolved=subprocess.check_output(['git','rev-parse',revision+'^{commit}'],cwd=repo,text=True).strip()
    if resolved!=revision:raise ValueError('Reviewed SHA must resolve exactly')
    relative=private_inventory.relative_to(repo)
    tracked=subprocess.run(['git','ls-files','--error-unmatch','--',str(relative)],cwd=repo,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    committed=subprocess.run(['git','cat-file','-e',revision+':'+relative.as_posix()],cwd=repo,
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if tracked.returncode==0 or committed.returncode==0:
        raise ValueError('Private inventory must never be tracked by Git')
    if private_inventory.is_symlink():raise ValueError('Private inventory cannot be a symlink')
    if output.exists():raise ValueError('Use a new artifact output path')
    with tempfile.TemporaryDirectory(prefix='volts-reviewed-pack-') as temp:
        root=Path(temp)/'source';root.mkdir()
        process=subprocess.Popen(['git','archive','--format=tar',revision],cwd=repo,stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
                for member in archive:
                    if not allowed(member.name) or member.name==META:continue
                    if not member.isfile():raise ValueError('Reviewed runtime contains a link or special file')
                    target=root/member.name;target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as src,target.open('xb') as dst:
                        import shutil
                        shutil.copyfileobj(src,dst)
            if process.wait()!=0:raise ValueError('Git archive failed')
        finally:
            if process.poll() is None:process.kill();process.wait()
            process.stdout.close()
        private=private_matches(root,private_inventory)
        hashes={p.relative_to(root).as_posix():digest(p) for p in sorted(root.rglob('*'))
                if p.is_file() and allowed(p.relative_to(root).as_posix())}
        meta={'version':1,'revision':revision,'files':hashes,
              'private_inventory_sha256':digest(private_inventory),
              'private_inventory_count':len(private['items'])}
        safe_json(root/META,meta,0o644)
        output.parent.mkdir(parents=True,exist_ok=True)
        with tarfile.open(output,'w:gz') as archive:
            for name in sorted([*hashes,META]):
                item=tarfile.TarInfo(name);item.size=(root/name).stat().st_size
                item.mode=0o644;item.uid=item.gid=0;item.mtime=0
                with (root/name).open('rb') as stream:archive.addfile(item,stream)
        output.chmod(0o600)
        check=Path(temp)/'verify';check.mkdir();unpack_bundle(output,check,revision)
    print(json.dumps({'revision':revision,'artifact_sha256':digest(output),
                      'runtime_files':len(hashes),'private_file_in_archive':False,
                      'private_inventory_count':len(private['items'])}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repo',required=True,type=Path)
    parser.add_argument('--sha',required=True);parser.add_argument('--private-inventory',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    build(args.repo,args.sha,args.private_inventory,args.output)
