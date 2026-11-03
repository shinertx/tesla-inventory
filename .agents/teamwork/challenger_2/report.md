⚠️ [SIMULATION / MOCK DATA] (Local test runner with fixture catalog and mock api routes)

# Empirical Challenge Report: Browser Flow & UI Verification

## Challenge Summary

**Overall risk assessment**: MEDIUM

Automated browser smoke suites passed cleanly. However, empirical verification of user interaction flows revealed an unfulfilled requirement and false claim in Worker 1 handoff.

---

## Challenges

### [Medium] Challenge 1: Step 3 Post-Submit Screen Eyebrow Still Displays "YOUR REQUEST"

- **Assumption challenged**: Worker 1 claimed `showOrder()` was updated to display `"YOUR ONLINE ORDER"`.
- **Attack scenario**: Buyer completes Step 2 online purchase and clicks `Start online purchase · $0 today`. The app navigates to Step 3 (`#order-dialog`). The browser renders `<p class="eyebrow">YOUR REQUEST</p>` at the top of `#order-content`.
- **Observation / Blast radius**:
  - `web/app.js:435` still renders `<p class="eyebrow">YOUR REQUEST</p>`.
  - Worker 1 only updated `renderRecoverOrder()` at line 315.
  - The initial post-submit order screen still labels an active online purchase as a "request".
  - This contradicts the dealer purchase flow requirement and user prompt specifications.
- **Mitigation**: Update `web/app.js:435` from `<p class="eyebrow">YOUR REQUEST</p>` to `<p class="eyebrow">YOUR ONLINE ORDER</p>`.

---

## Stress Test Results

### 1. Step 2 Shipping Subtotal & Out-the-Door Pricing Across States

| ZIP | State | Request Estimate Display | SubNote | Status |
|---|---|---|---|---|
| `90210` | CA | `Estimated total` **$50,278.43** | Includes estimated delivery to 90210, state tax & registration. | ✅ PASS |
| `43215` | OH | `Estimated total` **$49,505.48** | Includes estimated delivery to 43215, state tax & registration. | ✅ PASS |
| `78201` | TX | `Estimated total` **$49,788.13** | Includes estimated delivery to 78201, state tax & registration. | ✅ PASS |

- **Bare price confusion**: No instances of bare vehicle price (`$45,830.00 + delivery, tax & fees`) above `Includes estimated delivery`.
- **Total vs. Subtotal**: Displays complete Out-the-Door estimate for all tested US states.

### 2. Vehicle Modal Copy Verification

- Verified `#vehicle-dialog` top summary, `tab-details`, and `tab-pricing`.
- Zero occurrences of:
  - `"Unverified"`
  - `"Awaiting Confirmation"`
  - `"Availability to be confirmed"`
  - `"History not yet verified"`
  - `"Request this vehicle price or lower"`
  - `"Dealer confirmation is required"`
- Correctly displays Texacars direct inventory copy, HW4/HW3 screen photo verification, and clean title guarantee.

### 3. Step 2 Button & Checkbox Interaction

- Checkbox text verified: `"I authorize Texacars to process my online purchase and order details."`
- Initial button label: `"Start online purchase · $0 today"`
- In-flight submission state: Button changes to `"Processing order…"`, button is disabled, dialog navigation controls are disabled.
- Post-submit reset: Handled properly in finally block.

### 4. Step 3 Post-Submit Screen Verification

- `#order-vehicle-price` line items verified:
  - Vehicle price: `$45,830.00 or lower`
  - Estimated delivery: `$700.00`
  - Motor-vehicle tax estimate: verified integer cents
  - Title & registration allowance: verified integer cents
  - Estimated total: verified matching sum
- Disclaimers removed: `"Your request does not reserve the vehicle"` is completely absent.
- Dealer branding: `"selling dealer"` is absent; `"Texacars"` is used consistently.
- **Eyebrow verification**: ❌ **FAIL**. Eyebrow renders `"YOUR REQUEST"`, not `"YOUR ONLINE ORDER"`.

### 5. Automated Browser Test Suites

- `tests/simple_flow_browser_smoke.py`:
  - Desktop (1440px) & Mobile (390px) viewports: PASSED (exit code 0)
  - `javascript_errors`: `[]`
- `tests/browser_smoke.py`:
  - Uvicorn backend + Playwright headless browser: PASSED (exit code 0)
  - 36 initial cards, filters, savings sort, deal estimator, durable order creation, photo gallery: PASSED
  - `javascript_errors`: `[]`

---

## Unchallenged Areas

- Live third-party ACH balance clearing (mocked by design in local fixtures).
- Live Stripe webhook event processing (mocked by design in local fixtures).
