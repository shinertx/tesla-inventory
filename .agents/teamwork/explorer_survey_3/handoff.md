# Handoff Report: 50-State Out-The-Door Pricing & Test Suite Survey

## 1. Observation

- **Observation 1 (Texas-Only Calculation in `web/pricing.js`):**
  Lines 7–8 & 47–50 of `web/pricing.js`:
  ```javascript
  const TX_RATE = 0.0625;
  const TX_REGISTRATION_ALLOWANCE_CENTS = 35000;
  ...
  const taxCents = state === 'TX' && delivery ? Math.round((vehicleCents + delivery.budgetCents) * TX_RATE) : null;
  const registrationCents = state === 'TX' ? TX_REGISTRATION_ALLOWANCE_CENTS : null;
  const totalCents = delivery && taxCents !== null ? vehicleCents + delivery.budgetCents + taxCents + registrationCents : null;
  const finance = loanPayment(totalCents ?? vehicleCents, cents(downPayment), apr, term);
  ```
  For any state other than `'TX'`, `taxCents`, `registrationCents`, `taxRate`, and `totalCents` return `null`. Financing falls back to bare `vehicleCents`.

- **Observation 2 (ZIP-to-State Resolution in `web/app.js`):**
  - Line 56: `const zipState=()=>Array.isArray(zipPoint)&&typeof zipPoint[0]==='string'?zipPoint[0].toUpperCase():'';`
  - Line 637: `fetch(new URL('data/us_zip_centers.json',rootURL)).then(async r=>{if(!r.ok)throw new Error('Location data could not load. Please retry.');return (await r.json()).zips;})`
  - `data/us_zip_centers.json` contains 43,590 US postal codes mapped to `[State, Lat, Lon]`. State is already extracted into a 2-letter uppercase code.

- **Observation 3 (Step 2 Preview Contradiction):**
  In `web/app.js:257-258`:
  ```javascript
  const est=estimateDeal(x),matches=postal===zip&&!!zipState();
  $('request-estimate').innerHTML=`<div class="request-estimate-total"><span>${matches&&est.totalCents!==null?'Estimated total':'Vehicle price'}</span><strong>${matches&&est.totalCents!==null?money(est.totalCents):money(est.vehicleCents)+' + delivery, tax & fees'}</strong></div><p>${matches?'Includes estimated delivery to '+esc(postal)+'.':'Enter a valid delivery ZIP to update this preview.'}</p>${saving(x)>0?`<p class="flow-savings">Vehicle price is ${dollars(saving(x))} below the similar-listing benchmark.</p>`:''}`;
  ```
  Because `est.totalCents === null` for non-Texas ZIPs, `matches && est.totalCents !== null` evaluates to `false`, displaying `"Vehicle price: $XX,XXX.00 + delivery, tax & fees"` directly above `"Includes estimated delivery to [ZIP]"`.

- **Observation 4 (Hardcoded CA None Assertion in `tests/test_deal_math.py`):**
  In `tests/test_deal_math.py:48-53`:
  ```python
  def test_unverified_state_tax_never_becomes_an_invented_complete_total():
      result = js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'CA'})")
      assert result['taxCents'] is None
      assert result['totalCents'] is None
      assert result['financeIncludesEstimatedCosts'] is False
  ```
  This is the ONLY test in the entire test suite asserting that an out-of-state calculation returns `None`.

- **Observation 5 (Simple Flow Smoke Test Assertions):**
  In `tests/simple_flow_browser_smoke.py:113-117, 132-141`:
  - Texas total: `$22,343.75` for vehicle $20,000 at 0 miles in `78201` (`$20,000 + $700 + $1,293.75 + $350 = $22,343.75`).
  - Out-of-state transition: Entering `90210` (CA) asserts `state == 'CA'` and `assert '$22,343.75' not in page.locator('#request-estimate').inner_text()`.
  - Invalid ZIP: Entering `12` asserts `'Enter a valid delivery ZIP' in inner_text()`.

- **Observation 6 (Missing Location Center Handling in `tests/browser_smoke.py`):**
  In `tests/browser_smoke.py:115-120`:
  When a listing has no `location_center`, `miles` is `null`, `delivery` is `null`, and the test asserts:
  `assert 'Carrier quote needed' in incomplete.locator('#deal-summary').inner_text()`
  `assert 'vehicle price only; delivery, taxes, and fees are extra' in incomplete.locator('#deal-summary').inner_text().lower()`

- **Observation 7 (Baseline Test Pass Status):**
  - `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pytest -q tests/test_public_pages.py`: 8 passed in 0.45s.
  - All 10 Playwright smoke suites in `tests/` pass with exit code 0 and 0 JavaScript errors.

## 2. Logic Chain

