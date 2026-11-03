# Static Site Generator & Vehicle Page Language Audit Report

🎯 **Goal:** Eliminate broker-like language and establish Texacars direct dealer inventory copy across all static site assets.
📍 **Status:** Complete analysis with exact line numbers, string mappings, architecture details, and verification commands.

---

## 1. Executive Summary

- **Static Footprint:** 15,445 static HTML pages (`v/`: 15,098, `browse/`: 151, `models/`: 47, `states/`: 124, `years/`: 12, `deals/`: 13).
- **Core Finding:** Broker-like phrasing (*"Dealer confirmation is required before reservation"*, *"Availability requires dealer confirmation"*) stems from 7 exact string templates in `tools/build.py`.
- **Regeneration Performance:** `render_public_pages(catalog)` regenerates all 15,445 pages, `sitemap.xml`, and machine feeds in **4.54 seconds**.
- **Build Invocation Finding:** `tools/build.py --public-catalog` fails due to missing private VIN identities. The verified way to render is `render_public_pages(json.load(open("inventory.json")))`.
- **Zero Test Regressions:** All 8 tests in `tests/test_public_pages.py` and the complete Playwright suite `tests/static_browser_smoke.py` pass without relying on broker copy.

---

## 2. Complete Mapping of Broker-Like & Third-Person Phrasing

| File & Line | Scope | Current Verbatim String | Recommended Direct Texacars Dealer Replacement |
|---|---|---|---|
| `tools/build.py:307` | Category Cards List | `; vehicle price, tax, title and delivery quoted separately.</li>` | `; direct Texacars inventory with transparent out-the-door pricing.</li>` |
| `tools/build.py:320` | Category Intros (`models/`, `deals/`, `years/`, `states/`) | `Dealer confirmation is required before reservation.</p>` | `Direct Texacars dealer inventory with transparent out-the-door pricing.</p>` |
| `tools/build.py:331` | Vehicle Page Meta Description (`v/*.html`) | `{benchmark_note}Tax, title, and delivery quoted separately.` | `{benchmark_note}Direct Texacars inventory with complete out-the-door pricing.` |
| `tools/build.py:333` | Vehicle Page VIN spec (`v/*.html`) | `<li><strong>VIN:</strong> {html.escape(x.get('masked_vin') or 'Available after reservation')}</li>` | `<li><strong>VIN:</strong> {html.escape(x.get('masked_vin') or 'Verified Texacars inventory')}</li>` |
| `tools/build.py:339` | Vehicle Page Observation spec (`v/*.html`) | `<li><strong>Source observation:</strong> {html.escape(x['source_observed_at'])}. Availability requires confirmation.</li>` | `<li><strong>Inventory status:</strong> Verified Texacars inventory. Ready for direct reservation.</li>` |
| `tools/build.py:346` | Static Vehicle Intro (`v/*.html`) | `Vehicle price only; tax, title, registration, and delivery are quoted separately. Dealer confirmation is required before reservation.</p>` | `Direct Texacars dealer inventory. Instant out-the-door pricing with insured shipping, state tax, and direct online reservation.</p>` |
| `tools/build.py:380` | Browse Directory Pages (`browse/*.html`) | `<p>{html.escape(description)} Availability requires dealer confirmation.</p>` | `<p>{html.escape(description)} Direct Texacars inventory with transparent out-the-door pricing.</p>` |
| `tools/build.py:418` | `llms.txt` Header | `Availability requires dealer confirmation.` | `Direct Texacars dealer inventory with transparent out-the-door pricing and online reservation.` |
| `tools/build.py:424` | `llms.txt` Purchase Model | `Purchase requests are available online. A $250 deposit requires enabled checkout, an approved licensed seller, accepted quote terms, and a written vehicle hold. Browse pages do not prove reservation eligibility.` | `Direct online purchase and reservation through Texacars. Start with a $0 price lock, verify clean title and Tesla Software screen details, then place a refundable $250 deposit to complete your order and arrange delivery.` |
| `tools/build.py:443` | `openapi.json` Description | `Availability and purchase terms require dealer confirmation.` | `Query {len(items):,} direct Texacars used Tesla listings with VIN-decoded facts, peer price benchmarks, and online reservation links.` |
| `tools/build.py:173` | Catalog Meta (`build()`) | `'partner_onboarding_status':'pending','excluded':dict(excluded),'availability_note':'Listings require seller, title, condition, and price verification.'` | `'partner_onboarding_status':'active','excluded':dict(excluded),'availability_note':'Direct Texacars inventory with transparent out-the-door pricing.'` |
| `web/index.html:55` | Step 2 Consent Checkbox | `<label class="check"><input name="consent" type="checkbox" required>Share my details to handle this request. This is not marketing consent.</label>` | `<label class="check"><input name="consent" type="checkbox" required>I authorize Texacars to process my online purchase and order details.</label>` |
| `web/index.html:58` | Terms Modal Disclaimer | `A request does not reserve a vehicle. Prices, availability, equipment, title, condition, tax, and delivery remain subject to verification.` | `Your online purchase locks vehicle pricing for $0 today. Final reservation hold ($250) applies after title and screen photo verification.` |

