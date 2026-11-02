# Volts & VINs

A branded Tesla buying experience over dealer-owned inventory. Volts & VINs controls the storefront and coordinates checkout and fulfillment.
The business captures the agreed transaction spread. Source dealers and the disclosed licensed retail seller can be different businesses.

## Live status

Snapshot: November 2, 2026.

| Component | Status |
| --- | --- |
| [Customer storefront](https://voltsandvins.com/) | Live: browsing, galleries, comparison, pricing previews, and purchase requests |
| [Production configuration](https://api.voltsandvins.com/api/config) | Requests enabled; deposits and balance checkout disabled |
| [Existing TEST sandbox](https://hank.jockeyvc.com/volts-sandbox/) | Synthetic inventory and Stripe TEST only |
| Application release | `9f83a8be2a0485b0b55a9fd79e29597658a0173a` verified in both API services |
| Live payment collection | Pending actual seller agreements, supported states, and verified Stripe capture/release access |
| Financing and carrier quotes | Provider access is not connected; calculators show clearly labeled estimates |

Documentation commits can advance `main` without changing the deployed application. Compare runtime changes before redeploying the API.
GitHub Pages publishes a customer-only artifact after successful main checks. It does not publish this README, agent instructions, or operational tools.

The published catalog contains 15,098 vehicles and 206,922 gallery images after excluding one reviewed dealer advertisement.
There are 10,436 multi-photo listings, 3,776 single-photo listings, and 886 without photos. Every external image URL has not been tested.

## Verified buying flow

1. Browse stock-ID vehicle pages and inspect their photographs.
2. Enter the delivery ZIP and compare vehicle, delivery, tax, and registration estimates.
3. Submit a free purchase request with contact details and payment preference.
4. Receive an itemized quote from an actual approved licensed seller.
5. Accept its terms and authorize a $250 card hold when checkout is enabled.
6. Choose the configured payment path or download the accepted buyer's order.
7. Explicit capture collects the deposit; only captured funds receive purchase credit.
8. Reconciled funding and verified evidence gate fulfillment, delivery, title, and settlement.

An uncaptured authorization is not revenue, acquisition funding, or a paid deposit. Payment return URLs never establish payment.
The deposit is not the platform's earned spread. Collection follows the order's agreed seller and collector roles.

Actual Stripe TEST authorization, capture, and full refund passed. Real signed Checkout and refund webhooks were recorded.
The deployed cleanup also passed against that refunded order. Uncaptured release has local coverage but no separate provider walkthrough.
Live collection remains disabled. A pending partner or placeholder name is not a verified dealership.

## Local development

Use Python 3.12. Run these commands from the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. A fresh public clone supports browsing.
Actual request resolution needs the private VIN-backed transaction catalog. Do not reconstruct transactional identities from guessed VINs.
Set `INVENTORY_JSON` to that catalog's absolute path before starting the API.

Environment variables come from the process environment. `.env.example` is documentation; it is not loaded automatically.
Use a private generated `ADMIN_TOKEN` for operator endpoints. Keep secrets outside Git, browser code, logs, and screenshots.

## Catalog and photo updates

- `web/` contains the frontend source. The builder generates root and category pages.
- `inventory.json` and stock-keyed `media/` files contain the customer projection.
- `.data/transaction_inventory.json` preserves private VIN identities and gallery sources.
- `.data/source_snapshot.json` contains private supplier observations when available.
- `data/exclusions.json` records known title or condition exclusions.
- `tools/media.py` excludes reviewed non-vehicle imagery and generic placeholders.

Refresh generated pages without collecting or repricing:

```sh
.venv/bin/python -c 'import json; from tools.build import render_public_pages; render_public_pages(json.load(open("inventory.json")))'
```

Rebuild only with a valid private source snapshot and transaction baseline. Do not use an empty source to replace published inventory.
Collectors make real provider requests. Respect source permissions and stop blocked or rate-limited hosts.
Known salvage, rebuilt, lemon, flood, and structural-risk evidence prevents publication. Unknown title history is not clean-title proof.

The scheduled refresh was already failing before this release. Its limited discovery coverage cannot refresh the complete catalog.
It also lacks a private baseline on hosted runners. Keep coverage and privacy guards until persistent sourcing is configured.

Stock IDs reduce direct public VIN exposure. Historical Git data and vehicle photographs can still identify a vehicle externally.

## Pricing

Vehicle prices remain separate from delivery, tax, and registration estimates. Accepted request prices cannot silently increase.
Delivery budgets include route distance, vehicle size, and a contingency. They are not carrier or Carvana quotes.
Texas previews use 6.25% motor-vehicle tax and a $350 registration allowance. Other unverified destinations need actual vehicle-tax quotes.
Monthly payments are illustrations, not lender offers. A declared down payment does not move money.

See [pricing policy](docs/PRICING_COMMITMENT.md) for assumptions and reconciliation rules.

## Checks

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/manual_hold_browser_smoke.py
.venv/bin/python -m unittest discover -s ops/purchase_release -p test_purchase_release.py -q
node --check web/app.js
```

The application suite passed 679 checks at the verified release. Ten browser suites run in GitHub Actions.
Seventeen real desktop/mobile checks passed, followed by visual confirmation of the corrected gallery.
Local fake-provider tests and actual Stripe TEST evidence are different checks. Neither establishes live customer payment readiness.

## Deployment and handoff

The storefront uses GitHub Pages. The API uses the existing persistent JENNi/Jockey server with separate production and TEST databases.
Production CORS permits the customer origin. Tokens stay in explicit authorization headers; account cookies are not shared.
Use one SQLite-backed API instance until a shared transactional database is introduced.

Never publish the repository root. Export only customer files:

```sh
.venv/bin/python -m tools.public_site --output site-dist
```

Use an empty output directory. The exporter excludes private data, operator documents, source code, and full VINs.
Keep private inventory mode `0600`. Preserve order history, bound payment accounts, existing workers, and rollback releases.

The installed production wrapper enforces inactive payment collection. A single environment flag cannot activate checkout.
Activation requires actual seller and collection evidence, verified live permissions, and a reviewed activation release.
Existing JENNi/Jockey infrastructure and its Stripe account are used. No new account is needed for this architecture.

Start with [AGENTS.md](AGENTS.md). Follow the [release tools](ops/purchase_release/README.md) for packaging, verification, and rollback.
See [operations](docs/OPERATIONS.md), [deposit activation requirements](docs/JENNI_DEPOSIT_LAUNCH.md), and the [business model](docs/BUSINESS_OPERATING_MODEL.md).
