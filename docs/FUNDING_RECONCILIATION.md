# Buyer funding reconciliation handoff

This release records observations. It does not transfer funds, cancel provider sessions, issue refunds, or pay anyone.

## Operator API

All endpoints require existing operator authorization.

- `POST /api/admin/orders/{id}/buyer-cash-receipts`: `currency:"USD"`, `quote_version`, `dealer_id`, positive integer `amount_cents`, `receipt_reference`, `evidence_reference`, past `settled_at`, `settled:true`, `excludes_reservation_deposit:true`.
- `POST /api/admin/orders/{id}/buyer-cash-reversals`: `currency:"USD"`, original `quote_version`, original `dealer_id`, `receipt_id`, positive integer `amount_cents`, unique `reversal_reference`, `evidence_reference`, past `observed_at`.
- Existing `POST .../financing`: `funded_amount_cents` means a cumulative net settled snapshot, never an additional delta. An optional strict `quote_version` rejects stale submissions. Each funded snapshot needs a canonical actual remittance/reconciliation reference. Amount or identity changes cannot reuse it.
- `POST /api/admin/orders/{id}/lender-funding-corrections`: `currency:"USD"`, original `quote_version`, original `dealer_id`, `expected_prior_reference`, unique `correction_reference`, `evidence_reference`, integer `net_settled_cents` including zero, past `observed_at`.
- Authenticated history: `GET .../buyer-cash-receipts` and `GET .../lender-funding-observations`.

Use canonical actual bank/remittance identifiers. Application IDs and rotating evidence URLs are not settlement identifiers. Put supporting document links in `evidence_reference`. New URL-shaped remittance references are rejected.

Exact cash/correction retries are idempotent. Changed payloads, cross-order reuse, stale heads, and conflicting identities fail. References are reserved across cash, reversals, lender observations, and corrections. Recorded deposit and full-balance payment identifiers cannot become additional funds.

## Customer contract

`funding_summary` contains USD integer amounts: `quote_version`, `quote_total_cents`, `credited_deposit_cents`, `lender_funded_cents`, `settled_balance_cents`, `net_additional_cash_cents`, `prior_quote_unallocated_cash_cents`, `prior_quote_unallocated_lender_cents`, `remaining_cents`, and `overpaid_cents`.

Boolean flags are `coverage_complete`, `funds_review_required`, `balance_checkout_allowed`, and `in_flight_balance_conflict`.

`balance_checkout_allowed` is the same ledger eligibility used by the existing full-balance route. Other existing seller, hold, agreement, and payment configuration gates still apply.

Public financing amounts use reconciled current net funds. A correction uses status `funding_reconciled`. Receipt IDs, remittance IDs, correction/evidence references, and seller fingerprints stay private.

## Safety and compatibility

- New additional cash is accepted after deposit/seller confirmation, not during initial quoting or on closed orders. Rejected late receipts require accounting review.
- Observed cash reversals and loan corrections remain possible after closure. They preserve the order state and all earlier observations.
- Historical corrections affect only their original context. They cannot fund a new quote or overwrite its financing status.
- Old unallocated money remains visible. No historical cash is fabricated from generic evidence strings.
- Legacy lender corrections can link directly to an actual historical funded event when its quote/seller binding is provable. No historical funding row is invented.
- Conditional approval and calculator down payments never count as settled funds.
- Release, dispatch, and delivery require reconciled coverage. Old pure-cash purchases need an actual quantified receipt or canonical settled balance evidence.
- Additional funds during an open/processing/reviewed full-balance payment create an internal reconciliation event. Release and new payment actions are blocked. Session/payment IDs remain intact.
- Provider sessions are not expired by this observational ledger. Existing canonical outcomes determine failed, pending, paid, and overpaid summaries.

Transport helper dependencies are commits `76bb272` and `89022cf`. The main/model hooks preserve accepted bookings after their original rate expires, enforce lifecycle progression, and require strict integer money/timestamps.

## Price and settlement differences

The remaining funding amount is a reconciliation measure. It is not permission to increase the accepted vehicle price or charge a buyer for a dealer expense. Provider deductions and dealer-paid fees require actual settlement terms and evidence. Resolve those differences with the selling dealer before asking the buyer for another payment. Do not record a dealer expense as money received from the buyer.
