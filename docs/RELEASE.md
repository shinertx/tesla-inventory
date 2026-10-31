# Release status

## Built

- Maintained frontend and repeatable static build.
- Truthful vehicle details and pricing across category and detail views.
- Strict VIN identity, source observations, persistent exclusions, and snapshot expiry.
- Durable private purchase requests, versioned quotes, accepted terms, and VIN holds.
- Signed Stripe webhook verification, canonical payment lookup, duplicate protection, and refund controls.
- Evidence-gated purchase lifecycle and customer cases.
- Guest access receipts and authenticated operator recovery.
- Operator work queue, event history, outbox, and inactive-request anonymization.
- Own-dealership operating model and launch acceptance criteria.

## Verification boundaries

API regression tests use isolated databases and payment-provider fixtures.

The real Stripe SDK signature verifier is tested with locally signed webhook payloads.

Browser tests use temporary pending-license services. They exercise real local HTTP requests and browser interaction.

No card was charged. No live merchant account, lender, carrier, title provider, or dealership license was verified.

No customer email or external message was sent.

## Production prerequisites

- Complete the actual dealership acquisition/licensing process.
- Confirm entity, premises, authority, bond, insurance, and supported destinations.
- Configure persistent HTTPS hosting for the API.
- Establish merchant account and webhook; prove merchant-account sandbox payment and refund behavior.
- Supply verified vehicle, title, inspection, hold, pricing, and customer-term evidence.
- Assign operator coverage and connect monitored notification delivery.
- Establish restricted document storage, backups, restore testing, and retention scheduling.
- Complete a controlled purchase and delivery before claiming end-to-end readiness.

GitHub Pages can publish the safe discovery storefront. It cannot operate the Python transaction service.

## Rollback

Retain the repair branch and its verified artifacts. Revert individual functional changes if needed.

Do not restore the earlier fabricated inspection readings, hardcoded credentials, or URL-driven payment state.

If payments malfunction, disable `CHECKOUT_ENABLED`, retain the order database, and resolve recorded payments before releasing holds.

If inventory evidence is unreliable, suppress affected VINs through `data/exclusions.json` and rebuild.