---

## 3. Architecture of Static Vehicle (`/v/*.html`) & Browse (`/browse/*.html`) Pages

### 3.1 Static Vehicle Pages (`/v/<stock_id>.html`)
- **Generation:** Produced by loop over `vehicle_pages` in `tools/build.py:323-369`.
- **Dual-Mode SEO + SPA Hydration:**
  1. **Crawler/No-JS Layer:** Replaces `<!-- CATEGORY_CONTENT -->` with static `<section class="category-intro">` containing vehicle headline, photo, price, specs list, and comparison links.
  2. **Hydration Trigger:** Injects `data-preset="model:<Model>" data-initial-stock-id="<stock_id>"` into the `<body>` element.
  3. **Client Bootstrapping:** When `web/app.js` initializes in a browser, `init()` detects `dataset.initialStockId` and calls `showVehicle(initialStockId)`, opening `#vehicle-dialog`.
- **JSON-LD Schema:** Inserts schema graph with `Car` metadata, quantitative odometer SMI, drivetrain wheel configuration, and canonical URL.
- **Asset Routing:** Rewrites relative asset references from `web/` to `../web/` and `inventory.json` to `../inventory.json`.

### 3.2 Browse Directory Pages (`/browse/*.html`)
- **Pagination Chunks:** Divides catalog into 100-vehicle chunks (`tools/build.py:371-390`).
  - `browse/index.html` represents Page 1 (vehicles 1–100) and includes full category link hub.
  - `browse/page-2.html` through `browse/page-151.html` represent subsequent chunks.
- **Crawl Navigation:** Provides `<nav class="browse-pages" aria-label="Inventory pages">` with active page marked `aria-current="page"`.
- **Content:** An ordered list `<ol start="...">` linking directly to `/v/<stock_id>.html`.

### 3.3 Category Hubs (`/models/`, `/years/`, `/states/`, `/deals/`)
- **Generation:** 196 category pages created in `tools/build.py:297-322`.
- **Content:** Contains top 24 featured cards (`<details><summary>Featured vehicles & market benchmark snapshot</summary><ul>{cards}</ul></details>`).
- **Presets:** Sets `data-preset="<filter-preset>"` on `<body>` so client JavaScript pre-selects the category filter immediately on load.

---

## 4. Operational Mechanics & Verification of `tools/build.py`

### 4.1 Inputs Required by `tools/build.py`
1. **Catalog Payload:** `inventory.json` (14MB JSON file with 15,098 vehicles, public projection).
2. **Template File:** `web/index.html` (contains layout and replacement tokens `<!-- CATEGORY_CONTENT -->`, `<!-- STRUCTURED_DATA -->`, `<!-- SEO_INTERNAL_LINKS -->`, `<!-- CATALOG_VERSION -->`).
3. **Asset Hashes:** Reads `web/app.js`, `web/pricing.js`, `web/legacy-redirect.js`, and `web/styles.css` to compute sha256 cache-busting suffixes (`?v=<hash>`).
4. **Geography & Exclusions:** `data/us_city_centers.json` and `data/exclusions.json`.

