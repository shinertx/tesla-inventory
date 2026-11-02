"""Local-only release safety tests. No network, systemd, credentials, or real DBs."""
from pathlib import Path
import ast
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from purchase_release_common import (allowed,inventory_env,parse_env,unpack_bundle,
    private_matches,digest,safe_json,catalog_module,META,refresh_private_history)
from stock_wrapper_adapter import adapt,INSPECTED_WRAPPER_SHA256
from pack_purchase_release import build
from install_purchase_release import guard_environment,sandbox_frontend,preserving_inventory
from install_purchase_proof import install as install_proof

HERE=Path(__file__).parent
SOURCE=HERE.parents[1]


class ReleaseSafety(unittest.TestCase):
    def test_allowlist_rejects_private_and_traversal(self):
        for name in ('.data/transaction_inventory.json','.env','../app/main.py','/app/main.py',
                     'app/../secret.py','orders.db','media/sandbox.svg','data/source_snapshot.json'):
            self.assertFalse(allowed(name),name)
        for name in ('app/main.py','tools/build.py','web/app.js','v/VV-012345ABCDEF.html','media/7f.json'):
            self.assertTrue(allowed(name),name)

    def test_only_inventory_environment_changes(self):
        raw=b'# retained\nCHECKOUT_ENABLED=false\nSTRIPE_SECRET_KEY=test-placeholder\nINVENTORY_JSON=/old\n'
        result=inventory_env(raw,'/current/.data/transaction_inventory.json')
        self.assertEqual(result.replace(b'/current/.data/transaction_inventory.json',b'/old'),raw)
        self.assertEqual(parse_env(result)['CHECKOUT_ENABLED'],'false')

    def test_duplicate_inventory_environment_refused(self):
        with self.assertRaises(ValueError):inventory_env(b'INVENTORY_JSON=a\nINVENTORY_JSON=b\n','c')

    def test_production_gates_cannot_be_enabled(self):
        env=dict.fromkeys(('SANDBOX_MODE','CHECKOUT_ENABLED','BALANCE_CHECKOUT_ENABLED','PLATFORM_AGREEMENTS_VERIFIED'),'false')
        guard_environment(env,'production')
        for key in (*env,'STRIPE_AUTHORIZATION_WRITES_VERIFIED'):
            with self.assertRaises(ValueError):guard_environment({**env,key:'true'},'production')

    def test_sandbox_rejects_live_credentials(self):
        with self.assertRaises(ValueError):guard_environment({'SANDBOX_MODE':'true','STRIPE_SECRET_KEY':'rk_live_placeholder'},'sandbox')

    def test_tar_links_traversal_duplicates_refused(self):
        for bad in ('../escape','app/link.py','app/main.py'):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as temp:
                temp=Path(temp);bundle=temp/'bad.tar.gz';dest=temp/'out';dest.mkdir()
                with tarfile.open(bundle,'w:gz') as archive:
                    item=tarfile.TarInfo(bad)
                    if bad.endswith('link.py'):item.type=tarfile.SYMTYPE;item.linkname='/etc/passwd';archive.addfile(item)
                    elif bad=='app/main.py':
                        for _ in range(2):item.size=1;archive.addfile(item,io.BytesIO(b'x'))
                    else:item.size=1;archive.addfile(item,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):unpack_bundle(bundle,dest,'a'*40)

    def test_already_reviewed_wrapper_is_preserved_on_later_releases(self):
        source=(Path(__file__).parent/'production_entry.stock-candidate.py').read_text()
        self.assertEqual(adapt(source),source)
        with self.assertRaises(ValueError):adapt(source+'\n# unreviewed edit')

    def test_wrapper_adapter_is_narrow_and_hash_pinned(self):
        source=(HERE/'production_entry.inspected.py').read_text();result=adapt(source)
        self.assertIn("body.get('stock_id') or body.get('vin')",result)
        self.assertIn("'stock_id': r.get('stock_id')",result)
        self.assertIn('?id=',result)
        before=ast.parse(source);after=ast.parse(result)
        for name in ('_require_inactive_live_environment','_require_zero_approved_sellers','jobs_status','_init_visits_table'):
            a=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name==name)
            b=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(a),ast.dump(b))
        with self.assertRaises(ValueError):adapt(source+'\n# unreviewed\n')

    def test_wrapper_history_summary_contains_only_stock_ids(self):
        source=adapt((HERE/'production_entry.inspected.py').read_text())
        tree=ast.parse(source)
        module=catalog_module(SOURCE)
        import sys,types
        original=sys.modules.get('app.catalog');sys.modules['app.catalog']=module
        try:
            helpers=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name.startswith('_public_')],type_ignores=[])
            namespace={};exec(compile(helpers,'helpers','exec'),namespace)
            result=namespace['_public_visit_summary']({'external_vin_views':[{'vin':'7SAYGDEE0TEST0001','views':2}],
                'all_top_vins':[{'vin':'VV-012345ABCDEF','views':3}],'total_events':5})
            self.assertNotIn('7SAYGDEE0TEST0001',json.dumps(result))
            self.assertEqual(result['external_stock_views'][0]['views'],2)
            self.assertEqual(result['all_top_stocks'][0]['stock_id'],'VV-012345ABCDEF')
        finally:
            if original is None:sys.modules.pop('app.catalog',None)
            else:sys.modules['app.catalog']=original

    def test_sandbox_frontend_is_test_only(self):
        with tempfile.TemporaryDirectory() as temp:
            index=Path(temp)/'index.html';index.write_text('<html><head><meta name="robots" content="index,follow"><link rel="canonical" href="https://voltsandvins.com/"></head><body data-preset="all">hello</body></html>')
            sandbox_frontend(index);result=index.read_text()
            self.assertIn('noindex,nofollow',result);self.assertIn('STRIPE TEST PAYMENTS ONLY',result)
            self.assertIn('https://hank.jockeyvc.com/volts-sandbox/',result)

    def make_repo(self,root):
        for directory in ('app','tools','web','media'): (root/directory).mkdir()
        (root/'app/catalog.py').write_bytes((SOURCE/'app/catalog.py').read_bytes())
        (root/'app/main.py').write_text('')
        (root/'tools/public_site.py').write_text('')
        for file in ('app.js','pricing.js','styles.css'):(root/'web'/file).write_text('')
        (root/'index.html').write_text('<html><head></head><body></body></html>')
        (root/'requirements.txt').write_text('')
        private={'meta':{'count':1},'items':[{'vin':'5YJ3E1EA0JF000001','year':2018,'model':'Model 3','display_price':19000,'photos':[]}]}
        public=catalog_module(root).public_catalog(private)
        for row in public['items']:row.pop('photos',None)
        safe_json(root/'inventory.json',public,0o644)
        data=root/'.data';data.mkdir();safe_json(data/'transaction_inventory.json',private)
        (root/'.gitignore').write_text('.data/\n__pycache__/\n')
        for cmd in (['git','init','-q'],['git','config','user.name','Local Test'],
                    ['git','config','user.email','local@example.invalid'],['git','add','.'],
                    ['git','commit','-qm','Local fixture']):
            subprocess.run(cmd,cwd=root,check=True,stdout=subprocess.DEVNULL)
        return subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()

    def test_reviewed_bundle_excludes_private_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();sha=self.make_repo(root)
            bundle=Path(temp)/'runtime.tar.gz';build(root,sha,root/'.data/transaction_inventory.json',bundle)
            with tarfile.open(bundle) as archive:self.assertFalse(any(n.startswith('.data') for n in archive.getnames()))
            out=Path(temp)/'out';out.mkdir();unpack_bundle(bundle,out,sha)
            private_matches(out,root/'.data/transaction_inventory.json')
            data=json.loads((root/'.data/transaction_inventory.json').read_text());data['items'][0]['display_price']=1
            safe_json(root/'.data/transaction_inventory.json',data)
            with self.assertRaises(ValueError):private_matches(out,root/'.data/transaction_inventory.json')

    def test_private_tracking_file_cannot_be_packed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();self.make_repo(root)
            subprocess.run(['git','add','-f','.data/transaction_inventory.json'],cwd=root,check=True)
            with self.assertRaises(ValueError):build(root,subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),root/'.data/transaction_inventory.json',Path(temp)/'x.tar.gz')

    def test_private_file_in_reviewed_commit_is_refused_even_if_untracked_now(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();self.make_repo(root)
            subprocess.run(['git','add','-f','.data/transaction_inventory.json'],cwd=root,check=True)
            subprocess.run(['git','commit','-qm','Private fixture must be rejected'],cwd=root,check=True)
            sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            subprocess.run(['git','rm','--cached','-q','.data/transaction_inventory.json'],cwd=root,check=True)
            with self.assertRaises(ValueError):build(root,sha,root/'.data/transaction_inventory.json',Path(temp)/'x.tar.gz')

    def test_extended_proof_detects_private_and_public_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.make_repo(root)
            (root/'production_entry.py').write_text('')
            install_proof(root,'a'*40,{'charges_disabled':True})
            spec=importlib.util.spec_from_file_location('release_proof',root/'runtime_proof.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(module.deployment_proof()['artifact_verification'],'match')
            original=(root/'.data/transaction_inventory.json').read_bytes()
            (root/'.data/transaction_inventory.json').write_text('{}')
            self.assertFalse(module.deployment_proof()['private_inventory_manifest_match'])
            self.assertEqual(module.deployment_proof()['artifact_verification'],'mismatch')
            (root/'.data/transaction_inventory.json').write_bytes(original)
            (root/'web/unexpected.js').write_text('unexpected public file')
            self.assertFalse(module.deployment_proof()['public_artifact_manifest_match'])
            self.assertEqual(module.deployment_proof()['artifact_verification'],'mismatch')

    def test_sandbox_extended_proof_includes_preserved_fixture_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.make_repo(root)
            (root/'sandbox_entry.py').write_text('')
            (root/'media/sandbox.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
            install_proof(root,'b'*40,{'sandbox':True})
            spec=importlib.util.spec_from_file_location('sandbox_release_proof',root/'runtime_proof.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(module.deployment_proof()['artifact_verification'],'match')

    def test_unchanged_release_proof_does_not_rehash_artifact_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.make_repo(root)
            (root/'production_entry.py').write_text('')
            install_proof(root,'c'*40,{'charges_disabled':True})
            spec=importlib.util.spec_from_file_location('fast_release_proof',root/'runtime_proof.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with patch.object(module,'_sha256',wraps=module._sha256) as hashed:
                for _ in range(2):
                    result=module.deployment_proof()
                    self.assertEqual(result['artifact_verification'],'match')
                    self.assertEqual(result['inventory_count'],1)
                self.assertEqual(hashed.call_count,0)

    def test_same_size_edits_with_restored_mtime_invalidate_public_and_private_proof(self):
        for name in ('web/app.js','.data/transaction_inventory.json'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);self.make_repo(root)
                (root/'production_entry.py').write_text('')
                if name=='web/app.js':(root/name).write_text('before')
                install_proof(root,'d'*40,{'charges_disabled':True})
                spec=importlib.util.spec_from_file_location('changed_release_proof',root/'runtime_proof.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                self.assertEqual(module.deployment_proof()['artifact_verification'],'match')
                target=root/name;before=target.stat();original=target.read_bytes()
                changed=b'after!' if name=='web/app.js' else original.replace(b'19000',b'19001')
                self.assertEqual(len(changed),len(original));self.assertNotEqual(changed,original)
                target.write_bytes(changed)
                os.utime(target,ns=(before.st_atime_ns,before.st_mtime_ns))
                self.assertEqual(target.stat().st_mtime_ns,before.st_mtime_ns)
                with patch.object(module,'_sha256',wraps=module._sha256) as hashed:
                    result=module.deployment_proof()
                    self.assertEqual(result['artifact_verification'],'mismatch')
                    hashed.assert_called_once_with(target.resolve())
                if name.startswith('.data/'):
                    self.assertFalse(result['private_inventory_manifest_match'])
                else:self.assertFalse(result['public_artifact_manifest_match'])

    def test_fingerprint_fast_path_still_detects_deleted_and_unexpected_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.make_repo(root)
            (root/'production_entry.py').write_text('')
            install_proof(root,'e'*40,{'charges_disabled':True})
            spec=importlib.util.spec_from_file_location('file_set_release_proof',root/'runtime_proof.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(module.deployment_proof()['artifact_verification'],'match')
            target=root/'web/pricing.js';original=target.read_bytes();target.unlink()
            self.assertEqual(module.deployment_proof()['artifact_verification'],'mismatch')
            target.write_bytes(original)
            self.assertEqual(module.deployment_proof()['artifact_verification'],'match')
            (root/'browse').mkdir();(root/'browse/unexpected.html').write_text('unexpected')
            self.assertFalse(module.deployment_proof()['public_artifact_manifest_match'])
            self.assertEqual(module.deployment_proof()['artifact_verification'],'mismatch')

    def history_pair(self,root):
        active=root/'active';staged=root/'staged';name='.data/deal_packets.json'
        body={'updated_at':'before','packets':[{'id':'packet-fixture','amount_cents':100,'accepted':True,'updated_at':'business-timestamp'}]}
        for release in (active,staged):
            (release/'.data').mkdir(parents=True)
            safe_json(release/name,body)
        return active,staged,name,body

    def test_packet_timestamp_refresh_updates_staged_bytes_and_history_hash_at_both_checks(self):
        for anchor in ('active','staged'):
            with self.subTest(anchor=anchor),tempfile.TemporaryDirectory() as temp:
                active,staged,name,body=self.history_pair(Path(temp))
                prior=digest(staged/name)
                safe_json(active/name,{**body,'updated_at':'latest-producer-timestamp'})
                expected={name:digest(active/name) if anchor=='active' else prior}
                result=refresh_private_history(active,staged,expected)
                self.assertEqual((staged/name).read_bytes(),(active/name).read_bytes())
                self.assertEqual(result[name],digest(active/name))
                self.assertEqual((staged/name).stat().st_mode&0o777,0o600)
                self.assertEqual(refresh_private_history(active,staged,result),result)

    def test_packet_refresh_refuses_business_edits_new_rows_and_nested_timestamp_changes(self):
        for change in ('amount','new-row','nested-time','boolean-type'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temp:
                active,staged,name,body=self.history_pair(Path(temp))
                expected={name:digest(staged/name)};original=(staged/name).read_bytes()
                changed=json.loads(json.dumps(body));changed['updated_at']='new'
                if change=='amount':changed['packets'][0]['amount_cents']=101
                elif change=='new-row':changed['packets'].append({'id':'new-business-row'})
                elif change=='nested-time':changed['packets'][0]['updated_at']='changed-business-time'
                else:changed['packets'][0]['accepted']=1
                safe_json(active/name,changed)
                with self.assertRaisesRegex(ValueError,'business history changed'):
                    refresh_private_history(active,staged,expected)
                self.assertEqual((staged/name).read_bytes(),original)

    def test_other_private_history_never_gets_timestamp_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            active,staged,_,body=self.history_pair(Path(temp));name='.data/source_snapshot.json'
            safe_json(active/name,body);safe_json(staged/name,body)
            expected={name:digest(staged/name)};safe_json(active/name,{**body,'updated_at':'new'})
            with self.assertRaisesRegex(ValueError,'business history changed'):
                refresh_private_history(active,staged,expected)

    def test_packet_producer_change_during_refresh_stops_cutover(self):
        import purchase_release_common as common
        with tempfile.TemporaryDirectory() as temp:
            active,staged,name,body=self.history_pair(Path(temp));expected={name:digest(staged/name)}
            safe_json(active/name,{**body,'updated_at':'new'})
            actual_read=common.stable_history_read;reads=0
            def changing_read(path):
                nonlocal reads
                result=actual_read(path)
                if Path(path)==active/name:
                    reads+=1
                    if reads==2:safe_json(active/name,{**body,'updated_at':'changed-during-refresh'})
                return result
            with patch.object(common,'stable_history_read',side_effect=changing_read):
                with self.assertRaisesRegex(ValueError,'changed during timestamp refresh'):
                    refresh_private_history(active,staged,expected)


if __name__=='__main__':unittest.main()
