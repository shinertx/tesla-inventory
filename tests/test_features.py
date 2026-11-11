from tools.features import vehicle_features

def row(vin='7SAYGDED1RF039277',model='Model Y',year=2024,trim='Base',**kw):
    return {'vin':vin,'model':model,'year':year,'dealer_trim':trim,**kw}

def test_drive_code_is_model_specific_and_does_not_invent_hardware():
    y=vehicle_features(row())
    assert y['drivetrain']=='RWD' and y['factory']=='Fremont' and y['drivetrain_basis']=='VIN-derived'
    assert y['hardware'] is None and y['trim_family']=='Other / unspecified'
    truck=vehicle_features(row(vin='7G2CEHED0RA026714',model='Cybertruck',year=2024))
    assert truck['drivetrain']=='AWD' and truck['factory']=='Austin'

def test_hardware_requires_both_explicit_verification_and_evidence():
    assert vehicle_features(row(hardware_generation='HW4',hardware_verified=True))['hardware'] is None
    assert vehicle_features(row(hardware_generation='HW4',hardware_verified=True,hardware_evidence_reference='screen-proof'))['hardware']=='HW4'
    assert vehicle_features(row(hardware_generation='HW4',hardware_verified=False,hardware_evidence_reference='screen-proof'))['hardware'] is None

def test_trim_and_unknown_codes_stay_distinct_from_verified_features():
    values=vehicle_features(row(vin='5YJSA1S22FF087484',model='Model S',year=2015,trim='70D'))
    assert values['drivetrain'] is None
    assert values['factory']=='Fremont'
    assert vehicle_features(row(trim='Performance'))['trim_family']=='Performance'

def test_conservative_infotainment_lfp_and_fsd_tags():
    y24=vehicle_features(row(model='Model Y',year=2024,trim='Long Range AWD with FSD'))
    assert y24['infotainment']=='AMD Ryzen' and y24['fsd_mentioned'] is True and y24['hardware'] is None
    m3_lfp=vehicle_features(row(vin='5YJ3E1EA1PF000001',model='Model 3',year=2023,trim='Base RWD'))
    assert m3_lfp['infotainment']=='AMD Ryzen' and m3_lfp['battery_chemistry']=='LFP (100% Daily)'
    m3_20=vehicle_features(row(vin='5YJ3E1EA1LF000001',model='Model 3',year=2020,trim='FSD Capable'))
    assert m3_20['infotainment']=='Intel Atom' and m3_20['fsd_mentioned'] is False
