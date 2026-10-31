"""Market-reference pricing proposals. No fixed markup or hard spread ceiling."""
from dataclasses import dataclass

@dataclass(frozen=True)
class PricingPolicy:
    buyer_savings_cents: int = 0
    minimum_comparables: int = 5
    minimum_contribution_cents: int = 0
    platform_cost_floor_cents: int = 0
    minimum_buyer_savings_cents: int = 50000

    def __post_init__(self):
        if (self.buyer_savings_cents<0 or self.minimum_comparables<3
            or self.minimum_contribution_cents<0 or self.platform_cost_floor_cents<0
            or self.minimum_buyer_savings_cents<0):
            raise ValueError('Invalid pricing policy')

def propose_price(dealer_net_cents,reference_cents=None,sample_size=0,platform_cost_cents=None,policy=None):
    policy=policy or PricingPolicy()
    if dealer_net_cents<=0:raise ValueError('Dealer proceeds must be positive')
    if platform_cost_cents is not None and platform_cost_cents<0:raise ValueError('Costs cannot be negative')
    supported=bool(reference_cents and sample_size>=policy.minimum_comparables)
    raw_gap=(reference_cents-dealer_net_cents) if supported else 0
    unusual_unverified=bool(supported and raw_gap/dealer_net_cents>.25 and platform_cost_cents is None and (policy.minimum_contribution_cents>0 or policy.platform_cost_floor_cents>0))
    cost_floor=platform_cost_cents if platform_cost_cents is not None else policy.platform_cost_floor_cents
    required_spread=cost_floor+policy.minimum_contribution_cents
    if not supported or unusual_unverified or policy.buyer_savings_cents<=0:
        discount=0
    elif required_spread>0:
        surplus=max(0,raw_gap-required_spread)
        discount=min((surplus//100)*100,policy.buyer_savings_cents)
        if discount<min(policy.minimum_buyer_savings_cents,policy.buyer_savings_cents):
            discount=0
    else:
        discount=policy.buyer_savings_cents
    retail=max(dealer_net_cents,reference_cents-discount) if supported else dealer_net_cents
    spread=retail-dealer_net_cents
    return {'proposed_retail_cents':retail,
        'buyer_savings_cents':max(0,reference_cents-retail) if supported else 0,
        'modeled_gross_spread_cents':spread,
        'modeled_contribution_cents':spread-platform_cost_cents if platform_cost_cents is not None else None,
        'reference_cents':reference_cents if supported else None,'reference_sample':sample_size,
        'pricing_basis':'comparable_asking_prices' if supported else 'source_asking_only',
        'is_optimal_price_proven':False,
        'requires_market_review':bool(supported and max(spread,raw_gap)/dealer_net_cents>.25),
        'costs_verified':platform_cost_cents is not None}


def mileage_reference(target,comparables,policy=None):
    """Fit a bounded mileage adjustment from peer asking prices, excluding the target VIN.

    This is an asking-price estimate, not an appraisal or a proven sale price.
    """
    from statistics import median
    policy=policy or PricingPolicy()
    if target['mileage']<=0:return None,0
    peers=[x for x in comparables if x['vin']!=target['vin'] and x['mileage']>0]
    peers=sorted(peers,key=lambda x:abs(x['mileage']-target['mileage']))[:21]
    if len(peers)<policy.minimum_comparables:return None,len(peers)
    prices=[x['asking_cents'] for x in peers];center=median(prices)
    # Suppress extreme listings before estimating the relationship to mileage.
    clean=[x for x in peers if center*.65<=x['asking_cents']<=center*1.35]
    if len(clean)<policy.minimum_comparables:return None,len(clean)
    mean_miles=sum(x['mileage'] for x in clean)/len(clean)
    mean_price=sum(x['asking_cents'] for x in clean)/len(clean)
    variance=sum((x['mileage']-mean_miles)**2 for x in clean)
    span=max(x['mileage'] for x in clean)-min(x['mileage'] for x in clean)
    slope=sum((x['mileage']-mean_miles)*(x['asking_cents']-mean_price) for x in clean)/variance if variance and span>=5000 else 0
    slope=max(-30,min(0,slope)) # At most $0.30 per mile; never reward more mileage.
    adjustment=max(-10000,min(10000,target['mileage']-median(x['mileage'] for x in clean)))
    estimate=round(center+slope*adjustment)
    return int(round(estimate/100)*100),len(clean)