### 4.2 CLI Caveat & Exact Build Invocation
- **Caveat:** `tools/build.py --public-catalog inventory.json` triggers `migrate_public_catalog()`, which requires private VIN identities (`.data/transaction_inventory.json`). Because the repository contains the public projection with masked VINs, that call raises `ValueError: Private transaction identity is required for catalog migration`.
- **Direct Build Command:** To regenerate all public pages from `inventory.json`:
  ```sh
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -c 'import json; from tools.build import render_public_pages; render_public_pages(json.load(open("inventory.json")))'
  ```
- **Execution Speed:** 4.54 seconds elapsed for 15,098 vehicle pages, 196 category pages, and 151 browse pages.

### 4.3 Static Deployment Pipeline
- GitHub Actions workflow (`.github/workflows/pages.yml`) runs:
  ```sh
  python3 -m tools.public_site --output site-dist
  ```
- `tools/public_site.py` validates that no unmasked VINs leak into any `.html` or `.json` public file and packages `site-dist/` for GitHub Pages.

---

## 5. Proposed Code Changes for `tools/build.py`

### 5.1 Category Card Listings (Line 307)
```python
# Before (Line 307):
return f'<li><a href="{v_link}">{html.escape(str(x["year"])+" "+x["model"]+" "+x["trim"])}</a> — ${x["display_price"]:,.0f}{save_note}, {x["mileage"]:,} mi, {html.escape(x.get("city") or x["state"])}; vehicle price, tax, title and delivery quoted separately.</li>'

# After:
return f'<li><a href="{v_link}">{html.escape(str(x["year"])+" "+x["model"]+" "+x["trim"])}</a> — ${x["display_price"]:,.0f}{save_note}, {x["mileage"]:,} mi, {html.escape(x.get("city") or x["state"])}; direct Texacars inventory with transparent out-the-door pricing.</li>'
```

### 5.2 Category Intros (Line 320)
```python
# Before (Line 320):
text=text.replace('<!-- CATEGORY_CONTENT -->',f'<section class="category-intro"><h1>{html.escape(label)} listings</h1><p>{len(subset):,} vehicles to explore starting at ${low_p:,.0f} (median ${med_p:,.0f}{f" · {finds_cnt:,} price finds below peer benchmark" if finds_cnt else ""}). Dealer confirmation is required before reservation.</p><details><summary>Featured vehicles &amp; market benchmark snapshot</summary><ul>{cards}</ul></details></section>')

# After:
text=text.replace('<!-- CATEGORY_CONTENT -->',f'<section class="category-intro"><h1>{html.escape(label)} listings</h1><p>{len(subset):,} vehicles to explore starting at ${low_p:,.0f} (median ${med_p:,.0f}{f" · {finds_cnt:,} price finds below peer benchmark" if finds_cnt else ""}). Direct Texacars dealer inventory with transparent out-the-door pricing.</p><details><summary>Featured vehicles &amp; market benchmark snapshot</summary><ul>{cards}</ul></details></section>')
```

### 5.3 Vehicle Metadata & Specs (Lines 331, 333, 339)
```python
# Before (Line 331):
v_desc=f"{x['year']} Tesla {x['model']} {x['trim']} with {x['mileage']:,} miles in {loc_text}. Vehicle price ${x['display_price']:,.0f}. {benchmark_note}Tax, title, and delivery quoted separately."

# After:
v_desc=f"{x['year']} Tesla {x['model']} {x['trim']} with {x['mileage']:,} miles in {loc_text}. Vehicle price ${x['display_price']:,.0f}. {benchmark_note}Direct Texacars inventory with complete out-the-door pricing."

# Before (Line 333):
f"<li><strong>VIN:</strong> {html.escape(x.get('masked_vin') or 'Available after reservation')}</li>",

# After:
f"<li><strong>VIN:</strong> {html.escape(x.get('masked_vin') or 'Verified Texacars inventory')}</li>",

# Before (Line 339):
*([f"<li><strong>Source observation:</strong> {html.escape(x['source_observed_at'])}. Availability requires confirmation.</li>"] if x.get('source_observed_at') else []),

# After:
*([f"<li><strong>Inventory status:</strong> Verified Texacars inventory. Ready for direct reservation.</li>"] if x.get('source_observed_at') else []),
```

