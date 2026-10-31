# Transaction operations

## Configuration

Copy `.env.example` to private deployment configuration. Populate secrets through the host's secret manager.

The service does not automatically load `.env` files.

`DEALER_VERIFIED=true` requires documented licensing confirmation for the actual entity and premises.

`DEALER_LICENSE_EVIDENCE` identifies the retained verification. `SUPPORTED_STATES` lists approved destination states.

`CHECKOUT_ENABLED=true` also requires Stripe credentials and a webhook secret. Live keys require an HTTPS public origin.

The code checks configuration and evidence references. It cannot independently authenticate a license or inspect a vehicle.

## Operator access

The API uses `Authorization: Bearer <ADMIN_TOKEN>`. Never put the token in a URL.

```sh
python3 -m tools.dealer_ops orders
python3 -m tools.dealer_ops outbox
python3 -m tools.dealer_ops quote --id ORDER_ID --file private-quote.json
python3 -m tools.dealer_ops transition --id ORDER_ID --file private-transition.json
python3 -m tools.dealer_ops refund --id ORDER_ID
python3 -m tools.dealer_ops ack --id OUTBOX_EVENT_ID
python3 -m tools.dealer_ops privacy-purge
```

Store customer quote files outside the public repository.

## Quote fields

All money uses integer cents. Model definitions in `app/models.py` are the API contract.

Required cost inputs:

- Acquisition and customer vehicle price.
- Sales tax and title/registration.
- Documentation and customer delivery charges.
- Actual carrier cost, inspection/reconditioning, marketing, reserves, and other costs.

Required evidence:

- Source hold reference and expiry.
- Title history and lien disposition.
- Inspection, equipment, and recall disposition.
- Tax and carrier quotes.
- Applicable Buyers Guide or documented exemption basis.
- Accessible warranty, return, and deposit terms.

Customer-visible terms require HTTPS URLs. Do not use internal file paths for those links.

The quote cannot outlive the source hold. Checkout needs at least 32 minutes of remaining validity.

The default minimum contribution is $1,000. This is provisional and requires owner approval.

Taxes and registration do not count as revenue. No assumed lender reserve is included.

## Customer access

`POST /api/requests` requires a unique `Idempotency-Key` and explicit request consent.

The response returns the order ID and a private access token. The browser retains only that pair in sessionStorage.

Customer name, email, state, and ZIP are stored server-side. They are not stored in localStorage or payment redirect parameters.

`GET /api/orders/{id}` requires the customer bearer token.

`POST /api/orders/{id}/checkout` requires the current quote version and explicit terms acceptance.

This release uses guest access with a downloadable private receipt. Customers can restore access with the request ID and access code. Lost receipts require an operator-verified recovery process; never reset access from an unauthenticated email claim.

## Payment verification

Register `/api/stripe/webhook` with the dealer's own Stripe account.

Subscribe to:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`
- `checkout.session.expired`
- `refund.created`
- `refund.updated`
- `charge.dispute.created`

The handler verifies the raw-body signature and retrieves the checkout session.

It matches order, quote version, amount, currency, payment status, and live/test mode.

Event IDs prevent duplicate handling. Checkout and refund calls use stable provider idempotency keys.

Late payments enter `refund_pending`. They cannot displace another customer's VIN hold.

Refund completion requires provider success. Unexpected refunds or disputes freeze fulfillment in `payment_review`.

## Order states

`requested → quoted → checkout_pending → deposit_paid → contracted → funded → purchased → in_transit → delivered → completed`

Exception states: `quote_expired`, `cancelled`, `refund_pending`, `refunded`, `payment_review`.

Each forward transition requires named evidence. See `TRANSITIONS` in `app/main.py`.

Before contracting, funding, or purchasing, the source-dealer hold must remain valid.

Renew a paid order's source hold with authenticated `POST /api/admin/orders/{id}/hold` and a new evidence reference.

A paid hold does not automatically expire into resale. An operator must resolve payment and ownership first.

Reserved or purchased vehicles disappear from the API-served catalog. New requests for held VINs are rejected.

## Customer cases

Customers can open return, warranty, transport-damage, title-delay, or general cases.

`GET /api/admin/cases` returns unresolved cases. Each has a review deadline.

`POST /api/admin/cases/{case_id}` requires an owner and resolution evidence.

Opening a return case does not promise eligibility or automatically refund a vehicle purchase.

Vehicle purchase balances are outside the card-deposit subsystem. Reconcile full-price refunds through the actual settlement rails and signed terms.

## Notifications and exceptions

The outbox is durable. It is not an email-delivery service.

Assign a human owner before accepting public requests. Connect monitored delivery before claiming notifications.

Acknowledge events only after handling them or delivering them to the responsible operator.

Review overdue `action_due_at` orders, refund exceptions, unresolved cases, and provider failures each business day.

## Retention and recovery

Run the authenticated privacy purge on a daily operations schedule. It anonymizes inactive unpaid leads after the configured retention interval.

It preserves paid transaction records. Establish the applicable legal retention schedule before production.

Handle explicit privacy requests from the outbox. Resolve legal-hold and transaction obligations before deletion.

Back up SQLite using its backup API or an application-consistent snapshot. Encrypt backups and test restoration.

Store all retained evidence in restricted storage with stable references. Do not upload identity or financial documents into the public repository.

## Production boundaries

- One instance with a persistent private volume; no ephemeral serverless SQLite.
- HTTPS, a trusted reverse proxy, request-size limits, and rate-limit policy.
- Managed operator identity and role separation before broad staff access.
- Real provider sandbox verification and webhook retry testing.
- Notifications, account recovery, retention scheduling, backups, and restore drills.
- Dealership authority, merchant acceptance, financing arrangements, and written customer terms.

These integrations require actual accounts and business decisions. Passing mocked regression tests does not establish production operation.
