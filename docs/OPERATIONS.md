# Dealer-network operations

## Ownership and deployment

The platform owns demand generation and transaction coordination. The fulfilling dealer owns the car and sells directly to the customer.

Host the API on persistent HTTPS infrastructure. GitHub Pages supports static shopping only.

Use one SQLite-backed application instance until migrating to a shared transactional database.

## Configuration

Set `ADMIN_TOKEN` to a private secret of at least 32 characters.

`PLATFORM_AGREEMENTS_VERIFIED=true` records approval of the platform transaction structure and agreements.

It does not assert that the platform owns a dealership or eliminate any applicable legal requirements.

Set approved `SUPPORTED_STATES`, Stripe platform credentials, and a connected-account webhook secret.

`CHECKOUT_ENABLED` stays false until actual partner/account sandbox verification is complete.

Do not place secrets or supplier snapshots in the public repository.

## Private supplier data

`SOURCING_JSON` defaults to `.data/source_snapshot.json`.

The builder and collectors read/write private supplier inputs there. The public catalog contains an explicit customer-field allowlist.

`GET /api/admin/sourcing` requires operator authentication. It exposes supplier names, listing links, and raw prices only to operators.

Previously committed supplier data remains in Git history. This change removes it from the current tree and public-serving paths; it cannot revoke historical exposure.

VINs and approved photographs can still identify a vehicle externally. Confirm media permissions and use approved branded media when available.

## Enroll dealers

Authenticated `PUT /api/admin/dealers/{id}` stores:

- Dealer ID, legal name, license number, address, and supported states.
- Connected Stripe account.
- License evidence and signed agreement reference.
- Operator verification status.

Only an approved dealer can fulfill a quote. Checkout verifies the connected account can accept charges.

Order records snapshot the seller and payment account. Account changes cannot silently redirect an existing checkout or refund.

## Quotes

All monetary values use integer cents. `app/models.py` is the schema contract.

Set the fulfilling dealer, agreed dealer vehicle net, customer vehicle price, taxes, title, documentation, and delivery charges.

Record platform-borne demand, service, payment, reserve, and other costs.

Provide supplier commitment, spread agreement, hold expiry, title/lien, inspection, equipment, recall, tax, and carrier evidence.

Customer terms need accessible HTTPS documents. The quote exposes the legal seller, total price, and terms before acceptance.

Quotes cannot outlive supplier holds. Checkout requires at least 32 minutes remaining.

## Deposits and money ownership

The adapter creates card deposits on the fulfilling dealer's connected account using `stripe_account`.

It takes no platform application fee from the refundable $250 deposit.

Register the webhook to receive connected-account events. The signed event's account must match the stored order before payment lookup.

Subscribe to checkout completion/expiry, refund creation/update, and dispute creation events.

Verify amount, currency, quote version, order, account, and live/test mode against the retrieved session.

Refunds use the original dealer account, even if its onboarding status later changes.

Late payments and revoked dealer commitments enter refund review. Payment redirects never establish payment.

The dealer or its provider receives the balance. `dealer_funded` requires that evidence; it does not represent platform acquisition funding.

## Fulfillment and settlement

`requested → quoted → checkout_pending → deposit_paid → dealer_confirmed → dealer_funded → in_transit → delivered → settlement_pending → completed`

Transitions require evidence named in `TRANSITIONS`. No vehicle ownership transfers to the platform.

Dealer commitments must remain valid through dealer funding and dispatch. Renew with `/api/admin/orders/{id}/hold`.

Completion requires `/api/admin/orders/{id}/settle`, a dealer statement, receipt, actual platform costs, and reconciliation to the agreed spread.

Settlement is an operator-confirmed external receipt. The endpoint does not move cash.

Record fee clawbacks through `/api/admin/orders/{id}/settlement-reversal`. Duplicate references do not duplicate deductions.

`GET /api/admin/economics` reports collected spread, reversals, and actual contribution by demand channel.

Vehicle GMV, deposits, and expected price gaps are excluded from collected platform revenue.

## Operator commands

Use environment credentials, never command-line secrets.

```sh
python3 -m tools.dealer_ops orders
python3 -m tools.dealer_ops sourcing
python3 -m tools.dealer_ops dealers
python3 -m tools.dealer_ops economics
python3 -m tools.dealer_ops quote --id ORDER_ID --file private-quote.json
python3 -m tools.dealer_ops transition --id ORDER_ID --file private-transition.json
python3 -m tools.dealer_ops settle --id ORDER_ID --file private-settlement.json
python3 -m tools.dealer_ops settlement-reversal --id ORDER_ID --file private-reversal.json
python3 -m tools.dealer_ops refund --id ORDER_ID
python3 -m tools.dealer_ops outbox
```

## Exceptions, privacy, and legacy data

Legacy resale quotes/orders enter `model_review`. They are not reinterpreted as dealer-owned fulfillment or silently refunded through a different account.

Retain their payment and original quote evidence for manual reconciliation.

Customer cases, private access receipts, verified operator recovery, and the notification outbox remain available.

Assign operators and connect monitored notification delivery before accepting public demand.

Keep evidence in restricted storage. Schedule inactive-lead anonymization and apply a reviewed paid-transaction retention policy.

Use encrypted backups and test restores. Confirm dealer support, returns, title, tax, insurance, and settlement responsibilities before enabling payments.

## Arbitrage and customer media

Use `python3 -m tools.dealer_ops arbitrage` for private ranked pricing proposals. There is no fixed $1,500 retail markup or spread cap.

`BUYER_SAVINGS_CENTS` sets the provisional buffer below comparable asking-price medians. Final customer quotes remain independently approved against the dealer commitment and actual costs.

Customer cards omit operational availability warnings. The backend still requires an actual dealer hold before charging a reservation.

Real-photo vehicles lead the showroom. Generic default image paths do not count as vehicle photography.

`GET /api/vehicles/{vin}/photos` serves cached VIN-bound media. Carvana Flight data and JSON-LD arrays preserve galleries and condition photographs.

CarGurus detail requests were blocked during verification. Its known primary photo remains available; the code does not fabricate extra angles or repeatedly retry blocked detail pages.

The original ledger's photo count included 794 generic placeholder paths. The current public set includes 13,945 vehicles with real HTTPS primary-photo URLs; URL presence does not independently prove every remote image remains accessible.

## Fully online completion

The $250 reservation remains. Customer quote approval, secure dealer deposit, provider contract signing, dealer balance payment, title-document submission, and delivery tracking can happen online.

Enroll approved `online_portal_hosts` on the dealer record. Configure per-order `online-actions` for signing, dealer balance payment, title documents, or delivery tracking.

Actions only appear in the appropriate order state. Clicking a link never marks a contract signed or funds received; state changes still require evidence.

These are secure provider handoffs. Actual e-sign, lender, payment, and title accounts still need integration and end-to-end verification.