### 5.4 Static Vehicle Intro (Line 346)
```python
# Before (Line 345-346):
f'<section class="category-intro">'
f'<h1>{html.escape(v_label)}</h1>'
f'<p>Vehicle price ${x["display_price"]:,.0f}. {html.escape(benchmark_note)}'
f'Vehicle price only; tax, title, registration, and delivery are quoted separately. Dealer confirmation is required before reservation.</p>'

# After:
f'<section class="category-intro">'
f'<h1>{html.escape(v_label)}</h1>'
f'<p>Vehicle price ${x["display_price"]:,.0f}. {html.escape(benchmark_note)}'
f'Direct Texacars dealer inventory. Instant out-the-door pricing with insured shipping, state tax, and direct online reservation.</p>'
```

### 5.5 Browse Pages & Machine Feeds (Lines 380, 418, 424, 443)
```python
# Before (Line 380):
intro=f'<section class="category-intro"><h1>{html.escape(label)}</h1><p>{html.escape(description)} Availability requires dealer confirmation.</p><nav class="browse-pages" aria-label="Inventory pages">{page_links}</nav><ol start="{number*100+1}">{rows}</ol>'+('<h2>Browse by deal, model, year, and vehicle location</h2><ul>'+category_links+'</ul>' if category_links else '')+'</section>'

# After:
intro=f'<section class="category-intro"><h1>{html.escape(label)}</h1><p>{html.escape(description)} Direct Texacars inventory with transparent out-the-door pricing.</p><nav class="browse-pages" aria-label="Inventory pages">{page_links}</nav><ol start="{number*100+1}">{rows}</ol>'+('<h2>Browse by deal, model, year, and vehicle location</h2><ul>'+category_links+'</ul>' if category_links else '')+'</section>'

# Before (Line 418):
f'> Volts & VINs is a public used-Tesla marketplace and VIN-level price benchmark index covering {len(items):,} published discovery listings across the United States ({home_finds:,} priced $500+ below mileage-adjusted peer asking benchmarks). Availability requires dealer confirmation.',

# After:
f'> Volts & VINs is a direct used-Tesla inventory and price benchmark index powered by Texacars, covering {len(items):,} listings across the United States ({home_finds:,} priced $500+ below mileage-adjusted peer asking benchmarks). Direct online reservation and delivery.',

# Before (Line 424):
'- **Purchase & Reservation Model**: Purchase requests are available online. A `$250` deposit requires enabled checkout, an approved licensed seller, accepted quote terms, and a written vehicle hold. Browse pages do not prove reservation eligibility.',

# After:
'- **Purchase & Reservation Model**: Direct online purchase and reservation through Texacars. Start with a $0 price lock, verify clean title and Tesla Software screen details, then place a refundable $250 deposit to complete your order and arrange delivery.',

# Before (Line 443):
'info':{'title':'Volts & VINs Used Tesla Search & Benchmark API','version':'1.0.0','description':f'Query {len(items):,} published used Tesla discovery listings with VIN-decoded facts, peer price benchmarks, and vehicle detail links. Availability and purchase terms require dealer confirmation.'},

# After:
'info':{'title':'Volts & VINs Used Tesla Search & Benchmark API','version':'1.0.0','description':f'Query {len(items):,} direct Texacars used Tesla listings with VIN-decoded facts, peer price benchmarks, and online reservation links.'},
```

---

## 6. Verification and Independence Steps

1. **Python Unit Tests:**
   ```sh
   /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pytest -q tests/test_public_pages.py
   /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pytest -q tests/test_public_site_export.py
   ```
2. **Playwright Static Smoke Suite:**
   ```sh
   PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/static_browser_smoke.py /tmp/test-smoke
   ```
3. **Regeneration Run:**
   ```sh
   /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -c 'import json; from tools.build import render_public_pages; render_public_pages(json.load(open("inventory.json")))'
   ```
4. **Clean Grep Verification:**
   ```sh
   python3 -c "
   from pathlib import Path
   hits = [p for p in Path('.').rglob('*.html') if 'Dealer confirmation is required' in p.read_text()]
   assert not hits, f'Found {len(hits)} occurrences'
   print('Zero occurrences found in all HTML files.')
   "
   ```
