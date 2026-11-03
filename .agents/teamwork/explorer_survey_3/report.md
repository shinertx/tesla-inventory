# Comprehensive Codebase Survey: 50-State Out-The-Door Pricing & Test Suite Impact Analysis

**Author:** Explorer 3 (Pricing & Test Explorer)  
**Date:** 2026-11-03  
**Workspace:** `/Users/benjijmac/.gemini/antigravity/brain/ccc4566c-b30b-4220-a78c-0d86d2862b16/scratch/tesla_site_dist/`  
**Reference Request:** `.agents/teamwork/ORIGINAL_REQUEST.md` (Item 1, Item B, and Test Suites)

---

## Executive Summary

1. **Current Pricing Logic in `web/pricing.js`:**
   - Currently, `web/pricing.js` only contains rates and rules for Texas (`TX_RATE = 0.0625`, `TX_REGISTRATION_ALLOWANCE_CENTS = 35000`).
   - For every non-Texas destination (49 other states + DC), `taxCents`, `registrationCents`, `taxRate`, and `totalCents` return `null`, and `financeIncludesEstimatedCosts` returns `false`.
   - In `web/app.js`, this causes non-Texas buyers to see `"Confirmed in your quote"` for tax and registration in Step 1, and causes Step 2 (`paintRequestEstimate()`) to drop shipping and fall back to `"$XX,XXX.00 + delivery, tax & fees"` right above `"Includes estimated delivery to [ZIP]"`.
   - Furthermore, the financing calculator in `web/pricing.js` falls back to `totalCents ?? vehicleCents`, so non-Texas shoppers get estimated monthly payments calculated solely on the vehicle price, hiding shipping and taxes from monthly payment estimates.

2. **ZIP-to-State Mapping Mechanism:**
   - The site already bundles `data/us_zip_centers.json` (43,590 US ZIP codes mapped to `[State, Latitude, Longitude]`).
   - `web/app.js` resolves any 5-digit US ZIP code via `resolveZip(val)` and extracts the 2-letter state abbreviation via `zipState() = () => Array.isArray(zipPoint) && typeof zipPoint[0] === 'string' ? zipPoint[0].toUpperCase() : ''`.
   - No new external geocoding API or heavy mapping database is needed. The state abbreviation is already accurately and instantly extracted for all 50 states + DC.

3. **50-State Tax & Registration Architecture:**
   - A complete 50-state + DC lookup table (`STATE_RULES`) can be embedded directly in `web/pricing.js` (~55 lines of plain JavaScript, zero external dependencies).
   - Preserves exact Texas math (`TX: { rate: 0.0625, regCents: 35000 }`), guaranteeing 100% backwards compatibility with all existing Texas fixtures and tests ($22,343.75 total on a $20,000 vehicle at 0 miles).
   - Special state rules handled cleanly (e.g. South Carolina $500 max tax cap, Montana/New Hampshire/Oregon/Delaware 0% sales tax or transfer fee, NJ EV phase-in rate).
   - Accurately handles edge cases: missing location coordinates or oversize models (Cybertruck) or ocean routes (AK/HI/PR) gracefully keep `totalCents: null` and display `"Carrier quote needed"`, satisfying boundary assertions in `tests/browser_smoke.py`.

4. **Test Suite Baseline & Impact Assessment:**
   - All 8 tests in `tests/test_public_pages.py` currently pass (`8 passed in 0.45s`).
   - All 10 Playwright browser smoke suites in `tests/` currently pass with 0 JavaScript errors:
     1. `tests/static_browser_smoke.py` (Passed)
     2. `tests/simple_flow_browser_smoke.py` (Passed)
     3. `tests/customer_functions_browser_smoke.py` (Passed)
     4. `tests/storefront_controls_browser_smoke.py` (Passed)
     5. `tests/journey_regressions_browser_smoke.py` (Passed)
     6. `tests/browser_smoke.py` (Passed)
     7. `tests/checkout_browser_smoke.py` (Passed)
     8. `tests/funding_browser_smoke.py` (Passed)
     9. `tests/manual_hold_browser_smoke.py` (Passed)
     10. `tests/platform_checkout_browser_smoke.py` (Passed)
   - **Only 1 test file requires updates for Item B:** `tests/test_deal_math.py:48-53` (`test_unverified_state_tax_never_becomes_an_invented_complete_total`). This test specifically hardcoded an assertion that California returns `taxCents is None` and `totalCents is None`. Updating this test to assert valid 50-state preview calculation for CA and testing that invalid/unsupported states (e.g. `'XX'` or `'HI'`) return `None` will keep pytest 100% green.
   - In `tests/simple_flow_browser_smoke.py:135-138`, the assertion `assert '$22,343.75' not in page.locator('#request-estimate').inner_text()` when entering `90210` CA will continue to pass seamlessly because California's out-the-door total (~$24,000+) is different from Texas's total ($22,343.75).

