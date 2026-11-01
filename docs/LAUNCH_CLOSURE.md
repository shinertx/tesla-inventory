# Remaining launch work — November 1, 2026

This release completes the current code/data closure. It does not supply provider approvals, signatures, a dealer license, or missing supplier photos.

## Ownership

Codex owns quarantine, code, catalog/media projection, release integration, and deployment proof. Antigravity owns actual dealer, finance, and transport onboarding. Ben approves business identity, commercial terms, binding agreements, and any required external outreach. No new accounts or paid plans are opened by this release.

## Ready code and data

- Reported-risk VIN 7G2CEHED8SA058834 is excluded pending authentic history review. Stale requests, quote approval, deposit checkout, and balance checkout are blocked. Existing cancellation, recovery, and support remain available.
- A validated primary photo is restored for one formerly photo-less VIN. Duplicate resolutions do not count as new gallery angles. Blocked hosts are not retried or bypassed.
- Public pages can be refreshed from the published catalog without repricing or changing observation dates: `python3 -m tools.build --public-catalog inventory.json`.
- The initial duplicate catalog preload is removed. Catalog revisions get their own cache version.
- `python3 -m tools.dealer_ops integrations` reads authenticated setup requirements without changing flags.

## Required external inputs

| Outcome | Required evidence | Owner |
|---|---|---|
| Real reservations | Actual licensed seller, approved states, signed operating/payment terms, eligible live account and connected seller | Ben, licensed dealer, Antigravity |
| Automotive payment eligibility | Written approval for the actual business/entity and automotive deposit/balance flow; keys alone are insufficient | Payment provider, Antigravity |
| Financing | Dealer/provider contract, account entitlement, documented application and funding callbacks | Finance provider, Antigravity |
| Shipping | Authorized provider access, rate scope, carrier acceptance/booking authority, insurance, bill of lading and tracking | Transport provider, Antigravity |
| Vehicle quality | Authentic history/title/lien, inspection, equipment and recall evidence per payable VIN | Licensed seller |
| Remaining photos | Authorized exact-VIN dealer feeds with distinct vehicle images | Source/dealer feed owner, Antigravity |
| Company spread | Counsel-approved compensation, actual remittance/processor rail, reconciled receipts and reversals | Ben and licensed seller |

A signed draft alone does not create provider entitlement. The $250 deposit is not vehicle acquisition funding. Seller-scoped charges do not automatically collect a platform fee. Current settlement records an external receipt; it does not transfer cash.

A private nonbinding dealer pilot draft and unsent provider inquiries are prepared in the task's outputs. Required party identities, fees, signatures and provider approvals remain blank until supplied.

## Release and acceptance

Run Python and browser suites. Verify live public catalog removal and recovery photo. Deploy matching backend, inventory, media and data/exclusions.json. Preserve branded API, tracking wrapper, persistent databases, sandbox TEST setup, refund retries and disabled production payment flags. Report actual backend and catalog artifact hashes separately. A successful mock is not a live lender, carrier or customer payment.
