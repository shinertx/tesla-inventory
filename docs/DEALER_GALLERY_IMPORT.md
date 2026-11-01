# Authorized dealer gallery feed

Use this path for a dealer-supplied gallery feed. It does not scrape vehicle pages or bypass blocked hosts. A host allowlist and an operator reference do not establish display rights. Obtain the actual feed permission first.

CSV columns are `vin,url,title,category`; title and category are optional. JSON accepts VIN keys with photo URL/object lists. VINs must exist in the current public catalog and remain outside review exclusions.

Run `python -m tools.import_dealer_photos --help` for the exact options. Default review is offline and produces an empty delta. Add `--verify` only for an authorized feed. Supply each exact public HTTPS hostname using `--allow-host` and record the actual authorization using `--authorization-reference`.

The verifier checks raster image bytes, dimensions and transfer limits. It rejects redirects and private network addresses. A403 or429 stops that host. DNS uses the OS resolver and has no independent deadline. Exact URL/content duplicates are removed; a person must still review distinct angles and display rights.

Outputs are new private JSON receipts under `.data/dealer-photo-reviews/`. Existing output files are never overwritten. The tool does not edit catalog prices, media, quarantine exclusions or source records. Review the delta, then reuse the existing photo-only merge/export tools for publication. The raw receipt is private and must not be placed on the public site.

No actual feed was available for this release. No additional photos were recovered.
