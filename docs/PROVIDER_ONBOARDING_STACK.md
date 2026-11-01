# Provider connections and launch inputs

Volts & VINs uses a branded customer experience with a disclosed licensed retail seller.

The working seller label is **Jockey**. It is an unverified draft placeholder. No dealer has agreed yet.

All vendor inquiries remain drafts under Ben's November 1 instruction. No new accounts, paid plans, or vendor sends are authorized.

| Part | Current code | Needed to activate |
| --- | --- | --- |
| $250 reservation | Seller-scoped Stripe Checkout, signed webhook verification, cancellation and refunds | Real licensed seller, signed seller/platform terms, eligible live Stripe/Connect access, supported states, actual vehicle quote and hold |
| Financing | Payment preference, recorded lender status, approved hosted application links | Licensed seller's approved lending relationship, official application URL or API contract, customer consent, authenticated funding evidence |
| Delivery estimate | Verified Super Dispatch Pricing Insights request and fresh customer-price projection | Provider-issued Pricing Insights key and account entitlement; confirmed route and vehicle operability |
| Carrier booking | Recorded accepted-carrier and delivery evidence | Approved Shipper API credentials, booking/acceptance contract, carrier insurance, bill of lading and tracking integration |
| Photos and inventory | Public galleries and private source catalog | Authorized dealer/source feeds with full galleries, stable VIN mapping and availability updates |
| Tax, title and documents | Itemized seller quote and secure document links | Selling dealer's actual tax/title calculations, documents, signing and filing process |
| Platform income | Private modeled spread and recorded settlement receipts | Executed compensation/settlement agreement and verified remittance or approved processor fee collection |

## Existing payment account

The inspected Stripe TEST account returns the name **JENNi sandbox**. It is not an approved production automotive account.

Do not relabel a synthetic seller as Jockey or enable checkout from placeholder information.

## Integration boundaries

Super Dispatch Pricing Insights recommends a price. It does not book a carrier or guarantee a delivery window.

The verified client remains available. Legacy unverified provider adapters fail closed before any network request.

The legacy instant-quote helper returns estimates only. It cannot provide verification evidence or approve a purchase quote.

Financing requires the provider's actual contract and approved access. No default APR, lender approval, delivery window or referral income establishes live service.

A bank link is not settled purchase funding. A ledger entry is not a collected platform payout.

## Official onboarding sources

- [AutoFi marketplace partnerships](https://www.autofi.com/marketplaces/)
- [Super Dispatch Pricing Insights authentication](https://developer.superdispatch.com/pricing-insights/docs/authentication/)
- [Super Dispatch Shipper API quickstart](https://developer.superdispatch.com/shipper/docs/quickstart/)
- [Stripe Connect direct charges](https://docs.stripe.com/connect/direct-charges)

See PROVIDER_SETUP.md for the supported integration contract and activation checks.
