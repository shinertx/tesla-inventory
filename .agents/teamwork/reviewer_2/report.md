# Integration & Interface Review Report

## Review Summary

**Verdict**: REQUEST_CHANGES

## Findings

### [Critical] Finding 1: Step 3 Post-Submit Screen Retains "YOUR REQUEST" Eyebrow (Integrity Violation / Incomplete Implementation)

- **What**: In `web/app.js:435`, the order modal top eyebrow remains `<p class="eyebrow">YOUR REQUEST</p>` instead of `<p class="eyebrow">YOUR ONLINE ORDER</p>`.
- **Where**: `web/app.js`, Line 435 in `showOrder()`.
- **Why**:
  - `ORIGINAL_REQUEST.md` Item 5 specifically mandates: *"Step 3 Post-Submit Screen Says 'YOUR REQUEST — Your request does not reserve the vehicle' (`showOrder()` in `web/app.js:430`): Right after clicking Start online purchase, the screen reverts to YOUR REQUEST..."*.
  - `PROJECT.md` Feature 4 dictates: *"Update `#order-vehicle-price` and header in `showOrder()` (`web/app.js:430`) to 'YOUR ONLINE ORDER'..."*.
  - `worker_1/handoff.md` Section 1.1 claimed: *"Line 430 (`showOrder()`): Replaced eyebrow with 'YOUR ONLINE ORDER'..."*.
  - Inspection reveals that Worker 1 updated line 314 (`showResumeOrder()`), leaving `showOrder()` on line 435 unchanged with `<p class="eyebrow">YOUR REQUEST</p>`.
  - When a buyer clicks "Start online purchase · $0 today" in Step 2, `showOrder()` executes, reverting the order confirmation screen to broker-era "YOUR REQUEST".
  - This claim in `worker_1/handoff.md` is unverified and contradicts the source code.
- **Suggestion**:
  - In `web/app.js:435`, change:
    ```javascript
    $('order-content').innerHTML=`<p class="eyebrow">YOUR REQUEST</p><h2>${esc(stageNames[order.state]||order.state)}</h2>...
    ```
    to:
    ```javascript
    $('order-content').innerHTML=`<p class="eyebrow">YOUR ONLINE ORDER</p><h2>${esc(stageNames[order.state]||order.state)}</h2>...
    ```
  - Note: Keep `stageNames['requested']` as `'Request received'` because `tests/browser_smoke.py:73` and `tests/customer_functions_browser_smoke.py` assert `Request received` inside `#order-content`. Only the eyebrow text needs correction.

## Verified Claims

- **Zero Broker Phrasing in HTML / Templates**: Verified across `tools/build.py`, `web/index.html`, and all 15,445 public static files. Zero occurrences of *"Dealer confirmation is required before reservation"*, *"selling dealer"*, or *"Unverified / Awaiting Confirmation"*. → **PASS**
- **50-State Out-The-Door Math Parity**: Verified `web/pricing.js` across all 50 states + DC via Node.js evaluation. Accurate tax and registration allowances calculated for continental states. Ocean routes (AK, HI, PR) safely fail closed (`totalCents: null`). → **PASS**
- **Cybertruck Oversize Carrier Safeguard**: Cybertruck correctly returns `delivery: null`, `taxCents: null`, and `totalCents: null`, displaying *"Oversize carrier quote needed"*. → **PASS**
- **Step 2 Pricing Subtotal Visibility**: Non-Texas ZIPs (`90210` CA, `43215` OH) in `paintRequestEstimate()` render the complete Out-the-Door estimate (`$50,278.43` and `$49,505.48`). Delivery subtotal is never omitted. → **PASS**
- **Verification Smoke Suites**:
  - `PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/simple_flow_browser_smoke.py` → **PASS** (0 JS errors)
  - `PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/customer_functions_browser_smoke.py` → **PASS** (0 JS errors)
  - `PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 tests/storefront_controls_browser_smoke.py` → **PASS** (0 JS errors)
  - `PYTHONPATH=tests:. /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m pytest -q tests/test_public_pages.py tests/test_deal_math.py` → **PASS** (15 passed)
  - All 7 additional Playwright smoke suites (`browser_smoke`, `static_browser_smoke`, `checkout_browser_smoke`, `funding_browser_smoke`, `journey_regressions_browser_smoke`, `manual_hold_browser_smoke`, `platform_checkout_browser_smoke`) → **PASS**

## Adversarial Challenge & Stress-Test Results

### Challenge 1: Live Post-Submit Step 3 Confirmation Eyebrow Test
- **Assumption Challenged**: Submitting Step 2 opens an order screen titled "YOUR ONLINE ORDER".
- **Attack Scenario**: Buyer enters ZIP `90210`, fills out name/email/phone, clicks "Start online purchase · $0 today", and inspects `#order-content .eyebrow`.
- **Actual Behavior**: Renders `<p class="eyebrow">YOUR REQUEST</p>`.
- **Blast Radius**: Buyer perceives the purchase as a broker request rather than a direct dealer order. Fails Item 5 of the original user prompt.
- **Mitigation**: Update line 435 in `web/app.js` to `<p class="eyebrow">YOUR ONLINE ORDER</p>`.

### Challenge 2: State Tax Input Boundary & Sanitization
- **Assumption Challenged**: Non-standard state inputs (lowercase `ca`, invalid code `XX`, null, numbers) must not cause runtime crashes or false total calculations.
- **Result**: `web/pricing.js` sanitizes string input via `toUpperCase()`. Supported lowercase inputs calculate correctly; invalid inputs (`XX`, `null`, `123`) safely return `taxCents: null` and `totalCents: null`. → **PASS**

## Coverage Gaps
- None. All 50 states + DC, invalid inputs, and all 10 smoke suites were exercised.

## Unverified Items
- None. All claims were verified via direct code inspection and automated execution.