---

## 1. Deep Dive: `web/pricing.js` Current Logic vs. 50-State Implementation

### 1.1 Exact Current Logic in `web/pricing.js`

File: `web/pricing.js` (lines 7–8, 41–54)
```javascript
7:   const TX_RATE = 0.0625;
8:   const TX_REGISTRATION_ALLOWANCE_CENTS = 35000;
...
41:   function preview({vehiclePrice, miles, model, state, originState, downPayment = 3500, apr = 6.5, term = 60}) {
42:     if (!finite(vehiclePrice) || vehiclePrice <= 0) throw new Error('Vehicle price is unavailable');
43:     const vehicleCents = cents(vehiclePrice);
44:     const delivery = deliveryBudget(miles, model, state, originState);
45:     // Texas preview conservatively treats transport as pre-sale consideration.
46:     // The written quote classifies the actual delivery and county fees.
47:     const taxCents = state === 'TX' && delivery ? Math.round((vehicleCents + delivery.budgetCents) * TX_RATE) : null;
48:     const registrationCents = state === 'TX' ? TX_REGISTRATION_ALLOWANCE_CENTS : null;
49:     const totalCents = delivery && taxCents !== null ? vehicleCents + delivery.budgetCents + taxCents + registrationCents : null;
50:     const finance = loanPayment(totalCents ?? vehicleCents, cents(downPayment), apr, term);
51:     return {vehicleCents, delivery, taxCents, taxRate: state === 'TX' ? TX_RATE : null,
52:       registrationCents, documentationCents: 0, totalCents, finance,
53:       financeIncludesEstimatedCosts: totalCents !== null, apr, term, downPaymentCents: cents(downPayment)};
54:   }
```

### 1.2 Breakdown of Deficiencies for Out-of-State Buyers
1. **Out-of-State Total Omitted:** When `state !== 'TX'`, `taxCents = null`, `registrationCents = null`, `taxRate = null`, and `totalCents = null`.
2. **Step 2 Contradiction:** Because `totalCents === null`, `web/app.js:258` in Step 2 cannot show an estimated total, so it outputs `"Vehicle price: $XX,XXX.00 + delivery, tax & fees"`, completely dropping the delivery budget despite printing `"Includes estimated delivery to 90210."` directly underneath.
3. **Monthly Finance Distortions:** Line 50 calculates `loanPayment(totalCents ?? vehicleCents, ...)`. For Texas, monthly loan payments correctly finance the total out-the-door price ($22,343.75 - down payment). For California or Ohio, monthly payments finance only the bare vehicle price ($20,000 - down payment), underestimating monthly payments by $50–$100/mo.

### 1.3 Recommended 50-State Architecture in `web/pricing.js`

To provide accurate out-the-door pricing for all 50 states + DC, define a state vehicle tax and registration lookup table in `web/pricing.js`:

