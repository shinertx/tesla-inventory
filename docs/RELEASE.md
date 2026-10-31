# Dealer-fulfillment release

The platform generates demand and earns agreed spread. Dealers retain inventory ownership and fulfill customer purchases.

The prior acquisition/resale workflow is superseded. Existing resale orders require manual review.

Built: dealer registry, supplier commitments, quote acceptance, dealer-scoped deposits/refunds, dealer fulfillment, spread reconciliation, reversals, and channel contribution reporting.

Customer UI keeps the branded buying flow. Supplier commercial details are excluded from public catalog exports. Legal seller identity appears on the accepted quote.

Provider calls are tested with fixtures and real SDK signature checks. No real dealer, payment account, title transfer, dispatch, or customer sale has been verified.

This release publishes the static customer storefront to GitHub Pages. Customers can browse, view galleries, save, and compare vehicles.

Reservation APIs and live payments are not deployed on GitHub Pages. The storefront labels reservations as coming soon when the API is unavailable. Partner onboarding remains pending.

Vehicle galleries are loaded from versioned static shards. The initial catalog excludes full photo arrays. No server is needed for customer photos.

Current coverage: 10,535 multi-photo vehicles, 3,550 single-photo vehicles, and 827 without a photo. Further source requests returned 403. Complete coverage is not claimed.

Before launch: approved platform agreements, enrolled dealers, merchant/Connect approval, persistent HTTPS hosting, monitored operations, and a controlled dealer-fulfilled sale with collected spread.

Rollback must preserve orders and payment scope. Do not restore fake inspection claims, URL-driven paid state, or acquisition/resale semantics. Disable new checkouts while reconciling exceptions.

## Platform checkout and pricing release

- Market-reference pricing with exact-mileage adjustments and whole-dollar estimates.
- No fixed markup, mandatory discount, or spread ceiling. Extreme gaps require evidence before public repricing.
- Branded deal builder and explicit local drafts on static hosting. No fake orders or deposits.
- Authenticated embedded reservation checkout, with connected-account scope and signed webhook confirmation.
- Full-balance collection and document signing still require approved provider integrations. Automatic spread splitting is not implemented.
- No schema migration; payments stay disabled in production until provider/backend onboarding.
- Roll back if deal drafts, galleries, price disclosures, or customer access fail. Preserve order databases and payment records.
