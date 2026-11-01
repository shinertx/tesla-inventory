# Private deal review

Deal reports contain private sourcing data and must not be published with the storefront.

Run `python3 -m tools.top_arbitrage_deals` from the repository root.
The default report is `.data/top-arbitrage-deals.md`, which Git ignores.
Use `--min-spread` to set the minimum modeled gross spread before costs.

The report compares asking-price scenarios. It does not establish collected revenue or net profit.
Availability, seller commitments, vehicle evidence, and transaction costs require review before a payable quote.
