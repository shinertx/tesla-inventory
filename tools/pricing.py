"""Market-reference pricing proposals. No fixed markup or hard spread ceiling."""
from dataclasses import dataclass

@dataclass(frozen=True)
class PricingPolicy:
    buyer_savings_cents: int = 50000
    minimum_comparables: int = 5

    def __post_init__(self):
        if self.buyer_savings_cents<0 or self.minimum_comparables<3:raise ValueError('Invalid pricing policy')

def propose_price(dealer_net_cents,reference_cents=None,sample_size=0,platform_cost_cents=None,policy=None):
    policy=policy or PricingPolicy()
    if dealer_net_cents<=0:raise ValueError('Dealer proceeds must be positive')
    supported=bool(reference_cents and sample_size>=policy.minimum_comparables)
    retail=max(dealer_net_cents,reference_cents-policy.buyer_savings_cents) if supported else dealer_net_cents
    spread=retail-dealer_net_cents
    return {'proposed_retail_cents':retail,'modeled_gross_spread_cents':spread,
        'modeled_contribution_cents':spread-platform_cost_cents if platform_cost_cents is not None else None,
        'reference_cents':reference_cents if supported else None,'reference_sample':sample_size,
        'pricing_basis':'comparable_asking_prices' if supported else 'source_asking_only',
        'is_optimal_price_proven':False}
