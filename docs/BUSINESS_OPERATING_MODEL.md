# Own-dealership operating model

Status: licensing pending. Owner selected an own-dealership model. No legal entity or license has been verified.

## The product promise

Give buyers a familiar online vehicle-shopping experience. Confirm the vehicle, complete price, seller, and written terms before taking a deposit.

A source listing is a lead. It becomes reservable only after an actual source-dealer hold and an approved quote.

## Licensing and ownership

Buying a dealer license is not a valid shortcut. TxDMV states dealer licenses are not transferable or assignable.

An acquisition may require ownership amendments or a new application. A new legal entity can require a new license.

Confirm the entity, beneficial ownership, management, licensed premises, retail license category, bond, insurance, and operating authority.

Do not treat a wholesale-only license as retail authority. Obtain professional review of the actual acquisition structure.

Sources: [TxDMV dealer manual](https://www.txdmv.gov/sites/default/files/body-files/Motor_Vehicle_Dealer_Manual.pdf), [GDN categories](https://www.txdmv.gov/dealers/licensing/independent-gdn), [ownership updates](https://www.txdmv.gov/dealers/starting-your-new-dealership).

## Launch scope

Start with one licensed entity, one supported destination state, and a small dealer-confirmed selection.

Do not advertise nationwide transaction capability until the title, tax, transport, and consumer-contract processes support each destination.

The source catalog can remain broad. Checkout must enforce the destination allowlist.

## Supply and acquisition

Owner: dealership sourcing lead.

For each vehicle, retain the seller identity, acquisition price, all source fees, VIN, actual photographs, odometer, and a written hold.

The hold must identify its expiry, release terms, sale conditions, and the person authorized to commit the source dealer.

Obtain permission to reuse listings and images. Confirm feed/API rights before scheduled collection. Scraping capability does not establish redistribution rights.

Keep title/condition exclusions independent of source refreshes. Never reconstruct an unknown VIN through checksum guesses.

Record observed source prices as observations. Never equate an import timestamp with availability verification.

## Vehicle acceptance

Owner: inspection and title lead.

Collect:

- Title history and ownership chain.
- Brand, flood, theft, lien, and odometer evidence.
- Inspection report, dated photographs, and material-condition disclosures.
- Battery health evidence with test method, date, and technician identity.
- Hardware evidence from the actual vehicle.
- Purchased software versus subscriptions; no assumed transfer of FSD or connectivity.
- Remaining factory warranty evidence and any separate written warranty terms.
- Open-recall disposition and charging-equipment condition.
- Keys, charging adapters, tire condition, glass, underbody, and transport condition.

A clean title does not establish accident-free condition. A VIN does not establish current hardware or purchased software rights.

## Price and unit economics

Owner: dealership principal.

Show one consistent estimated vehicle price across cards, detail pages, and category pages. Disclose the current $1,500 planning fee explicitly.

A final quote replaces that estimate. Quote taxes, registration, documentation, delivery, and other mandatory amounts before collecting a deposit.

Review price advertising with counsel. Texas requires a dealer to honor advertised prices, subject to permitted exclusions.

[TxDMV advertising guidance](https://www.txdmv.gov/sites/default/files/body-files/Dealer_Advertising_Presentation.pdf)

Contribution equals vehicle proceeds plus retained fees, less acquisition, transport, inspection/reconditioning, marketing, return/warranty reserve, and other costs.

Taxes and registration are liabilities. They are excluded from contribution revenue.

Do not count lender reserve without an executed lender agreement and an eligible funded loan. The implemented model assumes no lender reserve.

The provisional minimum contribution is $1,000 per sale. The owner must approve it against actual acquisition cost and risk.

The price comparison is based on advertised listings. It is not an appraisal or a guaranteed resale value.

## Working capital

Owner: finance lead.

The $250 deposit is refundable customer money. Do not treat it as acquisition funding or profit.

Peak cash exposure equals acquisition, transport, reconditioning, and settlement needs, less cleared funds available for those purposes.

Example: a $25,000 vehicle plus $1,000 logistics requires roughly $26,000 before contingencies when usable buyer funding has not cleared.

A source-dealer hold reduces availability risk. It does not eliminate capital, seller-default, damage, return, or title risk.

Document the funding source, daily exposure cap, bank verification, reconciliation, and conditions for paying the source seller.

## Customer contract and disclosures

Owner: dealership principal with counsel.

Define the seller, deposit scope, quote validity, cancellation rules, timing, and dispute channel.

Provide the applicable Buyers Guide and separate warranty terms. The FTC says online used-car buyers are entitled to a Buyers Guide.

Applicability varies by vehicle and jurisdiction. The quote accepts an exemption only with a documented basis.

[FTC dealer guidance](https://www.ftc.gov/business-guidance/resources/dealers-guide-used-car-rule), [online buyer guidance](https://consumer.ftc.gov/articles/buying-used-car-dealer).

Do not promise seven-day returns or a warranty until the responsible party, eligibility, exclusions, funding reserve, and recovery process exist.

Do not use “official DMV form” labels for generated internal paperwork.

## Payments and fraud

Owner: finance lead.

Use a dedicated dealer merchant account. Confirm processor acceptance of the business and transaction pattern.

Accept the quote version and linked terms before opening card-only deposit checkout.

Only a signed webhook plus a server-retrieved matching checkout session can confirm payment.

Reconcile deposit liabilities daily. Expired or cancelled holds with late payments enter a refund queue.

Review identity, bank changes, lien payoffs, cash-reporting duties, sanctions screening, and funding fraud with qualified providers.

Do not collect identity documents or bank details through the free-request form.

[Stripe fulfillment](https://docs.stripe.com/checkout/fulfillment), [webhook verification](https://docs.stripe.com/events/manage-webhook-endpoints).

## Financing and trade-ins

These services are not offered in the current customer flow.

Before enabling financing, establish lender contracts, credit consent, applications, adverse-action responsibilities, applicable licensing, and approved disclosures.

Before accepting trade-ins, establish appraisal, lien payoff, negative-equity treatment, title acceptance, pickup, and revised tax treatment.

A loan calculator is not loan approval. A mileage formula is not a binding appraisal.

## Acquisition, delivery, and title

Owner: fulfillment lead.

Do not purchase until customer contracts and cleared funding satisfy the approved acquisition plan.

Retain source bill of sale, acquisition payment, title chain, and lien release.

Dispatch only with carrier insurance, a bill of lading, pickup-condition evidence, and a dispatch reference.

Obtain delivery acceptance, condition evidence, keys, and Tesla account-transfer confirmation.

Complete title/registration, tax remittance, return resolution, and final reconciliation before closing the order.

Texas requires licensed dealers to use webDEALER for title and registration processing. Confirm operational enrollment before launch.

[TxDMV dealer requirements](https://www.txdmv.gov/dealers).

## Returns, complaints, and disputes

Owner: customer operations lead.

Publish the actual cancellation and return policy before quoting.

Distinguish pre-contract deposit cancellation from post-contract vehicle returns. The latter requires contract review and vehicle recovery.

Define mileage limits, damage responsibility, transport costs, restocking terms if permitted, refund timing, and warranty claim routing.

Keep chargebacks, unexpected refunds, and fraud concerns in payment review. Do not continue fulfillment through those states.

## Operating queue and service levels

Each order has an action deadline and an append-only event trail.

The authenticated operator queue and durable outbox require a named human owner. No email delivery is claimed.

Proposed targets: review requests within one business day; resolve payment exceptions the same business day.

Before public service launch, configure monitored notification delivery and escalation coverage. A database outbox alone does not notify staff.

## Data and security

Customer access uses a private bearer token. Operator access uses a separate secret.

Use HTTPS, restricted hosting, encrypted disks/backups, least-privilege staff access, secret management, and tested restoration.

Inactive unpaid requests have a configurable 90-day anonymization process. Schedule it before production.

Paid transactions require a separate legally reviewed retention schedule. Identity verification belongs in a specialist system.

## Launch acceptance

- License and ownership structure confirmed for the selling entity and premises.
- Bond, insurance, bank, processor, and title process established.
- Source permission, vehicle hold, inspection, and title evidence recorded.
- Complete quote meets contribution and cash-exposure limits.
- Customer terms reviewed and accessible.
- Real Stripe test-mode deposit, cancellation, webhook retry, and refund proven with the merchant account.
- One controlled acquisition, delivery, title transfer, and reconciliation proven.
- Return/recovery process exercised before promising returns.
- Operator coverage, notifications, backups, retention, and incident handling verified.

The software enforces transaction checkpoints. Evidence references still require responsible human verification.