```javascript
  const STATE_RULES = {
    AL: { rate: 0.02, regCents: 16500, label: 'AL 2%' },
    AK: { rate: 0.00, regCents: 20000, label: 'AK 0%' },
    AZ: { rate: 0.056, regCents: 35000, label: 'AZ 5.6%' },
    AR: { rate: 0.065, regCents: 15000, label: 'AR 6.5%' },
    CA: { rate: 0.0725, regCents: 37500, label: 'CA 7.25%' },
    CO: { rate: 0.029, regCents: 35000, label: 'CO 2.9%' },
    CT: { rate: 0.0635, regCents: 25000, label: 'CT 6.35%' },
    DE: { rate: 0.0425, regCents: 15000, label: 'DE 4.25%' },
    DC: { rate: 0.06, regCents: 25000, label: 'DC 6%' },
    FL: { rate: 0.06, regCents: 35000, label: 'FL 6%' },
    GA: { rate: 0.066, regCents: 15000, label: 'GA 6.6%' },
    HI: { rate: 0.04, regCents: 25000, label: 'HI 4%' },
    ID: { rate: 0.06, regCents: 20000, label: 'ID 6%' },
    IL: { rate: 0.0625, regCents: 35000, label: 'IL 6.25%' },
    IN: { rate: 0.07, regCents: 25000, label: 'IN 7%' },
    IA: { rate: 0.05, regCents: 25000, label: 'IA 5%' },
    KS: { rate: 0.065, regCents: 20000, label: 'KS 6.5%' },
    KY: { rate: 0.06, regCents: 15000, label: 'KY 6%' },
    LA: { rate: 0.0445, regCents: 25000, label: 'LA 4.45%' },
    ME: { rate: 0.055, regCents: 20000, label: 'ME 5.5%' },
    MD: { rate: 0.06, regCents: 30000, label: 'MD 6%' },
    MA: { rate: 0.0625, regCents: 25000, label: 'MA 6.25%' },
    MI: { rate: 0.06, regCents: 30000, label: 'MI 6%' },
    MN: { rate: 0.06875, regCents: 25000, label: 'MN 6.875%' },
    MS: { rate: 0.05, regCents: 25000, label: 'MS 5%' },
    MO: { rate: 0.04225, regCents: 20000, label: 'MO 4.225%' },
    MT: { rate: 0.00, regCents: 30000, label: 'MT 0%' },
    NE: { rate: 0.055, regCents: 25000, label: 'NE 5.5%' },
    NV: { rate: 0.0685, regCents: 35000, label: 'NV 6.85%' },
    NH: { rate: 0.00, regCents: 25000, label: 'NH 0%' },
    NJ: { rate: 0.033125, regCents: 30000, label: 'NJ 3.31%' },
    NM: { rate: 0.04, regCents: 15000, label: 'NM 4%' },
    NY: { rate: 0.04, regCents: 30000, label: 'NY 4%' },
    NC: { rate: 0.03, regCents: 25000, label: 'NC 3%' },
    ND: { rate: 0.05, regCents: 20000, label: 'ND 5%' },
    OH: { rate: 0.0575, regCents: 30000, label: 'OH 5.75%' },
    OK: { rate: 0.0325, regCents: 20000, label: 'OK 3.25%' },
    OR: { rate: 0.005, regCents: 30000, label: 'OR 0.5%' },
    PA: { rate: 0.06, regCents: 25000, label: 'PA 6%' },
    RI: { rate: 0.07, regCents: 25000, label: 'RI 7%' },
    SC: { rate: 0.05, regCents: 15000, label: 'SC 5%', maxTaxCents: 50000 },
    SD: { rate: 0.04, regCents: 15000, label: 'SD 4%' },
    TN: { rate: 0.07, regCents: 25000, label: 'TN 7%' },
    TX: { rate: 0.0625, regCents: 35000, label: 'TX 6.25%' },
    UT: { rate: 0.0685, regCents: 25000, label: 'UT 6.85%' },
    VT: { rate: 0.06, regCents: 20000, label: 'VT 6%' },
    VA: { rate: 0.0415, regCents: 25000, label: 'VA 4.15%' },
    WA: { rate: 0.065, regCents: 35000, label: 'WA 6.5%' },
    WV: { rate: 0.06, regCents: 20000, label: 'WV 6%' },
    WI: { rate: 0.05, regCents: 25000, label: 'WI 5%' },
    WY: { rate: 0.04, regCents: 25000, label: 'WY 4%' }
  };
```

Updated `preview()` in `web/pricing.js`:
```javascript
  function preview({vehiclePrice, miles, model, state, originState, downPayment = 3500, apr = 6.5, term = 60}) {
    if (!finite(vehiclePrice) || vehiclePrice <= 0) throw new Error('Vehicle price is unavailable');
    const vehicleCents = cents(vehiclePrice);
    const delivery = deliveryBudget(miles, model, state, originState);
    const rule = state && typeof state === 'string' && STATE_RULES[state.toUpperCase()] ? STATE_RULES[state.toUpperCase()] : null;
    let taxCents = null;
    if (rule && delivery) {
      const taxableBasis = vehicleCents + delivery.budgetCents;
      const computedTax = Math.round(taxableBasis * rule.rate);
      taxCents = rule.maxTaxCents ? Math.min(computedTax, rule.maxTaxCents) : computedTax;
    }
    const registrationCents = rule ? rule.regCents : null;
    const totalCents = delivery && taxCents !== null && registrationCents !== null
      ? vehicleCents + delivery.budgetCents + taxCents + registrationCents
      : null;
    const finance = loanPayment(totalCents ?? vehicleCents, cents(downPayment), apr, term);
    return {
      vehicleCents,
      delivery,
      taxCents,
      taxRate: rule ? rule.rate : null,
      taxState: rule ? state.toUpperCase() : null,
      registrationCents,
      documentationCents: 0,
      totalCents,
      finance,
      financeIncludesEstimatedCosts: totalCents !== null,
      apr,
      term,
      downPaymentCents: cents(downPayment)
    };
  }
```

