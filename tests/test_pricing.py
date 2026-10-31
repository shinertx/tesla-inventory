from tools.pricing import PricingPolicy,propose_price

def test_large_opportunity_is_not_capped_at_fifteen_hundred():
    result=propose_price(2500000,3500000,12,platform_cost_cents=150000)
    assert result['proposed_retail_cents']==3500000
    assert result['modeled_gross_spread_cents']==1000000
    assert result['modeled_contribution_cents']==850000

def test_no_reference_does_not_invent_a_markup_or_optimal_price():
    result=propose_price(2500000,3500000,2)
    assert result['proposed_retail_cents']==2500000
    assert result['pricing_basis']=='source_asking_only'
    assert result['modeled_contribution_cents'] is None
    assert not result['is_optimal_price_proven']

def test_lower_agreed_dealer_net_increases_spread_at_supported_retail():
    first=propose_price(2500000,3500000,12)
    negotiated=propose_price(2400000,3500000,12)
    assert first['proposed_retail_cents']==negotiated['proposed_retail_cents']
    assert negotiated['modeled_gross_spread_cents']==first['modeled_gross_spread_cents']+100000

def test_buyer_price_buffer_is_a_policy_not_a_margin_cap():
    result=propose_price(2500000,3500000,12,policy=PricingPolicy(buyer_savings_cents=100000))
    assert result['proposed_retail_cents']==3400000
    assert result['modeled_gross_spread_cents']==900000


def test_mileage_reference_excludes_itself_and_prices_different_mileage_from_peers():
    from tools.pricing import mileage_reference
    peers=[{'vin':str(i),'mileage':10000+i*5000,'asking_cents':4000000-i*100000} for i in range(9)]
    low={'vin':'new-low','mileage':20000};high={'vin':'new-high','mileage':40000}
    a,n=mileage_reference(low,peers);b,_=mileage_reference(high,peers)
    assert a>b and n>=5
    changed=[dict(x,asking_cents=99000000) if x['vin']=='4' else x for x in peers]
    assert mileage_reference(peers[4],changed)==mileage_reference(peers[4],peers)


def test_reference_does_not_reward_mileage_or_use_too_few_peers():
    from tools.pricing import mileage_reference
    target={'vin':'target','mileage':20000}
    assert mileage_reference({**target,'mileage':0},[])[0] is None
    assert mileage_reference(target,[{'vin':'other','mileage':15000,'asking_cents':2000000}])[0] is None
    peers=[{'vin':str(i),'mileage':i*10000,'asking_cents':3000000+i*100000} for i in range(6)]
    assert mileage_reference(target,peers)[0]==mileage_reference({**target,'mileage':40000},peers)[0]


def test_unusual_gap_is_flagged_without_capping_private_opportunity():
    result=propose_price(2500000,5000000,12)
    assert result['proposed_retail_cents']==5000000
    assert result['modeled_gross_spread_cents']==2500000
    assert result['requires_market_review'] and not result['costs_verified']


def test_negative_costs_are_rejected():
    import pytest
    with pytest.raises(ValueError):propose_price(2500000,3500000,12,platform_cost_cents=-100)


def test_buyer_savings_allocated_only_after_costs_and_minimum_contribution():
    policy=PricingPolicy(buyer_savings_cents=150000,minimum_contribution_cents=100000,platform_cost_floor_cents=130000,minimum_buyer_savings_cents=50000)
    # Gap ($2,000) is below verified costs ($1,500) + minimum contribution ($1,000) = $2,500 -> zero buyer discount
    tight=propose_price(2500000,2700000,12,platform_cost_cents=150000,policy=policy)
    assert tight['proposed_retail_cents']==2700000
    assert tight['buyer_savings_cents']==0
    # Gap ($3,200) leaves $700 surplus above $2,500 required spread -> exact $700 buyer discount
    partial=propose_price(2500000,2820000,12,platform_cost_cents=150000,policy=policy)
    assert partial['proposed_retail_cents']==2750000
    assert partial['buyer_savings_cents']==70000
    assert partial['modeled_gross_spread_cents']==250000
    assert partial['modeled_contribution_cents']==100000
    # Gap ($4,500) leaves $2,000 surplus above $2,500 -> capped at $1,500 policy buyer discount, $2,000 net contribution
    ample=propose_price(2500000,2950000,12,platform_cost_cents=150000,policy=policy)
    assert ample['proposed_retail_cents']==2800000
    assert ample['buyer_savings_cents']==150000
    assert ample['modeled_gross_spread_cents']==300000
    assert ample['modeled_contribution_cents']==150000
