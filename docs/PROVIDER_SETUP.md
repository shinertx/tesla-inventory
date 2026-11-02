# Provider setup and launch evidence

Status: provider access is not approved. Configuration is not live-service proof.

## Existing runtime

Production has zero approved sellers, no Stripe credentials, and no finance or transport credentials. Payments and ACH remain disabled. The isolated sandbox has Stripe TEST access and one synthetic seller. A prior actual TEST deposit/refund succeeded. These facts were refreshed November 1, 2026.

## Shipping integration included here

`SuperDispatchPricingClient` uses the published Pricing Insights v1 endpoint, X-API-Key authentication, vehicle characteristics, and success envelope. Money uses decimal conversion. Redirects and automatic retries are disabled. Missing credentials, malformed prices, quota errors, and unsupported routes fail clearly.

This service returns a recommended price. It does not accept a carrier bid, book a shipment, verify insurance, or promise pickup/delivery dates. The $200 customer shipping buffer is separate from the carrier estimate.

Private configuration:

- `SUPER_DISPATCH_API_KEY`: issued by the provider; store in the existing protected runtime environment.
- `SHIPPING_ESTIMATES_ENABLED=true`: operator activation after approved access. Default is false.

`GET /api/admin/integrations` requires the existing operator bearer. It lists configuration and missing checkout gates without exposing keys. Configured and enabled do not mean provider-approved or live-tested.

`POST /api/admin/orders/{id}/shipping-estimate` requires operator authentication and JSON `{"is_inoperable": false}` with confirmed operability. It uses the selected vehicle city/state and request delivery ZIP. It never submits customer names, emails, payment details, or credit data. Successful estimates are cached for 15 minutes in private order events. Closed requests are rejected. Requests are bounded to six uncached calls per order per hour. One service process serializes provider calls.

Returned `cache_expires_at` is our cache lifetime. It is not a carrier quote expiry. The response always marks `binding=false` and `carrier_booked=false`. Estimates do not approve retail quotes, create holds, alter order/payment/transport state, or send notifications. Carrier costs stay on the authenticated operator route. The customer order exposes only a fresh customer-price estimate, its timestamp, cache expiry and nonbinding notice. The receipt must match the current route. Customer status reads never call the provider. Expired, malformed, disabled-provider and changed-route receipts are hidden. A final written quote takes precedence.

Sources: https://developer.superdispatch.com/pricing-insights/docs/quickstart/ ; https://developer.superdispatch.com/pricing-insights/docs/authentication/ ; https://developer.superdispatch.com/pricing-insights/docs/response-handling/ ; https://developer.superdispatch.com/pricing-insights/reference/get-recommended-price-api-v-1-recommended-price-post/ . The raw YAML download returned 403; the public reference supplied the schema.

## Not implemented without approved contracts

RunBuggy and AutoFi API endpoints from the earlier draft were unverified. They are not included. No APR, lender name, approval, funding, shipment window, or seller verification is generated from a default. Legacy unverified adapters now fail before any network call. The legacy instant-quote helper returns estimated amounts only; it cannot invent evidence, holds, title status or accepted quote terms.

AutoFi marketplace integration is a partnership onboarding process: https://www.autofi.com/marketplaces/ . RunBuggy access requires its approved account documentation: https://docs.runbuggy.com/auth . A working integration requires credentials and a documented contract for the chosen product.

## Deposit activation

1. Select and onboard the actual licensed retail seller. Record legal name, license evidence, address, approved states, and signed operating/payment terms.
2. Confirm the approved live Stripe account and connected seller. The existing checkout charges the quoted selling dealer's connected account.
3. Store live keys privately and configure the signed Connect webhook. Confirm account capabilities and the correct account/mode.
4. Confirm per-VIN availability/hold, purchase price, title/condition/equipment evidence, actual taxes, delivery obligations, and accepted deposit/refund terms.
5. Enable checkout only for approved states and seller inventory. Reconcile the first customer payment and refund through canonical Stripe records. Human approval is required for actual financial actions and binding agreements.

A $250 deposit is not acquisition funding. Bank verification does not mean ACH funds are settled. Finance proceeds and purchase funds must reach the selling dealer before vehicle release.

## Acceptance bounds

Tests use explicit local provider fixtures. They verify the published payload and failure handling. They do not establish a vendor account, vendor entitlement, successful provider response, a funded loan, booked carrier, or production payment. Do not substitute these tests for provider approval.

## Hosted financing handoff

