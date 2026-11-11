# Master PRD: Volts & VINs (`voltsandvins.com` · Online Used-Tesla Dealership & Partner Network)

> [!IMPORTANT]
> **Single Source of Truth (`Volts-and-VINs` Production Stack)**
> - **Live Storefront:** https://voltsandvins.com/ (`GitHub Pages` CDN, repo [`/Users/benjijmac/Projects/Volts-and-VINs`](file:///Users/benjijmac/Projects/Volts-and-VINs))
> - **Live Checkout, Search & Image Proxy API:** https://api.voltsandvins.com/ (`meme-snipe-v19-vm` `/opt/volts-api/current`, `systemd` `volts-api.service` + 4-hour `volts-catalog-refresh.timer`)
> - **Curated Live Catalog (`Option B`):** **`~2,400`** Curated, Negotiable, Clean-Title US Teslas (`5,600+` 7-day fresh VINs indexed; `16,600+` 21-day national peer benchmark; no-haggle retail chains `Carvana`, `CarMax`, `AutoNation`, `EchoPark`, `DriveTime` excluded from curated browse).
> - **Regulatory Architecture:** **43 TAC § 215.85(a) W-2 Acquisition Director + `$25` `"Volts & VINs"` DBA** under Licensed Texas GDN (Day 1) $\rightarrow$ **Dedicated Volts & VINs Texas Independent GDN** (Day 45).

---

## 1. Core Thesis (YC Wedge)

Non-Tesla franchise dealerships (Ford, Toyota, Chevy, BMW, Honda) take Teslas on trade-in every day without understanding Tesla motor codes, `AMD Ryzen` vs. `Intel Atom` MCUs, `LFP` battery packs, `HW4` cameras, or paid Full Self-Driving—routinely pricing high-spec Teslas **`$1,500–$8,000` below mileage-adjusted peer value** and dumping them at auction after 45 days.

**Volts & VINs** turns fragmented, mispriced franchise Tesla trade-ins into a **Carvana-grade 100% online Tesla dealership with zero balance-sheet inventory risk**:
1. **Curated Partner Network Discovery (`$0` Lock Publicly):** Shoppers browse **`2,400+` clean-title Teslas** with proxied, OCR-scrubbed, `3%` border-cropped photography, Cash vs. Est. Monthly (`$XXX/mo`) pricing, `AMD Ryzen` / `LFP (100% Daily)` / `$4k` EV Tax Credit filters, instant 50-state shipping + tax estimates, and a **`$0` 24-Hour Price Lock + Printable Out-the-Door Buyer's Order**.
2. **1-on-1 Licensed GDN Fulfillment (`$250` Hold Into Dealer Stripe):** Upon a `$0` lock, our Deal Desk verifies physical availability, clean in-house title, and B2B wholesale net (`$500–$1,000` below retail ask + `$0` retail doc fee using TX Resale Certificate `Form 01-339`), issues a **1-on-1 written Buyer's Order (`43 TAC § 215.244(1)(B)`)**, collects the refundable `$250` hold into the licensed TX GDN's Stripe account, closes financing/wire, and ships insured direct from source lot to the buyer's driveway.

---

## 2. Verified Texas Legal & Money-Flow Architecture (`43 TAC Chapter 215`)

