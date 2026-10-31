# Dealer-owned Tesla fulfillment marketplace

## Decision and roles

The platform generates demand, matches vehicles, coordinates the buying experience, and earns an agreed transaction spread.

Dealers retain vehicle ownership and act as the sellers and fulfillment partners. Vehicles are never purchased into platform inventory.

Customers get a branded, guided buying experience. Their final quote and contract identify the actual selling dealer.

This supersedes the earlier own-dealership acquisition/resale design.

## Is the model good?

It is a credible model to test. It reduces the capital tied up in owned vehicles and lets existing dealers supply fulfillment capacity.

Its economics depend on three things: committed dealer supply, affordable qualified demand, and a spread the dealer actually pays.

A catalog, a price difference, or a reservation is not proof of a profitable sale.

The durable customer value is finding a suitable Tesla and completing the purchase reliably. The catalog is a means to that outcome.

The business must give dealers incremental buyers or faster sales. The agreement must compensate the platform for that contribution.

## Transaction flow

Demand → match → supplier commitment and quote → dealer deposit → dealer acceptance → dealer funding → dealer dispatch → delivery → spread reconciliation.

The code uses:

`requested → quoted → checkout_pending → deposit_paid → dealer_confirmed → dealer_funded → in_transit → delivered → settlement_pending → completed`

There is no platform vehicle-acquisition, inventory-funding, or title-through-platform stage.

## Supplier onboarding

Retain the dealer's verified legal identity, license evidence, address, permitted destination states, payment account, and signed agreement.

The agreement must define:

- Dealer ownership, seller role, and fulfillment duties.
- Inventory/data/photo permissions and update obligations.
- Vehicle-specific net proceeds and the customer price the dealer agrees to honor.
- The platform's spread, attribution, settlement timing, refund treatment, and clawbacks.
- Who receives customer funds and handles financing, taxes, title, delivery, warranty, and returns.
- Hold duration, cancellation, substitutions, damage, complaints, and service targets.

Do not assume a publicly listed car belongs to an enrolled fulfillment partner.

The configuration approval flag records an operational/legal review. It does not establish regulatory authority by itself.

## Demand channels

Measure organic search, paid search, referrals, affiliates, and other channels separately.

Requests retain channel and campaign attribution. Client-provided attribution is a claim; it is not a payment entitlement.

Use actual campaign spend and settled earnings to assess contribution. Do not optimize around raw traffic or deposits.

Test one repeatable segment first, such as a specific Tesla model and price range.

Proposed pilot: obtain written dealer commitments and complete a small set of dealer-fulfilled sales before expanding paid acquisition.

A useful pilot proves price integrity, supplier acceptance, delivery, customer support, and collected spread after channel costs.

## Pricing and spread

The private supplier net is not a platform vehicle purchase price.

Expected spread = customer vehicle price minus the dealer's agreed vehicle net proceeds.

Expected contribution = spread minus demand, platform service, payment, reserve, and other platform-borne costs.

Taxes, title/registration, dealer documentation, and delivery charges are dealer/pass-through amounts. They are not platform revenue in this implementation.

The catalog's $1,500 planning markup is an estimate. It does not establish a payable dealer obligation or earned profit.

An approved quote requires a supplier commitment and spread agreement. Customer vehicle pricing is consistent across shopping views.

## Payments

The implemented Stripe adapter creates deposits directly on the fulfilling dealer's connected account.

It scopes checkout lookup and refunds to that account. Signed webhook account identity must match the stored order.

A $250 refundable deposit does not produce a $1,500 platform fee. The deposit adapter takes no application fee.

The remaining vehicle balance is paid to the dealer or its financing/settlement provider. The platform records dealer funding evidence.

The platform records spread only after dealer fulfillment and a reconciled dealer remittance.

Stripe supports connected-account direct charges and platform fees, but an actual merchant/Connect setup still requires approval and sandbox verification.

[Stripe direct-charge documentation](https://docs.stripe.com/connect/direct-charges.md?platform=web&ui=stripe-hosted)

## Fulfillment responsibilities

The dealer confirms availability, title, liens, equipment, condition, recalls, and written customer terms.

A quote cannot outlive its vehicle hold. Reconfirm expired dealer commitments before advancing fulfillment.

The dealer accepts the buyer's contract, receives the purchase balance, and dispatches the vehicle.

Retain carrier coverage, bill of lading, pickup condition, delivery acceptance, and Tesla app-transfer evidence.

The dealer handles title directly to the buyer and records applicable tax/registration completion.

Do not advertise platform inspection certification, owned hubs, warranties, or return guarantees without the underlying agreement and evidence.

## Settlement and reversals

A deposit is a dealer-held customer liability. It is excluded from platform earnings.

An advertised spread is expected income. It is excluded from collected-earnings reporting.

Settlement requires a dealer statement and receipt. Received spread plus documented adjustments must reconcile to the approved quote.

Idempotency prevents recording the same settlement twice. Reversals are separate entries and reduce collected spread and contribution.

The current settlement endpoint records operator-verified external receipts. It does not move money or automatically invoice dealers.

## Customer experience

Use clean shopping language, one vehicle price, vehicle location, stock number, photos, and clear purchase steps.

Supplier names, raw prices, and listing links belong in authenticated operations. Identify the actual seller before the customer accepts terms or pays.

VINs and photographs remain searchable. Hiding supplier details does not replace commercial agreements or protect against every bypass.

The final quote contains the applicable seller identity, complete price, Buyers Guide basis, warranty, return, and deposit terms.

## Customer support and risk

The platform coordinates support; the selling dealer performs its contractual obligations.

Customer cases cover returns, warranty, transport damage, title delays, and other purchase issues.

Specify eligibility, responsible party, transport costs, refund timing, escalation, and the effect on platform fees.

Disputes and unexpected deposit refunds freeze progress. Dealer revocation blocks new transactions; existing money must still be reconciled.

Dealer ownership reduces inventory capital exposure. Demand spend, service obligations, disputed fees, and execution risk remain.

## Launch acceptance

- Enrolled dealer agreement, license evidence, payment account, and approved states.
- Actual vehicle commitment and evidence-supported customer quote.
- Real provider sandbox deposit, webhook, cancellation, and refund.
- Dealer acceptance, balance receipt, dispatch, delivery, title, and tax proof.
- Reconciled platform remittance and any clawbacks.
- Positive contribution after measured demand and support costs.
- Monitored operations, privacy, backups, and customer recovery.

No dealer agreement, merchant account, live payment, or dealer-fulfilled customer outcome was established during this code change.
