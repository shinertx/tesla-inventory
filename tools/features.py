"""Conservative customer specifications. No hardware inference from year or VIN."""
import re

def vehicle_features(row):
    vin=row['vin'];model=row['model'];year=row['year'];trim=str(row.get('dealer_trim') or '')
    drive=None;basis=None
    if re.search(r'\b(AWD|all[- ]wheel|dual[- ]motor|tri[- ]motor)\b',trim,re.I):drive='AWD';basis='listed'
    elif re.search(r'\b(RWD|rear[- ]wheel)\b',trim,re.I):drive='RWD';basis='listed'
    # Only apply motor tables within the documented model/year ranges.
    code=vin[7]
    if model=='Model Y' and 2020<=year<=2026:
        if code in 'E F K L'.split():drive='AWD';basis='VIN-derived'
        elif code in 'D J R S'.split():drive='RWD';basis='VIN-derived'
    if model=='Model 3' and 2017<=year<=2023:
        if code in ('B','C'):drive='AWD';basis='VIN-derived'
        elif code in ('A','R','S'):drive='RWD';basis='VIN-derived'
    if model=='Model 3' and 2024<=year<=2026:
        if code in ('B','K','T'):drive='AWD';basis='VIN-derived'
        elif code in ('A','J','R','S'):drive='RWD';basis='VIN-derived'
    if model=='Cybertruck' and 2024<=year<=2026 and code in ('D','E'):
        drive='AWD';basis='VIN-derived'
    factory=None
    if vin[:3] in ('5YJ','7SA') and vin[10]=='F':factory='Fremont'
    elif vin[:3] in ('7SA','7G2') and vin[10]=='A':factory='Austin'
    listed_trim=next((name for name in ('Plaid','Performance','Long Range','Standard Range') if name.lower() in trim.lower()),'Other / unspecified')
    hardware=row.get('hardware_generation') if row.get('hardware_verified') is True and row.get('hardware_evidence_reference') else None
    if hardware not in ('HW3','HW4'):hardware=None
    return {'drivetrain':drive,'drivetrain_basis':basis,'trim_family':listed_trim,'factory':factory,'factory_basis':'VIN-derived' if factory else None,'hardware':hardware}
