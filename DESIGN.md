# Marketplace design

## Customer goal

Find a suitable used Tesla, understand uncertainty, request verification, and review a complete quote.

## Visual system

- Navy `#12304a` for primary text and brand elements.
- Blue `#1474a4` for primary actions.
- Pale cyan `#e5f5fa` for informative notices.
- White cards on a pale background.
- Large vehicle photography, clear prices, and a persistent filter rail.
- Responsive two-column cards and a collapsible filter rail on phones.

## Required behavior

Keep browsing available during dealership setup. Clearly identify the pending license status.

Use one estimated vehicle price across all views. Disclose the included planning fee and unquoted charges.

Separate source listings from seller-confirmed availability. Require evidence for condition and equipment claims.

Paid checkout follows a server-approved quote. Payment redirects do not establish payment.

Support keyboard controls, native modal focus handling, visible labels, and reduced motion.

## Source

Edit `web/index.html`, `web/styles.css`, and `web/app.js`. Run `python3 -m tools.build`.

Generated pages must not introduce guarantees, licenses, inspections, or inventory control absent from the underlying records.
