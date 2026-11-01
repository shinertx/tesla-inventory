# Clear vehicle price release in progress — November 1, 2026

Codex owns price-protection API/store migration, web pricing labels, build copy and generated pages. Antigravity acknowledged this split in its existing Tesla conversation. New requests save the vehicle price and benchmark; stale browser prices fail409; quotes cannot raise the saved vehicle price. Legacy requests retain their explicit quote behavior without fabricated historical guarantees. Catalog/prices/media remain unchanged.

An existing LIVE JENNi/Jockey Stripe binding was located, but provider identity/capabilities and the Flow account label are not verified. Existing cloud login requires renewal; the known VM identity has no access. No production credential was copied or enabled. Deposits remain disabled without an actual licensed seller and eligible payment arrangement. Vendor inquiries remain drafts.

Antigravity confirmed no new financing, shipping or photo-feed entitlement. Provider field names in planning notes are examples until official account documentation confirms them. AutoFi should use an actual approved hosted dealer application first when available; do not invent API parameters.

--- Previous release ---

# Antigravity Checkpoint — Static `/v/{VIN}.html` Top 200 Vehicle Pages (November 1, 2026)

- **Ownership Split Acknowledged:** Antigravity owned only `tools/build.py`, generated `/v/*.html` (`200` pages), `sitemap.xml`, `llms.txt` / `llms-full.txt`, static category links (`deals/*.html`, `models/*.html`, `states/*.html`, `years/*.html`), and `tests/test_public_pages.py`.
- **Untouched Codex Files:** `app/main.py`, `app/models.py`, `app/providers.py`, `web/app.js`, `web/index.html`, `web/styles.css`, and `inventory.json` were left 100% untouched.
- **Draft & Compliance Invariants Preserved:** Jockey remains an unverified draft placeholder only; all Texacars, AutoFi, and Super Dispatch inquiries remain drafts; no live payment enablement, new accounts, or vendor sends were made.
- **Static VDP Implementation (`tools/build.py` + `v/*.html`):**
  - Renders top `200` peer-benchmarked price-find Teslas (`savings_amount >= 500`, `reference_sample >= 5`) to `/v/{VIN}.html`.
  - Sets `<body data-preset="model:{model}" data-initial-vin="{VIN}">` on every `/v/{VIN}.html` page so Codex's `web/app.js` bootstrap opens the exact VIN drawer automatically.
  - Embeds canonical URL (`https://voltsandvins.com/v/{VIN}.html`), `Car` + `BreadcrumbList` + `FAQPage` JSON-LD, VIN-decoded build factory (`Built in {factory}` labeled distinctly from `Vehicle location`), peer benchmark savings, and required disclosures without leaking supplier names or listing links.
  - Updates `sitemap.xml` (`397` total URLs = `1` home + `196` category + `200` `/v/{VIN}.html` pages), category featured links, and `llms.txt` / `llms-full.txt`.
- **Verification Evidence:**
  - `ENABLE_GITHUB_PAGES_CNAME=true python3 tools/build.py --public-catalog inventory.json` -> `{"published": 15098, "excluded": {}, "category_pages": 196, "vehicle_pages": 200, "sitemap_urls": 397}`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests` -> `190 passed, 2 warnings` (including `test_top_price_find_vehicle_pages_render_with_initial_vin`).

---

# Active provider launch engineering — November 1, 2026

Ben resumed launch work, then confirmed no dealer has agreed yet. Use Jockey only as an unverified draft label. All Texacars, AutoFi and Super Dispatch inquiries must remain DRAFTS. No account creation, paid plans, vendor sends or real-payment enablement is authorized from placeholder data.

Ownership accepted in the native Tesla chat: Antigravity owns tools/build.py, static /v pages, sitemap and their tests. Codex owns app/main.py, app/models.py, app/providers.py and web/app.js for provider integrity, fresh private-order shipping estimates and hosted lender application states. Set body data-initial-vin on static VDPs; root has added support. Coordinate the final builder/pages refresh before publishing matching asset hashes.

Root candidate codex/provider-launch-integrity removes fake legacy APR/booking/evidence; preserves the verified Super Dispatch client; adds sanitized, route-matched, expiring customer estimates; adds honest application_ready/application_submitted states and approved lender hosts. Production credentials remain absent and gates remain off.

Latest evidence: existing Stripe public business identity is JENNi sandbox, using TEST access. Cache follow-up recovered zero new photos;886 have none and3,776 have one. Missing photo completion requires authorized source/dealer feeds. Owner inputs are prepared in the current Codex task outputs/launch-inputs-for-ben.md.

--- Prior handoff ---

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