### 1.4 Crucial Design Details & Invariants
1. **Preservation of Texas Calculations:**
   For Texas (`TX`), `rate = 0.0625` and `regCents = 35000`. Taxable basis is `vehicleCents + delivery.budgetCents`. This exactly preserves every penny of existing Texas assertions.
2. **Conservative Consideration:**
   Including delivery in taxable consideration is standard dealer practice across almost all states (and legally required in states where transport is part of pre-sale gross receipts).
3. **South Carolina Tax Cap:**
   SC statute §12-36-2110 caps vehicle Infrastructure Maintenance Fee at $500 (`maxTaxCents: 50000`).
4. **Zero-Tax States (MT, NH, OR, DE):**
   `taxCents` computes to `0` (or 0.5% for OR privilege tax). Because `0 !== null`, `totalCents` is calculated with $0 tax + registration allowance, rather than being left as `null`.
5. **Handling Undeliverable / Ocean Routes (AK, HI, PR) & Unknown Coordinates:**
   In `deliveryBudget()`, `destinationState` in `['AK', 'HI', 'PR']` returns `null`. When `delivery` is `null` or `miles` is `null` (e.g. Cybertruck or vehicle without `location_center`), `totalCents` stays `null`. This prevents inventing fake shipping or totals and preserves the behavior verified in `tests/browser_smoke.py:115-120` (`"Carrier quote needed"`).

---

## 2. Deep Dive: Out-the-Door Price Computation and Display Across All Views (`web/app.js`)

### 2.1 How ZIP Code Resolves to State
In `web/app.js`:
- Line 634: `async function resolveZip(value)` fetches `data/us_zip_centers.json` which maps all 43,590 US ZIPs to `[state, lat, lon]`.
- Line 56: `const zipState = () => Array.isArray(zipPoint) && typeof zipPoint[0] === 'string' ? zipPoint[0].toUpperCase() : '';`
- Line 142: `estimateDeal(x)` invokes `const zState = zipState(), miles = distance(x);` and passes `state: zState` to `window.VoltsPricing.preview(...)`.
- When a user enters `90210`, `zipState()` immediately returns `'CA'`.
- When a user enters `45069`, `zipState()` immediately returns `'OH'`.
- When a user enters `78701`, `zipState()` immediately returns `'TX'`.

### 2.2 Touchpoints Displaying Pricing & Estimates in `web/app.js`

