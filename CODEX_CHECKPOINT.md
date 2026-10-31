# Current objective

Align PR #1 with dealer-owned inventory and fulfillment. The platform generates demand and captures agreed spread.

## Decision

User explicitly superseded the own-dealership acquisition/resale model. Dealers remain vehicle owners, sellers, and fulfillers.

## Implemented

Dealer registry, dealer-bound quotes and payment accounts, connected-account deposits/refunds, dealer fulfillment stages, spread settlement/reversals, and demand-channel economics.

Supplier data moved to ignored .data storage. Customer exports omit supplier identity, net prices, and source listing links. Seller identity is disclosed on the final quote.

## Verified

50 regression tests pass. Desktop/mobile browser flows pass with zero JavaScript exceptions. Public exports omit private supplier fields. Local preview is refreshed in dealer_fulfillment mode with payments disabled.

## Next

Push the verified changes to existing PR #1 and verify current-head CI. Actual dealer enrollment and provider proof remain pending.

## Boundaries

No production deployment, real payment, partner enrollment, or customer sale. Actual agreements, dealer credentials, provider approval, and hosting remain external launch requirements.
