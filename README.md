# Tesla Marketplace

Carvana-style vehicle discovery with an own-dealership transaction service.

**Current business state: licensing pending. Paid checkout is closed.**

## Run locally

Use Python 3.12 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m tools.build
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for shopping and free verification requests.

Environment settings come from the process environment. `.env.example` documents them; it is not loaded automatically.

Set `ADMIN_TOKEN` to a generated secret of at least 32 characters before using operator endpoints.

Do not place credentials in browser code, Git, screenshots, or command arguments.

## Build and collect

`data/source_snapshot.json` preserves source attribution. Its legacy timestamps are import times, not live-source verification.

`data/exclusions.json` suppresses known title/condition risk flags independently of source refreshes.

```sh
python3 -m tools.build
python3 -m tools.collect --source autolist --model 'Model Y' --year 2024 --pages 1
python3 -m tools.build
```

Collectors make real provider requests. Confirm source permission before using them. No bulk collectors were run during the repair.

Collection is bounded and makes no national completeness claim. Failed pages preserve the prior snapshot. Invalid VINs enter quarantine.

Fresh observations update price and mileage. Publication expires candidates after seven days. Seller holds still require independent confirmation.

The builder creates the root page, category pages, sitemap, and public inventory. It makes no network requests.

## Transaction behavior

1. A free request creates a durable private order and an operator notification entry.
2. An authenticated operator verifies the vehicle and approves a complete quote.
3. Customer acceptance binds checkout to that quote version and its terms.
4. A single VIN hold prevents competing reservations.
5. Signed Stripe events and retrieved session data confirm the deposit.
6. Evidence gates control contracting, funding, acquisition, transport, delivery, and closing.
7. Cancellation, refunds, disputes, and customer cases enter explicit queues.

Payment return URLs never establish payment. A deposit does not establish full purchase funding.

See [API and operations](docs/OPERATIONS.md) and the [business operating model](docs/BUSINESS_OPERATING_MODEL.md).

## Verify

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q tests
python3 tests/browser_smoke.py
node --check web/app.js
```

The browser smoke test uses a temporary database and a pending-license configuration. It does not charge cards or send messages.

## Deployment

GitHub Pages supports the static shopping experience. It cannot run this transaction API.

Host `app.main:app` with HTTPS and a persistent private disk for SQLite. Use one application instance until the database moves to a shared transactional service.

Serve the public site and API through the same origin. Dynamic responses remove reserved vehicles from the catalog.

Never serve the repository directory with a general file server in production. The API exposes only explicit public assets.

Before payments, configure the real seller, approved destination states, Stripe credentials, webhook, operator coverage, backups, privacy retention, and reviewed terms.

Test one real merchant-account sandbox transaction and refund before enabling live payments.

## Source ownership

This repository now contains the frontend, builder, source normalization, transaction service, tests, and operating documents.

The earlier personal scratch scripts are obsolete. Use this repository's build commands to avoid restoring unsafe generated claims.