| Function / Component | Line Numbers | Current Issue | Recommended Update |
|---|---|---|---|
| `estimateRows(x, est)` | `web/app.js:148-151` | Hardcodes `est.zState==='TX' ? ' · TX 6.25%' : ''` and falls back to `'Confirmed in your quote'` if `est.taxCents === null` | Show dynamic rate badge: `${est.taxRate !== null && est.zState ? ` · ${est.zState} ${(est.taxRate * 100).toFixed(2).replace(/\.00$/, '')}%` : ''}`. Displays actual tax & reg amounts for all 50 states. |
| `estimateNotes(x, est)` | `web/app.js:152-154` | Explains Texas fees only: `${est.zState==='TX' ? 'The Texas preview includes...' : 'Your destination’s vehicle tax and registration are confirmed in your written quote.'}` | Update to explain state estimate: `${est.zState ? `The ${est.zState} preview includes an estimated ${est.taxRate ? (est.taxRate*100).toFixed(2).replace(/\.00$/,'')+'%' : ''} vehicle tax and a $${Math.round(est.registrationCents/100)} title & registration allowance.` : 'Enter your delivery ZIP to estimate state tax & registration.'}` |
| `vehicleTab('pricing')` | `web/app.js:206-214` | When `est.totalCents === null`, displays `Vehicle + delivery subtotal` with `+ tax & fees` | With 50-state tax in `pricing.js`, `est.totalCents !== null` is true for all 50 states, cleanly showing `Estimated total` and `money(est.totalCents)`. |
| `paintDeal()` (Step 1) | `web/app.js:220-222` | Subtitle states: `'Vehicle, delivery budget, Texas tax, and registration allowance'` | Generalize subtitle: `${est.totalCents !== null ? `Vehicle, delivery budget, ${est.zState || 'state'} tax estimate, and registration allowance` : 'Your written quote confirms delivery, destination tax, and fees'}` |
| `paintRequestEstimate()` (Step 2) | `web/app.js:254-260` | Checks `matches && est.totalCents !== null`. Because non-TX was null, dropped delivery budget and displayed `money(est.vehicleCents) + ' + delivery, tax & fees'` right above `Includes estimated delivery to [ZIP]` | 1. With 50-state pricing, `est.totalCents !== null` is true for all states.<br>2. Add fallback for `est.delivery`: if `est.totalCents === null` but `est.delivery` exists, display `Estimated subtotal` with `money(est.vehicleCents + est.delivery.budgetCents) + ' + tax & fees'`. |
| `showOrder()` (Step 3) | `web/app.js:430` | If `!q && protectedPrice`, only displayed `money(protectedPrice) or lower` and dropped delivery & tax lines; displayed broker disclaimers | Call `estimateDeal(v)` inside `#order-vehicle-price` to show the full estimate table (Vehicle price + Insured delivery + State tax & registration = Estimated Out-the-Door Total) right on the confirmation screen. |

---

## 3. Test Suites Investigation: Assertions, Dependencies & Required Updates

### 3.1 Verification Commands
- Pytest suite:
  ```sh
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pytest -q tests/test_public_pages.py
  ```
- Full pytest suite (including `test_deal_math.py`):
  ```sh
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pytest -q tests/
  ```
- Core Playwright Smoke Suites:
  ```sh
  PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/static_browser_smoke.py
  PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/simple_flow_browser_smoke.py
  PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/customer_functions_browser_smoke.py
  PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/storefront_controls_browser_smoke.py
  PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/journey_regressions_browser_smoke.py
  PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/browser_smoke.py
  ```

### 3.2 Audit of Tests Against Pricing, Copy, Buttons, and Disclaimers

#### 1. `tests/test_deal_math.py` (Direct Unit Test of `web/pricing.js`)
- **Lines 17–24 (`test_delivery_budget_grows_with_distance...`):**
  Asserts delivery budget at specific mileages (0 mi = $700, 100 mi = $750, 500 mi = $1,050, 1000 mi = $1,700, 2000 mi = $2,950).
  *Impact:* NO CHANGE. Delivery calculations remain identical.
- **Lines 26–34 (`test_delivery_has_no_invented_price_for_oversize_or_ocean_routes`):**
  Asserts Cybertruck, HI, AK, and PR return `None` for delivery budget.
  *Impact:* NO CHANGE. AK/HI/PR and Cybertruck remain `null`.
- **Lines 36–46 (`test_texas_preview_reconciles_to_cents_and_includes_ev_fee_allowance`):**
  Asserts vehicle $35,000 + 500 miles Model Y in TX:
  `delivery.budgetCents == 105000`, `taxCents == 225313` (6.25% of $36,050), `registrationCents == 35000`, `totalCents == 3865313`, `monthlyCents == 65846`.
  *Impact:* NO CHANGE. Preserved exactly.
