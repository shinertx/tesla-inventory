from tools.pricing import PricingPolicy,propose_price

def test_large_opportunity_is_not_capped_at_fifteen_hundred():
    result=propose_price(2500000,3500000,12,platform_cost_cents=150000)
    assert result['proposed_retail_cents']==3450000
    assert result['modeled_gross_spread_cents']==950000
    assert result['modeled_contribution_cents']==800000

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