| Rule / Constraint | Legal Reality | Volts & VINs Production Implementation |
| :--- | :--- | :--- |
| **Brokering Prohibition (`43 TAC § 215.85(a)-(b)`)** | Outside unlicensed LLCs **cannot** take per-car profit splits or set vehicle prices; only a **bona fide employee** of the licensed GDN may earn per-car sales commissions. | **Ben McMillan** joins the San Antonio TX GDN as a **bona fide W-2 Commissioned Acquisition Director** (`90%+` commission above `$500` house pack); `JENNI PRO INC` charges at most a flat monthly software fee (`$0` per-car fee). See [`TEXAS_DEALER_PASS_THROUGH_AGREEMENT.md`](file:///Users/benjijmac/Projects/Volts-and-VINs/docs/TEXAS_DEALER_PASS_THROUGH_AGREEMENT.md). |
| **Advertising Unowned Vehicles (`43 TAC § 215.245(e)` & `§ 215.244(1)(B)`)** | Dealers cannot advertise unowned vehicles *as owned in-stock inventory*, while **1-on-1 direct communications (`§ 215.244(1)(B)`)** are exempt from advertising rules `[UNVERIFIED: confirm exact public disclosure wording with TX auto counsel]`. | Public storefront collects **`$0` publicly** (`CHECKOUT_ENABLED=false` until GDN Stripe is live) and frames Step 1–2 as a free 24-hour price lock; binding VIN/seller quotes and `$250` holds occur strictly inside the 1-on-1 Buyer's Order portal. |
| **Dealer Brand Identity** | Storefront must operate under the licensed GDN's legal name or registered trade name. | Licensed GDN files a **`$25` `"Volts & VINs"` DBA** with TX SOS + updates `TxDMV eLICENSING` within 30 days, while Volts & VINs Auto LLC files its own 5-space TX GDN (`~45` days). |
| **Zero-Leakage Photo & Identity Shield** | Public HTML/JSON cannot leak CarGurus/dealer URLs, watermarks, or full VINs before deposit hold. | `100%` of external image URLs route through [`app/image_proxy.py`](file:///Users/benjijmac/Projects/Volts-and-VINs/app/image_proxy.py) (`SHA-256` token, DNS-pinned SSRF guard, **OCR phone/URL/banner scrubber** [`tools/ocr_photo_scrubber.py`](file:///Users/benjijmac/Projects/Volts-and-VINs/tools/ocr_photo_scrubber.py) + **`3%` border crop & EXIF strip**). |

---

## 3. Shipped Production Architecture (Verified Live)

1. **Option B Curated Pricing & Rare-Trim Engine ([`tools/build.py`](file:///Users/benjijmac/Projects/Volts-and-VINs/tools/build.py), [`tools/pricing.py`](file:///Users/benjijmac/Projects/Volts-and-VINs/tools/pricing.py)):**
   - Excludes `Carvana`, `CarMax`, `AutoNation`, `EchoPark`, and `DriveTime` from `curated` browse.
   - Uses a `21-day` national peer-group baseline (`16,600+` Teslas) for `mileage_reference` while publishing only `7-day` fresh listings.
   - Sets `$500` pre-negotiation gross spread floor on negotiable dealers (`MIN_CURATED_SPREAD_CENTS=50000`) + `+$1,000` retail buffer (`RARE_TRIM_BUFFER_CENTS=100000`) on rare `<5`-peer trims (e.g., 2025 Cyberbeast, 2026 trims).
2. **OCR Banner Scrubber + `3%` Anti-Reverse-Search Image Proxy ([`tools/ocr_photo_scrubber.py`](file:///Users/benjijmac/Projects/Volts-and-VINs/tools/ocr_photo_scrubber.py), [`app/image_proxy.py`](file:///Users/benjijmac/Projects/Volts-and-VINs/app/image_proxy.py)):**
   - Automatically detects dead `403` S3 URLs (instant sold-car signal), dealer phone numbers, `.com` URLs, and top/bottom placard banners while preserving Tesla center-screen software/FSD photos.
   - Trims `3%` outer borders and re-encodes clean EXIF-stripped JPEGs at the edge relay.
3. **Carvana-Grade Storefront & Simplified Checkout UX ([`web/index.html`](file:///Users/benjijmac/Projects/Volts-and-VINs/web/index.html), [`web/app.js`](file:///Users/benjijmac/Projects/Volts-and-VINs/web/app.js), [`web/pricing.js`](file:///Users/benjijmac/Projects/Volts-and-VINs/web/pricing.js)):**
   - **Plain-English, Single-CTA Checkout Funnel:** One clear primary action per screen (`Review price` -> `Step 1: Out-the-door price` with `Continue · Lock price for $0` -> `Step 2: Your purchase details` with `Lock price for 24 hours · $0 today` -> `Step 3: Live order tracker + Printable Out-the-Door Summary`). Zero B2B jargon and zero competing buttons.
   - **Cash Price vs. Est. Monthly (`$XXX/mo`)** browse toggle with `tabular-nums`.
   - Grounded Tesla specs: **`AMD Ryzen`**, **`LFP (100% Daily)`**, **`FSD Listed`**, **`$4k EV Credit Eligible*`**, and verified **`HW4`**.
   - Optional **4-Year Battery & Drive-Unit Protection + GAP (`+$2,340` or `~$39/mo`)** add-on carried seamlessly from `deal-dialog` into `request-dialog`.
   - Native `<dialog closedby="any">` light-dismiss with Safari coordinate fallback and `enterkeyhint` / step-heading focus transitions.
4. **Automated 4-Hour VM Refresh Pipeline (`meme-snipe-v19-vm`):**
   - `volts-catalog-refresh.timer` sweeps live CarGurus + Autolist partitions, runs OCR photo scrubbing, rebuilds `Option B` curated catalog + static SEO pages, updates `/opt/volts-api/current`, and publishes public artifacts to `voltsandvins.com`.

---

## 4. Path to `500 Cars/Month` (`~$2.4M/Month` Gross Profit)

See [`docs/YC_500_CARS_MONTH_PLAN.md`](file:///Users/benjijmac/Projects/Volts-and-VINs/docs/YC_500_CARS_MONTH_PLAN.md) and [`docs/DEALER_PARTNER_FEED_AGREEMENT.md`](file:///Users/benjijmac/Projects/Volts-and-VINs/docs/DEALER_PARTNER_FEED_AGREEMENT.md) for the complete bottleneck playbook:
1. **Immediate (`Cars 1–10/mo`):** Execute [`docs/TEXAS_DEALER_PASS_THROUGH_AGREEMENT.md`](file:///Users/benjijmac/Projects/Volts-and-VINs/docs/TEXAS_DEALER_PASS_THROUGH_AGREEMENT.md) with San Antonio GDN, file `$25` `"Volts & VINs"` DBA, connect GDN Stripe (`CHECKOUT_ENABLED=true`), and close cash/credit-union wire buyers with `$0` float.
2. **45-Day Unlock (`Cars 10–50/mo`):** Open dedicated Volts & VINs TX Independent GDN, activate `CUDL` + `RouteOne`/`Dealertrack` lender portals, and turn on `$500k–$1.5M` pre-sold NextGear/AFC floorplan line.
3. **Scale (`Cars 50–500/mo`):** Enroll `150` franchise dealer groups onto direct `HomeNet`/`vAuto` feeds (`$750`-back pre-agreed wholesale net + un-watermarked DMS photos), use 48-hour bank title sight drafts (`$5M` pre-sold facility), enforce `"In-House Clear Title"` gate before buyout, and automate Super Dispatch photo-eBOL carrier pickups.