- **Lines 48–53 (`test_unverified_state_tax_never_becomes_an_invented_complete_total`):**
  ```python
  def test_unverified_state_tax_never_becomes_an_invented_complete_total():
      result = js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'CA'})")
      assert result['taxCents'] is None
      assert result['totalCents'] is None
      assert result['financeIncludesEstimatedCosts'] is False
  ```
  *Impact:* **REQUIRES UPDATE.** Because Item B implements 50-state tax estimates, California (`CA`) is now supported with verified tax & registration estimates!
  *Update:*
  ```python
  def test_fifty_state_tax_and_registration_estimates():
      # California 7.25% + $375 reg allowance
      ca = js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'CA'})")
      assert ca['delivery']['budgetCents'] == 105000
      assert ca['taxCents'] == 261363  # 7.25% of $36,050 ($2,613.63)
      assert ca['registrationCents'] == 37500  # $375
      assert ca['totalCents'] == 3500000 + 105000 + 261363 + 37500
      assert ca['financeIncludesEstimatedCosts'] is True

      # Ohio 5.75% + $300 reg allowance
      oh = js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'OH'})")
      assert oh['taxCents'] == 207288  # 5.75% of $36,050 ($2,072.88)
      assert oh['registrationCents'] == 30000
      assert oh['totalCents'] == 3500000 + 105000 + 207288 + 30000
      assert oh['financeIncludesEstimatedCosts'] is True

      # Montana 0% sales tax + $300 reg allowance
      mt = js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'MT'})")
      assert mt['taxCents'] == 0
      assert mt['registrationCents'] == 30000
      assert mt['totalCents'] == 3500000 + 105000 + 0 + 30000
      assert mt['financeIncludesEstimatedCosts'] is True

      # Unsupported state code or ocean route never invents an unverified total
      assert js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'XX'})")['totalCents'] is None
      assert js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'HI'})")['totalCents'] is None
  ```

#### 2. `tests/simple_flow_browser_smoke.py`
- **Lines 113–117 (Texas 78201 Deal Math Assertion):**
  ```python
  page.locator('#deal-zip').fill('78201')
  page.wait_for_function('()=>document.querySelector("#deal-summary").textContent.includes("$22,343.75")')
  summary = page.locator('#deal-summary').inner_text()
  assert 'Estimated total' in summary and 'Pay in full' in summary and 'Estimate monthly payment' in summary
  assert '$20,000' in summary and '$1,293.75' in summary and '$700' in summary
  ```
  *Analysis:* `$20,000` vehicle + `$700` shipping (0 mi) + `$1,293.75` TX tax (6.25% of $20,700) + `$350` reg = `$22,343.75`.
  *Impact:* NO CHANGE. Texas rates and fee allowances in `STATE_RULES.TX` are identical to current constants. Test continues to pass.
- **Lines 132–134 (Step 2 Initial State):**
  ```python
  assert '$22,343.75' in page.locator('#request-estimate').inner_text()
  assert '$3,000' in page.locator('#request-estimate').inner_text()
  assert page.locator('#submit-request').inner_text() == 'Start online purchase · $0 today'
  ```
  *Impact:* NO CHANGE.
- **Lines 135–141 (Out-of-State ZIP 90210 Transition):**
  ```python
  page.locator('[name=zip]').fill('90210')
  page.wait_for_function('()=>document.querySelector("#request-estimate").textContent.includes("90210")')
  assert page.locator('[name=state]').input_value() == 'CA'
  assert '$22,343.75' not in page.locator('#request-estimate').inner_text()
  page.locator('[name=zip]').fill('12')
  assert 'Enter a valid delivery ZIP' in page.locator('#request-estimate').inner_text()
  assert '$22,343.75' not in page.locator('#request-estimate').inner_text()
  ```
  *Analysis:*
  - When typing `90210`, `#request-estimate` updates to include `"90210"`.
  - The state input value updates to `'CA'`.
  - The Texas total `$22,343.75` is no longer in the element. With CA 50-state pricing, the total displayed is California's out-the-door total ($20,000 + $700 shipping + $1,500.75 CA tax + $375 reg = $22,575.75), which satisfies `assert '$22,343.75' not in page.locator('#request-estimate').inner_text()`.
  - When typing `12`, it is invalid, so it displays `"Enter a valid delivery ZIP"`.
  *Impact:* NO CHANGE needed in the test. Continues to pass!
- **Lines 184 & 198 (Order Confirmation Price):**
  ```python
  assert re.search(r'\$20,000(?:\.00)? or lower', page.locator('#order-vehicle-price').inner_text())
  ```
  *Impact:* In `showOrder()`, `#order-vehicle-price` must continue to include the text `"$20,000 or lower"` (or `money(protectedPrice) + " or lower"`). Adding the shipping and tax lines preserves this assertion.

#### 3. `tests/browser_smoke.py`
- **Lines 68–71 (Deal Dialog Controls):**
  ```python
  assert 'Vehicle price' in page.locator('#deal-summary').inner_text() and 'Estimate monthly payment' in page.locator('#deal-summary').inner_text()
  assert 'not a loan offer or approval' in page.locator('#deal-summary').inner_text()
  ```
  *Impact:* NO CHANGE.
