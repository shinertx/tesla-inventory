# Agent instructions for Volts & VINs

## Scope and ownership

- Use this repository as the application source.
- Build a branded Tesla buying experience over dealer-owned inventory.
- Keep source dealers distinct from the actual licensed retail seller.
- Use existing JENNi/Jockey infrastructure and its Stripe account.
- Follow the user's latest authorization and preferences.
- Do not request approval again for already authorized reversible work.
- Keep vendor outreach as drafts unless the user authorizes sending.
- Coordinate ownership before sharing files with another agent.
- Record shared changes in GitHub instead of relying on local scratch files.

## Establish current state

- Read README.md and the relevant operating document before changing its area.
- Check the branch, working tree, and current deployment before reporting status.
- Distinguish built, committed, merged, deployed, enabled, and end-to-end proven behavior.
- State material blockers directly.
- Stop repeated failed attempts and choose a cheaper diagnostic path.

## Data and customer claims

- Keep raw VINs, supplier terms, and acquisition prices outside customer artifacts.
- Preserve private VIN resolution for orders and payment bindings.
- Use stock IDs for public pages, catalog rows, and gallery keys.
- Never publish `.data`, credentials, databases, payment evidence, or private backups.
- Do not claim historical source exposure has been erased.
- Reject known title-risk evidence before publication.
- Treat unknown condition, equipment, title, and availability as unverified.
- Preserve real condition photographs.
- Exclude reviewed advertisements and generic imagery through photo normalization.
- Never invent photographs, lender offers, carrier quotes, seller credentials, or guarantees.

## Money and fulfillment

- Use integer cents for financial calculations.
- Count only canonically verified captured deposits and reconciled settled funds as purchase credit.
- Never credit an uncaptured card hold or a calculator down payment.
- Preserve order, quote, VIN, account, amount, currency, and test/live bindings.
- Preserve inventory locks during unresolved payments, refunds, releases, and funding review.
- Expire internal commitments only after verified terminal outcomes without unresolved funds.
- Distinguish internal release requests from confirmed external dealer release.
- Never fabricate provider events, payment IDs, or paid database states.
- Keep production activation gates disabled until actual seller, agreement, state, and permission requirements are verified.
- Preserve the installed inactive-production wrapper until a reviewed activation release replaces it.
- Document estimates clearly.
- Require actual comparable delivered quotes before claiming a Carvana savings advantage.

## Implementation and checks

- Edit frontend sources in web/ and regenerate published pages through tools.build.
- Keep private transaction inventory separate from its customer projection.
- Do not rebuild from incomplete sources or publish stale source identities.
- Run checks appropriate to the change.
- Add meaningful regressions for financial, concurrency, and boundary failures.
- Do not add tests that merely restate low-impact text changes.
- Test affected controls at desktop and mobile widths.
- Keep mock-provider, real Stripe TEST, and live customer evidence distinct.
- Do not repeat passed suites without changed inputs or unresolved concerns.

## Release and operations

- Follow ops/purchase_release/README.md for backend releases.
- Publish only the tools.public_site customer allowlist.
- Check disk headroom before staging release copies.
- Preserve active releases, immediate rollback copies, private history, and customer databases.
- Keep production and TEST environments, sellers, credentials, and databases separate.
- Never place synthetic sellers or vehicles in production.
- Use exact reviewed commit SHAs and verify artifact hashes.
- Allow only the documented updated_at heartbeat drift in private deal packets.
- Fail on business-record drift during staging.
- Never restore an older order database automatically during rollback.
- Report remaining provider and account gaps without claiming the whole purchase flow is live.