An approved selling dealer can provide an actual hosted lender application URL.

Use the operator financing endpoint with state `application_ready`, the approved lender host, provider and actual evidence reference. This state requires a URL and cannot contain approved or funded proceeds.

`application_submitted` records a supported submission separately from prequalification, approval and funding. The application host must appear in the seller's approved portal hosts.

This creates no lender application by itself. It does not establish an AutoFi contract, account entitlement, credit approval or funded proceeds.

## Owner decision recorded November 1

Ben has no agreed retail dealer yet. “Jockey” is a draft working label, not a licensed seller profile.

All provider inquiries remain drafts. Do not send, submit, sign or enable accounts from placeholder information.

## Deposit-only activation preparation

Secret and restricted account keys are classified by test/live mode. Key prefixes
establish neither actual permissions nor approval for automotive transactions.
Unknown modes, mismatched publishable keys, live keys in sandbox, missing seller
approval, missing agreements, and insecure live origins still fail closed.

`CHECKOUT_ENABLED` controls the existing $250 reservation path. Full-balance
collection now also requires **`BALANCE_CHECKOUT_ENABLED=true`**, which defaults
to false. For card deposits only, use `STRIPE_PAYMENT_METHODS=card` and leave the
balance switch false. The public configuration then reports ACH/balance checkout
disabled, hides stored balance-payment portals, and blocks new balance sessions.
This does not delete historical instructions or cancel existing provider sessions.

Explicit sandbox balance testing may opt in separately. Existing signed outcome,
refund, and ledger reconciliation continues when balance collection is disabled.
An existing pending or paid balance remains recorded. Do not use this switch to
claim funds were cancelled, reversed, refunded, or settled.

No account, seller profile, key, webhook, deployment, or runtime flag is created
or activated by these source changes. Live reservations still require the actual
licensed selling dealer, existing eligible connected account, signed terms,
verified per-VIN quote/hold/evidence, correct Connect webhook secret, and matching
live account keys. The platform account is not a substitute for the retail seller.

## Optional same-company platform deposit collection

The default remains `DEPOSIT_COLLECTION_MODE=dealer_direct`. Optional `platform`
mode is limited to the refundable $250 deposit. It requires the existing account
ID in `STRIPE_PLATFORM_ACCOUNT`, the actual collector name in
`PLATFORM_COLLECTION_LEGAL_NAME`, and actual platform agreements. The verified
collector for this project is JENNI PRO INC; Volts & VINs is its brand. This does
not make that company the licensed retail seller.

A real verified seller profile must specify `payment_account_role=platform`, the
same authorized `stripe_account`, matching `collection_legal_name`, and an actual
`collection_authorization_reference`. That authorization must cover who collects,
holds, credits, reconciles, and refunds the deposit. Existing seller identity,
license, quote, hold, vehicle evidence, and terms gates remain mandatory. Direct
mode rejects platform-role profiles for new collection. No profile is fabricated.

Orders retain role, collector name, and authorization in their seller snapshot.
Public responses expose only `deposit_collection_mode` and
`deposit_collector_legal_name` beside the actual retail seller. Authorization
references and the account pin remain private. Platform embedded checkout returns
`account:null`; its SDK and browser adapters must use the platform's own account.
Full-balance checkout remains disabled in platform mode, even if its switch is on.

Own-account webhooks omit `account`. They are accepted only for matching saved
platform orders and the configured pin, with matching signed/canonical key mode.
Connected seller events retain their original account match. Signed unrelated
JENNi events are acknowledged and ignored before provider retrieval or ledger
writes. Preserve the pin and signing configuration for historical reconciliation;
disabling new checkout does not erase outcomes. Existing late-payment refund
queue policy remains intact.

These source changes do not configure the account, create webhooks, enable
collection, establish legal authority, or prove provider approval. SDK/browser
changes and deployment require separate integration verification.

For platform mode, the existing `PLATFORM_AGREEMENTS_VERIFIED` gate also records
operator review of the processor's acceptance of this actual deposit flow. An
active account, enabled capabilities, or a software/older-commerce profile alone
does not establish automotive approval. The seller's `stripe_account` identifies
the authorized charge account; its `payment_account_role` states who owns that
collection role. The field itself is not proof of seller ownership. No additional
permission flag or implicit provider approval is created.

A session previously recorded by Volts remains known even after its current
checkout binding is cleared. Such a historical event requires reconciliation
(409); it is never silently classified as unrelated shared-account traffic.