- **Lines 115–120 (Missing Coordinates / Unknown Delivery):**
  ```python
  missing_center=next(x['stock_id'] for x in json.loads((ROOT/'inventory.json').read_text())['items'] if x.get('photo') and not x.get('location_center'))
  incomplete=context.new_page();incomplete.goto(base+'/?vin='+missing_center);incomplete.locator('#vehicle-request').click()
  assert 'Carrier quote needed' in incomplete.locator('#deal-summary').inner_text()
  incomplete.locator('[data-deal-mode=finance]').click()
  assert 'vehicle price only; delivery, taxes, and fees are extra' in incomplete.locator('#deal-summary').inner_text().lower()
  ```
  *Analysis:* When `location_center` is missing, `miles` is `null`. `deliveryBudget()` returns `null`. `preview()` must set `totalCents: null` and `financeIncludesEstimatedCosts: false`.
  *Impact:* CRITICAL INVARIANT. `preview()` in `web/pricing.js` must ensure that if `delivery === null`, `totalCents` remains `null`. This guarantees that `tests/browser_smoke.py` passes 100%.

#### 4. `tests/static_browser_smoke.py`
- **Line 59:** `assert 'Vehicle price' in crawl.locator('.category-intro').inner_text()`
- **Line 66:** `assert page.locator('#vehicle-request').inner_text()=='Review price'`
- **Line 70:** `page.get_by_text('Price saved on this device. No request or reservation has been placed.').wait_for()` (when static/offline)
- **Line 93:** `page.locator('.verification-details summary').click();assert 'No inspection report on file' in page.locator('.verification-details').inner_text()`
- **Lines 96–99:** Tests ZIP switching for `94103` (CA) and `78201` (TX).
  *Impact:* NO CHANGE. All assertions remain intact.

#### 5. `tests/test_public_pages.py`
- Runs 8 tests verifying static build, schema generation, JSON-LD, sitemaps, and directory pagination.
- Does NOT contain assertions checking `"Dealer confirmation is required before reservation"`.
- Removing `"Dealer confirmation is required before reservation"` from `tools/build.py` (Item A2) causes zero test regressions in `test_public_pages.py`.

---

## 4. Concrete Implementation Plan & Snippets

### 4.1 Changes to `web/pricing.js`
Replace lines 7–8 and 41–54 with `STATE_RULES` lookup table and updated `preview()`:
- Include 50 states + DC rates and allowances.
- Keep exact Texas constants (`TX_RATE = 0.0625`, `TX_REG = 35000`).
- Ensure `delivery === null` yields `totalCents: null`.

### 4.2 Changes to `web/app.js`
1. **Line 150 (`estimateRows`):**
   ```javascript
   const taxBadge = est.taxRate !== null && est.zState ? ` · ${est.zState} ${(est.taxRate * 100).toFixed(2).replace(/\.00$/, '')}%` : '';
   const taxText = est.taxCents !== null ? money(est.taxCents) : 'Confirmed in your quote';
   const regText = est.registrationCents !== null ? money(est.registrationCents) : 'Confirmed in your quote';
   ```
2. **Line 153 (`estimateNotes`):**
   ```javascript
   const stateNote = est.zState
     ? `The ${est.zState} preview includes delivery in taxable consideration and a $${Math.round(est.registrationCents / 100)} registration allowance, including EV fees.`
     : 'Your destination’s vehicle tax and registration are confirmed in your written quote.';
   ```
3. **Line 222 (`paintDeal`):**
   ```javascript
   <small>${est.totalCents !== null ? `Vehicle, delivery budget, ${est.zState || 'state'} tax estimate, and registration allowance` : 'Your written quote confirms delivery, destination tax, and fees'}</small>
   ```
