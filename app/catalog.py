"""Explicit public projection. Supplier commercial data never belongs in customer JSON."""
PUBLIC_FIELDS={'vin','stock_number','model','year','trim','mileage','display_price','pricing_status',
 'city','state','photo','fulfillment','source_observed_at','expires_at','availability','title_status',
 'hardware','inspection_status','reference_price','reference_sample'}
PUBLIC_META={'built_at','count','mode','partner_onboarding_status','availability_note'}

def public_catalog(data):
    return {'meta':{k:v for k,v in data.get('meta',{}).items() if k in PUBLIC_META},
            'items':[{k:v for k,v in x.items() if k in PUBLIC_FIELDS} for x in data.get('items',[])]}
