# Existing JENNi account: Volts & VINs deposits

Prepared integration; customer deposits remain disabled.

Ben confirmed that Volts & VINs is a brand of the same company. The existing live Stripe dashboard identifies JENNI PRO INC. Its account ends Ey1s3E. Payments and payouts are active, with no active account-status tasks. These facts do not establish approval for vehicle-deposit collection. Its current business profile describes software.

## Collection model

The optional `platform` collection mode charges the existing company account. It creates no new Stripe account. Each order still requires an actual licensed retail seller and its written collection authorization. The seller profile records the authorized collector account and legal name separately from the retail seller. The customer sees both roles before paying.

Checkout uses Volts & VINs session branding. It does not rename JENNi or change shared company branding. The deposit is exactly $250 USD. Platform mode cannot collect the vehicle balance, even if the balance switch is enabled. The deposit is credited under the accepted reservation terms; it is not platform revenue or acquisition funding.

The existing dealer-direct mode remains available. Historical connected-account and platform payments retain their bound account scope for retrieval, expiry, refunds and signed outcomes. Unrelated signed JENNi payment events are ignored without provider retrieval or ledger writes. Known historical session IDs that lost their current binding require reconciliation.

## Disabled preparation values

```dotenv
DEPOSIT_COLLECTION_MODE=platform
STRIPE_PLATFORM_ACCOUNT=acct_1RVzLDRt4eEy1s3E
PLATFORM_COLLECTION_LEGAL_NAME=JENNI PRO INC
PUBLIC_ORIGIN=https://voltsandvins.com
STRIPE_PAYMENT_METHODS=card
CHECKOUT_ENABLED=false
BALANCE_CHECKOUT_ENABLED=false
PLATFORM_AGREEMENTS_VERIFIED=false
AUTO_REFUND_ENABLED=true
```

Keep credentials in protected runtime storage. Do not commit them or paste them into chat. The existing production wrapper currently rejects an installed server key. Stage credentials separately until its reviewed installation change is ready. Do not overwrite other JENNi keys, webhooks, profile, or services.

The dedicated restricted-key proposal grants Checkout Sessions write, Charges and Refunds write, Payment Intents read, and Accounts read. Other and Connect permissions remain none. Restrict its use to the existing reserved server IP, `35.237.153.98`. Stripe key permissions cover the account; they do not enforce a $250 or brand-only limit. Application guards enforce the allowed order and amount.

The proposed own-account snapshot webhook is `https://api.voltsandvins.com/api/stripe/webhook`. Subscribe only to:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`
- `checkout.session.async_payment_failed`
- `checkout.session.expired`
- `refund.created`
- `refund.updated`
- `charge.dispute.created`

The dashboard offers the existing `2025-05-28.basil` snapshot version. Canonical Checkout retrieval uses the application's pinned `2026-03-25.dahlia` version. Event handling uses session IDs and fetches canonical payment data. Do not change the shared account's default API version.

These event types can include unrelated JENNi payment data. Creating the key and registering this new destination require specific approval. Neither form has been submitted during preparation.

## Required before activation

1. Verify the actual Texas seller's legal name, GDN/license evidence, licensed address, and supported states.
2. Obtain signed terms authorizing JENNI PRO INC to collect, refund and credit the reservation deposit.
3. Disclose the actual vehicle-reservation activity to Stripe and confirm this collection arrangement is supported. Set the existing agreement gate only after the actual agreements and provider acceptance are verified.
4. Install the authorized live key, matching publishable key, and dedicated signing secret after reviewing the runtime wrapper.
5. Approve a real VIN, source hold, itemized quote, vehicle evidence, delivery charge, and public purchase/reservation terms.
6. Verify the first actual deposit, signed outcome, cancellation/refund, and saved state. A human completes actual financial actions.

Automated financing and shipping APIs are separate integrations. Their absence does not replace the required quote, seller authorization, or refund terms.

References: [Stripe keys](https://docs.stripe.com/keys), [webhooks](https://docs.stripe.com/webhooks), [session branding](https://docs.stripe.com/api/checkout/sessions/create?api-version=2026-03-25.dahlia), and [disclosure restrictions](https://stripe.com/legal/restricted-businesses).