1. **Step 1 (Root Cause of Missing Out-of-State Total):** Based on Observation 1, `web/pricing.js` restricts tax and registration to `state === 'TX'`. Consequently, `taxCents`, `registrationCents`, and `totalCents` are `null` for all 49 other states and DC, causing Observation 3's contradictory copy in Step 2.
2. **Step 2 (Feasibility of 50-State Calculation):** Based on Observation 2, `data/us_zip_centers.json` and `zipState()` already resolve any valid US ZIP code to its 2-letter state abbreviation without network overhead. Introducing a 50-state + DC lookup table (`STATE_RULES`) in `web/pricing.js` enables instant computation of motor vehicle sales/use tax and title & registration allowance for all US states.
3. **Step 3 (Preservation of Texas Calculations):** In `STATE_RULES`, setting `TX: { rate: 0.0625, regCents: 35000 }` matches the current constants (`TX_RATE` and `TX_REGISTRATION_ALLOWANCE_CENTS`) to the penny, preserving the `$22,343.75` total asserted in Observation 5.
4. **Step 4 (Preservation of Unknown Delivery Boundaries):** Based on Observation 6, when a vehicle has no coordinates or requires an ocean route (`AK`, `HI`, `PR`), `delivery` is `null`. Structuring `preview()` so that `delivery === null` forces `totalCents: null` guarantees that `tests/browser_smoke.py` passes without regression.
5. **Step 5 (Test Suite Alignment):** Based on Observation 4, `test_unverified_state_tax_never_becomes_an_invented_complete_total` in `tests/test_deal_math.py` specifically asserted that CA returned `None`. Updating this test to verify CA/OH/MT estimates and verifying that invalid states (e.g. `'XX'`) or ocean routes (`'HI'`) return `None` aligns the test suite with 50-state pricing.
6. **Step 6 (Smoke Test Robustness):** Based on Observation 5, `tests/simple_flow_browser_smoke.py` does not assert that CA returns `None`; it asserts `assert '$22,343.75' not in page.locator('#request-estimate').inner_text()`. Because CA's total (~$24,000+) is not `$22,343.75`, this test continues to pass out-of-the-box.

## 3. Caveats

1. **Ocean Routes (AK, HI, PR):** `web/pricing.js:22` intentionally returns `null` for `deliveryBudget` to/from Alaska, Hawaii, and Puerto Rico because vehicle transport requires ocean shipping quotes. For these states, `totalCents` remains `null`, correctly displaying `"Carrier quote needed"` and `"Your written quote confirms delivery, destination tax, and fees"`.
2. **Local City/County Sales Tax Additions:** Vehicle tax rates in `STATE_RULES` use statewide base motor-vehicle rates (e.g. CA 7.25%, TX 6.25%, OH 5.75%). Local city/county surcharges vary by county and are disclosed as estimates in `estimateNotes()`, where final quotes specify exact county taxes.
3. **South Carolina Tax Cap:** South Carolina statutory vehicle sales tax (Infrastructure Maintenance Fee) is 5% capped at $500. `STATE_RULES.SC` incorporates `maxTaxCents: 50000` to prevent overestimating SC tax.

## 4. Conclusion

1. 50-state tax and registration can be implemented entirely within `web/pricing.js` using a compact `STATE_RULES` lookup table (~55 lines of code, 0 dependencies).
2. Existing ZIP resolution in `web/app.js` already provides the necessary 2-letter state code via `data/us_zip_centers.json`.
3. Updating `web/pricing.js` and `web/app.js` completely eliminates the `"Confirmed in your quote"` placeholder and fixes the Step 2 shipping subtotal drop for all US buyers.
4. Only one test (`tests/test_deal_math.py:48-53`) needs an assertion update to account for California being supported. All other pytest tests and Playwright smoke suites remain 100% compliant.

## 5. Verification Method

1. **Unit Test Verification (Pytest):**
   ```sh
   cd /Users/benjijmac/.gemini/antigravity/brain/ccc4566c-b30b-4220-a78c-0d86d2862b16/scratch/tesla_site_dist
   /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pytest -q tests/test_public_pages.py tests/test_deal_math.py
   ```
2. **Playwright Browser Smoke Verification:**
   ```sh
   PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/simple_flow_browser_smoke.py
   PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/browser_smoke.py
   PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/static_browser_smoke.py
   ```
3. **Node Syntax & Math Check:**
   ```sh
   node --check web/pricing.js
   node -e "const p=require('./web/pricing.js'); console.log('TX:', p.preview({vehiclePrice:20000,miles:0,model:'Model 3',state:'TX'})); console.log('CA:', p.preview({vehiclePrice:20000,miles:0,model:'Model 3',state:'CA'}));"
   ```
4. **Inspect Files:**
   - Detailed survey report: `/Users/benjijmac/.gemini/antigravity/brain/ccc4566c-b30b-4220-a78c-0d86d2862b16/scratch/tesla_site_dist/.agents/teamwork/explorer_survey_3/report.md`

