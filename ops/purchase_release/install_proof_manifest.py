"""Deployment helper library. Writing is explicit; importing performs no mutations."""
from pathlib import Path
import hashlib,json,re


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_proof(release, backend_revision, catalog_revision, public_context, proof_source):
    root=Path(release)
    assert re.fullmatch('[0-9a-f]{40}',backend_revision)
    assert re.fullmatch('[0-9a-f]{40}',catalog_revision)
    assert all('secret' not in k.lower() and 'path' not in k.lower() for k in public_context)
    (root/'runtime_proof.py').write_text(Path(proof_source).read_text())
    names={str(p.relative_to(root)) for directory in ('app','tools') for p in (root/directory).rglob('*.py')}
    names.add('runtime_proof.py')
    entry='sandbox_entry.py' if public_context.get('sandbox') else 'production_entry.py'
    names.add(entry)
    if not public_context.get('sandbox'):
        names |= {str(p.relative_to(root)) for p in (root/'web').rglob('*') if p.is_file()}
        if (root/'index.html').is_file():names.add('index.html')
    catalog_names={'inventory.json'} | {str(p.relative_to(root)) for p in (root/'media').rglob('*') if p.is_file()}
    catalog_names |= {name for name in ('data/exclusions.json','data/us_zip_centers.json') if (root/name).is_file()}
    manifest={'backend_revision':backend_revision,'catalog_revision':catalog_revision,
              'backend_modules':{name:_sha(root/name) for name in sorted(names)},
              'inventory_sha256':_sha(root/'inventory.json'),'catalog_files':{name:_sha(root/name) for name in sorted(catalog_names)},'public_context':public_context}
    target=root/'.deployment-manifest.json'
    target.write_text(json.dumps(manifest,sort_keys=True));target.chmod(0o644)
    return {'backend_module_count':len(names),'inventory_sha256':manifest['inventory_sha256']}


def patch_entry_proof(entry_path, expected_route):
    import ast
    path=Path(entry_path);source=path.read_text();tree=ast.parse(source)
    matches=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='proof']
    assert len(matches)==1
    node=matches[0]
    assert len(node.body)==1 and isinstance(node.body[0],ast.Return)
    routes=[decorator.args[0].value for decorator in node.decorator_list
            if isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Attribute)
            and decorator.func.attr=='get' and decorator.args and isinstance(decorator.args[0],ast.Constant)]
    assert expected_route in routes
    lines=source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno]=['def proof():\n','    return deployment_proof()\n']
    result=''.join(lines)
    if 'from runtime_proof import deployment_proof\n' not in result:
        result='from runtime_proof import deployment_proof\n'+result
    ast.parse(result);path.write_text(result)
