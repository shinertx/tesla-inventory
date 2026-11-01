# Vehicle price and complete purchase quote

The storefront shows a vehicle price. Delivery, tax, title and registration stay separate until the selling dealer confirms them.

## Price rule

New requests save the server catalog vehicle price, exact catalog revision and comparison snapshot. The browser submits its displayed price for a consistency check. A changed price requires review before request creation.

The quoted vehicle price cannot exceed the saved request price. Lower prices are allowed. If the vehicle cannot be supplied profitably at that price, cancel the unavailable request. Do not hide a vehicle-price increase in delivery or other fees. Any replacement vehicle needs the buyer's agreement and its own request.

A request does not reserve inventory or guarantee availability. A confirmed seller hold, approved complete quote and accepted terms still precede the $250 deposit.

Historical requests without a saved price have no invented guarantee. Their existing explicit quote and acceptance flow remains available.

## Comparison and margin

Pricing remains deterministic and keeps uncapped modeled spread. This release does not change prices or the pricing algorithm. Peer asking-price comparisons are estimates, not sold-price proof. New private requests retain their original comparison basis after catalog changes.

## Payment readiness

The existing JENNi/Jockey production Stripe binding was found in configuration. Its live public identity and capabilities were not verified because operator access expired. The label Flow is not yet matched to that account.

Production checkout remains disabled without a real licensed seller, agreed terms, eligible payment access and actual vehicle evidence. Jockey remains a draft label. Financing, carrier booking and full-photo feeds still require authorized provider or dealer access. Vendor inquiries remain drafts.
