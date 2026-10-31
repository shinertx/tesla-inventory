"""Explicit public projection. Supplier commercial data never belongs in customer JSON."""
PUBLIC_FIELDS={'drivetrain','drivetrain_basis','trim_family','factory','factory_basis','location_center','pricing_basis','photo_count','photos','vin','stock_number','model','year','trim','mileage','display_price','pricing_status',
 'city','state','photo','fulfillment','source_observed_at','benchmark_date','expires_at','reservable','availability','title_status',
 'hardware','inspection_status','reference_price','reference_sample','savings_amount'}
PUBLIC_META={'media_version','built_at','count','reservable_count','mode','partner_onboarding_status','availability_note'}

def public_catalog(data):
    return {'meta':{k:v for k,v in data.get('meta',{}).items() if k in PUBLIC_META},
            'items':[{k:v for k,v in x.items() if k in PUBLIC_FIELDS} for x in data.get('items',[])]}
