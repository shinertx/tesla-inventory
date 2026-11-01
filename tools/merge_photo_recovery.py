"""Merge a reviewed VIN-photo delta without rebuilding inventory or touching prices."""
import argparse,json
from pathlib import Path
from tools.media import normalize_photos
from tools.inventory import valid_vin

def merge(existing, delta):
    result=dict(existing)
    for vin,photos in delta.items():
        if not valid_vin(vin):raise ValueError('Invalid VIN in photo recovery delta')
        # Recovery already includes the current primary for these limited galleries.
        result[vin]=normalize_photos(result.get(vin,[])+photos)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gallery',type=Path,required=True)
    p.add_argument('--delta',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    gallery=json.loads(a.gallery.read_text())
    delta=json.loads(a.delta.read_text())
    result=merge(gallery,delta)
    a.output.write_text(json.dumps(result,separators=(',',':')))
    print(json.dumps({'gallery_vins':len(gallery),'delta_vins':len(delta),'merged_vins':len(result)}))

if __name__=='__main__':main()
