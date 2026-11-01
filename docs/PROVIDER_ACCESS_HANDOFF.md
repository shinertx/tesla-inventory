# Reviewed provider handoff

Antigravity prepared the first handoff. Codex checked the import command and provider references. No new account, entitlement, feed or transaction was established.

## Delivery

Use the existing Super Dispatch Pricing Insights client once its account key is authorized. A pricing recommendation is nonbinding and does not book a carrier. Carrier acceptance, pickup, delivery and bill-of-lading evidence require separate Shipper access.

Official references: https://developer.superdispatch.com/pricing-insights/docs/quickstart/ and https://developer.superdispatch.com/shipper/docs/quickstart/ .

The Shipper subscription response contains a verification_token. Callback verification must follow the provider contract. An invented generic webhook-secret variable is not a verified integration. Reference: https://developer.superdispatch.com/shipper/docs/webhooks/ .

Recorded accepted bookings remain valid after the original rate quote expires. New or changed unaccepted bookings require a current quote. Planning windows may overlap; invalid or incomplete timestamp pairs are rejected.

## Financing

The actual licensed selling dealer supplies an approved HTTPS lender application URL and permitted hostnames. Choosing financing is not an application or approval. Funding status must come from actual lender/dealer remittance evidence.

AutoFi marketplace onboarding: https://www.autofi.com/marketplaces/ . No AutoFi credential schema or lender contract was supplied here.

The reconciliation code records settled loan snapshots, separately observed cash receipts, reversals and reconciliation corrections. Operator records observe funds and do not transfer money. Calendar/loan calculator amounts never count as money received.

## Galleries and availability

An authorized direct dealer CSV/JSON export is accepted by the feed-only importer. Required CSV fields: vin,url. Optional fields: title,category.

The correct command starts with:

    python3 -m tools.import_dealer_photos --feed /private/path/authorized-feed.csv --allow-host actual-authorized-cdn.example --authorization-reference actual-agreement-reference

Default review is offline. Add --verify only after actual feed/display authorization. Existing output receipts cannot be overwritten. This importer stages a private delta; it does not publish photographs automatically.

Auto.dev documents VIN photo and listing endpoints. API access and display rights still need confirmation: https://docs.auto.dev/v2/reference/getVehiclePhotos and https://docs.auto.dev/v2/reference/getVehicleListingByVin . A working API or image URL alone does not prove display permission.

No new feed was supplied. No additional photos were recovered.

## Next owner

Ben and the actual retail dealer supply the seller agreement, approved finance portal/funding source, transport access and authorized VIN/photo feed. Codex connects and verifies them. Inquiries remain drafts; no new accounts or paid plans are authorized.
