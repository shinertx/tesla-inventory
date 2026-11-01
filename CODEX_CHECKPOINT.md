# Active work split — November 1, 2026

Ben confirmed the dealer, financing, and transport accounts do not exist yet. Antigravity owns obtaining those providers and dealer onboarding. Codex owns the remaining site functions and release integration. Do not repeat provider discovery in the functions task.

Current functions branch: codex/customer-functions, based on main 2c5fa84, preserving Antigravity's $200 estimated-shipping buffer. Source fixes cover support-case retries/history, blocked browser storage, pending-deposit cancellation, comparison labels, unavailable favorites, fullscreen-photo recovery, and stale asynchronous order responses.

The ownership message was delivered in the existing Antigravity Tesla chat. Final acknowledgment must be checked rather than inferred from a queued message.

--- Prior released baseline follows ---

# Current handoff — November 1, 2026

This replaces the earlier stale checkpoints. Use current provider and deployment evidence before changing payment flags.

## Product and ownership

Volts & VINs controls the brand, demand generation, and customer experience. Source dealers supply vehicles. A disclosed licensed retail seller conducts each sale. These can be different entities.

Keep supplier names, source costs, links, and platform spread private. Retain required retail seller disclosures. No trade-ins. The $250 reservation is credited under its written refund terms.

Use existing eligible accounts and infrastructure. Create no new accounts. Existing JENNi connectivity does not establish automotive provider eligibility.

Codex owns release integration and the isolated VM services. Antigravity's frontend commit dcb0e7c was integrated into PR #4. Coordinate new file ownership before concurrent writes.

## Released and verified

- PR #4: https://github.com/shinertx/tesla-inventory/pull/4, merged as 8c581188a4133ce74ee96a42854b411bdf732fa6.
- Public storefront: https://voltsandvins.com/. All 197 declared sitemap pages returned 200. HTML, JavaScript, CSS, and inventory matched the released files.
- Production API: https://hank.jockeyvc.com/volts-api/api/. Backend 0aa6604; catalog efa5791; media version edfb5f199dd7. Requests enabled. Payments and ACH disabled. No Stripe credentials or synthetic seller in production.
- Production uses a separate private persistent database, exact-origin CORS, bearer-protected customer records, and authenticated operator endpoints.
- A marked browser test request was stored once, recovered after reload and private receipt entry, and cancelled. No checkout or payment was created.
- Sandbox: https://hank.jockeyvc.com/volts-sandbox/. A new actual $250 Stripe TEST payment, signed webhook, customer cancellation, and automatic full refund succeeded. The same refund remained after restart. The refund retry timer is active. Its observed runs had an empty queue; outage retry was not proven against Stripe.
- PR #4 CI: 107 Python tests and three browser suites passed. Fake-provider browser tests are separate from the actual Stripe TEST acceptance.
- Pagination now preserves its expanded count after photo failure. Temporary API failures retain private order access.

## Photo coverage

Catalog: 15,097 vehicles; 10,436 multi-photo; 3,772 single-photo; 889 without photos.

Validated recovery improved 60 VINs. Generic renders and confirmed missing image URLs were excluded. All non-photo vehicle fields, prices, savings, availability, and snapshot time were preserved.

Remaining limited galleries need accessible dealer/source feeds. A working URL does not prove every photo is current or licensed for reuse.

## Remaining launch requirements

1. Actual licensed retail seller onboarding, signed operating terms, and approved live payment account. Production currently has no approved seller.
2. Existing eligible automotive transport and financing account access. Bounded JENNi/Flow inspection did not establish that access. Cloud metadata inspection also required reauthentication.
3. Actual provider quote/application/booking responses, supported routes and states, expiry, and authenticated status updates. Current shipping, tax, and monthly payments are estimates.
4. Source/dealer feeds for remaining photos and fresh availability. No supplier hold is implied by browsing.
5. Operational ownership for pending requests, buyer/dealer notifications, documents, funding, title, and fulfillment. Status-recording endpoints do not prove those operations are automated.

No live deposit, lender-funded purchase, carrier booking, or completed vehicle delivery has been proven. Dealer outreach remains unsent.
