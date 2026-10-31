# Active objective

Build a truthful Carvana-style Tesla storefront and a controlled own-dealership transaction service.

## Decision

User selected their own licensed dealership as seller. Legal identity and license evidence remain pending.

## Baseline

Commit 5020dcb. Static site and data reconcile with the public site.
Inspection readings and credentials are hardcoded. Payments trust URL parameters.
Legacy Python sources live beside this repository and are not tracked here.

## Work

Replace unsafe templates with maintained source. Add durable requests, quotes, verified deposits, inventory holds, and fulfillment controls.
Add an operating model covering acquisition, funding, title, inspections, transport, returns, warranty, privacy, and unit economics.
Keep paid checkout closed without real configured dealership evidence.

## Verification

Run bounded local regression tests and independent browser checks. Do not run bulk collectors or charge cards.

## Next

Implement canonical source and regenerate static output.

## Implementation complete

Canonical frontend, builder, acquisition normalization, API, tests, CI, and operating documents are tracked in this repository.

The legacy compiler entry point now forwards to the maintained builder. Its original is backed up in this task's work directory.

Published local catalog: 14,912 candidates. Persistent exclusions suppress 176 risk-flagged records.

## Verified

- 37 regression tests passed.
- Independent desktop/mobile browser flows passed with zero JavaScript exceptions.
- All 68 generated HTML files passed forbidden-claim checks.
- Source exclusions and unknown equipment/title states were reconciled across the published catalog.
- JavaScript syntax, Python parsing, and whitespace checks passed.

## External work remaining

License acquisition/amendment, actual dealership identity, merchant account, persistent API hosting, monitored notifications, and real provider sandbox proof remain pending.

No real payments, external messages, or bulk collection occurred.

## Next

Publish the repair branch for review. Confirm remote CI when available. Do not call the transaction service production-ready.