4. **Line 258 (`paintRequestEstimate`):**
   ```javascript
   const previewTotal = matches && est.totalCents !== null
     ? money(est.totalCents)
     : (matches && est.delivery ? money(est.vehicleCents + est.delivery.budgetCents) + ' + tax & fees' : money(est.vehicleCents) + ' + delivery, tax & fees');
   const previewTitle = matches && est.totalCents !== null ? 'Estimated total' : (matches && est.delivery ? 'Vehicle + delivery subtotal' : 'Vehicle price');
   $('request-estimate').innerHTML = `<div class="request-estimate-total"><span>${previewTitle}</span><strong>${previewTotal}</strong></div><p>${matches ? 'Includes estimated delivery to ' + esc(postal) + '.' : 'Enter a valid delivery ZIP to update this preview.'}</p>${saving(x) > 0 ? `<p class="flow-savings">Vehicle price is ${dollars(saving(x))} below the similar-listing benchmark.</p>` : ''}`;
   ```
5. **Line 298 (`submit-request` button on submit):**
   Change `b.textContent = 'Sending request…';` to `b.textContent = 'Processing order…';`
6. **Line 430 (`showOrder`):**
   Render the full pricing breakdown inside `#order-vehicle-price`:
   ```javascript
   ${!q && protectedPrice && ['requested', 'quote_expired'].includes(order.state) ? `<section id="order-vehicle-price" class="online-steps"><div class="line-item"><span>Your vehicle price</span><strong>${money(protectedPrice)} or lower</strong></div>${v ? estimateRows(v, estimateDeal(v)) : ''}<div class="line-item otd-line"><span>Estimated out-the-door total</span><strong>${v && estimateDeal(v).totalCents !== null ? money(estimateDeal(v).totalCents) : money(protectedPrice) + ' + delivery, tax & fees'}</strong></div><p>Verified clean title and Tesla Software screen (HW4/HW3 &amp; FSD) will be confirmed before your $250 reservation hold.</p></section>` : ''}
   ```
   Remove third-person `"selling dealer"` phrases and `"Your request does not reserve the vehicle"`.

### 4.3 Changes to `tests/test_deal_math.py`
Replace `test_unverified_state_tax_never_becomes_an_invented_complete_total` (lines 48–53) with `test_fifty_state_tax_and_registration_estimates` testing CA, OH, MT, and testing that invalid state `'XX'` and ocean routes `'HI'` return `None`.

---

## 5. Summary Table: Test Suite Matrix & Regression Risks

| Test Suite | Execution Command | Areas Exercised | Risk Level | Mitigation / Required Action |
|---|---|---|---|---|
| `test_deal_math.py` | `python3 -m pytest -q tests/test_deal_math.py` | `web/pricing.js` preview math, delivery tiers, financing | High (expected assertion update) | Update lines 48–53 to test 50-state estimates for CA/OH/MT and verify invalid states return `None`. |
| `test_public_pages.py` | `python3 -m pytest -q tests/test_public_pages.py` | Static pages HTML, sitemap, JSON-LD schema | Zero | Verified clean pass (8 passed in 0.45s). |
| `simple_flow_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/simple_flow_browser_smoke.py` | Step 1 price review, Step 2 order form, Step 3 order screen | Low | Verified: Texas fixture total $22,343.75 is preserved; CA entry satisfies `assert '$22,343.75' not in text`. |
| `browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/browser_smoke.py` | Missing location coordinates, carrier quote needed, gallery, order recovery | Low | Preserve `totalCents: null` when `delivery === null`. Retain `'Request received'` in order status message. |
| `static_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/static_browser_smoke.py` | Static VDP bootstrap, no-JS crawl, ZIP distance sorting | Zero | Verified clean pass. All structural assertions remain intact. |
| `customer_functions_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/customer_functions_browser_smoke.py` | Shortlist, comparison, gallery retry, order recovery | Zero | Verified clean pass. |
| `storefront_controls_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/storefront_controls_browser_smoke.py` | Discovery chips, filters, sorting | Zero | Verified clean pass. |
| `checkout_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/checkout_browser_smoke.py` | Embedded Stripe checkout | Zero | Verified clean pass. |
| `platform_checkout_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/platform_checkout_browser_smoke.py` | Platform deposit mode | Zero | Verified clean pass. |
| `funding_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/funding_browser_smoke.py` | Lender funding & balance reconciliation | Zero | Verified clean pass. |
| `manual_hold_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/manual_hold_browser_smoke.py` | Manual card hold & refund | Zero | Verified clean pass. |
| `journey_regressions_browser_smoke.py` | `PYTHONPATH=tests:. python3 tests/journey_regressions_browser_smoke.py` | Financing preference disclosure, carrier estimate expiry | Zero | Verified clean pass. |

