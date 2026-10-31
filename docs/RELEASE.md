# Dealer-fulfillment release

The platform generates demand and earns agreed spread. Dealers retain inventory ownership and fulfill customer purchases.

The prior acquisition/resale workflow is superseded. Existing resale orders require manual review.

Built: dealer registry, supplier commitments, quote acceptance, dealer-scoped deposits/refunds, dealer fulfillment, spread reconciliation, reversals, and channel contribution reporting.

Customer UI keeps the branded buying flow. Supplier commercial details are excluded from public catalog exports. Legal seller identity appears on the accepted quote.

Provider calls are tested with fixtures and real SDK signature checks. No real dealer, payment account, title transfer, dispatch, or customer sale has been verified.

Public production remains unchanged until an approved release. The local preview uses pending partner onboarding with payments disabled.

Before launch: approved platform agreements, enrolled dealers, merchant/Connect approval, persistent HTTPS hosting, monitored operations, and a controlled dealer-fulfilled sale with collected spread.

Rollback must preserve orders and payment scope. Do not restore fake inspection claims, URL-driven paid state, or acquisition/resale semantics. Disable new checkouts while reconciling exceptions.
