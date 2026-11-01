# Financing, delivery and photo readiness

## Funding and release

Financed orders cannot advance to dealer-funded or released status unless recorded settled proceeds cover the current quote balance. The $250 credit counts only after a recorded deposit. Fully settled full-balance ACH remains an existing alternative. Conditional approval and calculator down payments are not settled money.

The same coverage check applies to dispatch and delivered carrier markers. Existing cash/dealer-receipt behavior is unchanged.

Combined loan and additional cash funding uses an append-only reconciliation ledger. Separately settled cash receipts reduce the balance; observed returns use linked reversals. Lender funding uses cumulative net snapshots, with explicit linked corrections. Actual remittance references are reserved across funding types and orders. Current quote and seller identity determine which funds apply. Earlier-context funds remain visible for reconciliation. Calculator down payments and unverified approvals never count as received money. These records do not initiate transfers or refunds. The actual seller and provider still supply settlement evidence.

## Customer privacy

Customer financing and delivery responses use explicit field allowlists. Private funding references, carrier costs, source quote/acceptance references and operator notes stay private. The customer sees the delivery amount from the accepted retail quote.

## Photo feed

The feed-only importer accepts dealer CSV or VIN-keyed JSON. It defaults offline and never edits the catalog. Explicit verification checks actual raster image bytes and stages private review receipts. It does not scrape blocked pages or establish display rights. See DEALER_GALLERY_IMPORT.md.

No authorized new feed was available. Recovery count is zero. The existing catalog still has 886 zero-photo and 3,776 single-photo vehicles. Existing galleries and prices remain unchanged.

## External access still required

Real financing needs the licensed seller's approved lender application/contract and funding evidence. Real delivery pricing needs provider entitlement; carrier booking separately needs booking access, carrier acceptance and tracking. Full galleries need an authorized VIN-bound feed. Provider inquiries remain drafts; no account was opened or contacted during this release.
