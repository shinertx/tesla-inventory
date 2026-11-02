"""Reviewed, narrow projection adapter. Tracking storage and payment guards stay intact."""
import ast
import hashlib
import re

INSPECTED_WRAPPER_SHA256='26de592cf172ec31c10e60d336f24936d7483ec33240e7f5f4e940ba6c87e973'
ADAPTED_WRAPPER_SHA256='b80e440f3d87bd2b137b3ce8e7f41b44b240f74e023d54e591f49d4ad6194214'
HELPER='''

def _public_tracking_stock(value):
    from app.catalog import STOCK_ID_PATTERN, VIN_PATTERN, stock_id_for
    value = str(value or '')
    if STOCK_ID_PATTERN.fullmatch(value):
        return value
    if VIN_PATTERN.fullmatch(value):
        return stock_id_for(value)
    return None


def _public_visit_summary(summary):
    for old, new in (('external_vin_views', 'external_stock_views'), ('all_top_vins', 'all_top_stocks')):
        rows = summary.pop(old, [])
        summary[new] = [{'stock_id': _public_tracking_stock(row.get('vin')), 'views': row['views']}
                        for row in rows if _public_tracking_stock(row.get('vin'))]
    return summary
'''


def adapt(source):
    current=hashlib.sha256(source.encode()).hexdigest()
    if current==ADAPTED_WRAPPER_SHA256:return source
    if current!=INSPECTED_WRAPPER_SHA256:
        raise ValueError('Production wrapper changed; review its new source before adapting it')
    exact={
        "vin = str(body.get('vin') or '')[:24] or None":
            "vin = str(body.get('stock_id') or body.get('vin') or '')[:24] or None",
        "'vin': r.get('vin'),":
            "'stock_id': r.get('stock_id'),\n                'masked_vin': r.get('masked_vin'),",
        "f\"https://voltsandvins.com/?vin={r.get('vin')}\"":
            "f\"https://voltsandvins.com/?id={r.get('stock_id')}\"",
    }
    for old,new in exact.items():
        if source.count(old)!=1:raise ValueError('Production wrapper projection has changed')
        source=source.replace(old,new)
    tree=ast.parse(source)
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='visits_summary')
    ret=function.body[-1]
    if not isinstance(ret,ast.Return) or not isinstance(ret.value,ast.Dict):
        raise ValueError('Unexpected visitor summary return structure')
    lines=source.splitlines(keepends=True)
    # The existing final dictionary is wrapped. Its query and counting code remain unchanged.
    lines[ret.lineno-1]=lines[ret.lineno-1].replace('return {','return _public_visit_summary({',1)
    end=ret.end_lineno-1
    ending='\n' if lines[end].endswith('\n') else ''
    lines[end]=lines[end].rstrip('\n')+')'+ending
    result=''.join(lines)+HELPER
    ast.parse(result)
    return result
