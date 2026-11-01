"""Explicit public projection. Supplier commercial data never belongs in customer JSON."""
import json
from pathlib import Path


def catalog_exclusions(inventory_path):
    """Read each time so a running API observes new review exclusions."""
    path = Path(inventory_path).parent / 'data' / 'exclusions.json'
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}  # Explicit fixture roots need not contain a production exclusion file.
    except (OSError, ValueError) as exc:
        raise ValueError('Catalog review exclusions are unavailable') from exc
    if not isinstance(data, dict) or any(
        not isinstance(vin, str) or not isinstance(reason, str) or not reason.strip()
        for vin, reason in data.items()
    ):
        raise ValueError('Catalog review exclusions are invalid')
    return data


PUBLIC_FIELDS={'drivetrain','drivetrain_basis','trim_family','factory','factory_basis','location_center','pricing_basis','photo_count','photos','vin','stock_number','model','year','trim','mileage','display_price','pricing_status',
 'city','state','photo','fulfillment','source_observed_at','benchmark_date','expires_at','reservable','availability','title_status',
 'hardware','inspection_status','reference_price','reference_sample','savings_amount'}
PUBLIC_META={'media_version','built_at','count','reservable_count','mode','partner_onboarding_status','availability_note'}

def public_catalog(data):
    return {'meta':{k:v for k,v in data.get('meta',{}).items() if k in PUBLIC_META},
            'items':[{k:v for k,v in x.items() if k in PUBLIC_FIELDS} for x in data.get('items',[])]}
