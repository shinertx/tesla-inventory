# Volts & VINs — "Better Than Carvana" Provider & Onboarding Stack

## Why `Engine + Montway` Are Only Bridges (Not the Best Stack)

1. **Why Montway is NOT the best for transport:**
   - Montway is a **retail auto-transport broker** that adds `$250–$400/car` in broker fees and reposts the load to a carrier load board.
   - **What beats Carvana & Montway:** **`Super Dispatch` (`superdispatch.com`) + `RunBuggy` (`runbuggy.com`) + `Central Dispatch`**.
     - Direct API to 20,000+ verified carriers with **$0 broker markup**.
     - Instant algorithmic lane pricing (`Super Dispatch Pricing Insights API` / `RunBuggy Quotes API`) plus your `+$200` shipping margin buffer.
     - **Digital photo eBOL (Electronic Bill of Lading)** at pickup/drop-off + **Uber-style live GPS map link** for the customer.

2. **Why Engine by MoneyLion is NOT the best for financing:**
   - Engine is a general fintech lead-gen marketplace (`moneylion.com`). It cannot structure a VIN-specific retail installment contract or pay you full automotive dealer reserve (`$600–$1,200/car`).
   - **What beats Carvana:** **`AutoFi` (`autofi.com`) + `700Credit` (Soft-Pull) + `CUDL` (Credit Union Direct Lending)**.
     - Carvana pushes buyers into its high-APR in-house subprime lender (`Bridgecrest` at `9%–16%` APR).
     - **AutoFi + CUDL + 700Credit** pits **40+ credit unions and prime auto lenders** (PenFed, Navy Federal, Capital One Auto, Ally, Chase) against each other inside your checkout.
     - Result: Buyers get **`1.5%–3.0%` lower APR** (`~$80/mo` lower payment than Carvana on the same Tesla), and lenders pay Volts & VINs **`+$600–$1,200` dealer reserve per car**.

3. **Why Carvana Loses on Title & Registration (And How We Beat Them):**
   - Carvana is notorious for 60–90 day title/registration delays.
   - **What beats Carvana:** **`Vitu` (`vitu.com`) / `ATC` (`autotitle.com`)** (or **`Caramel` (`drivecaramel.com`)** prior to your Texas GDN license clearing) for exact 50-state county tax/title calculation, instant electronic temp tags, and digital DMV filing.

---

## Side-by-Side Comparison: Carvana vs. Volts & VINs Best-in-Class Stack

| Layer | Carvana Stack | Earlier Bridge (`Engine + Montway`) | **Volts & VINs "Beat Carvana" Stack** | Customer & Margin Advantage |
| :--- | :--- | :--- | :--- | :--- |
| **Inventory & Price** | ~1,200 Teslas (heavy recon/vending overhead) | 15,097 Teslas | **15,097 VIN-Verified Teslas + Peer Benchmark Savings** | **12x more Teslas**, `$500–$4,000` below peer benchmark |
| **Financing** | Bridgecrest in-house high APR (`9%–16%`) | Engine generic lead-gen offers | **`700Credit` Soft-Pull + `AutoFi` + `CUDL` (Credit Unions + Prime Banks)** | **`1.5%–3%` lower APR for buyer** + **`+$600–$1,200` dealer reserve** to you |
| **Transport & Tracking** | Fleet trucks (limited routes) | Montway retail broker (`+$300` middleman fee) | **`RunBuggy` + `Super Dispatch` API + `Central Dispatch`** | **0 broker fee**, digital photo eBOL inspection, **live GPS map link**, **`+$200–$400` shipping margin** |
| **Deposit & Balance Pay** | Legacy bank portal | Stripe Checkout | **`Stripe Embedded Checkout` (`$250`) + `Stripe Financial Connections` (Instant Plaid ACH)** | 1-click `$250` hold + instant verified bank balance settlement |
| **Title, Tax & Temp Tags** | Manual back-office (frequent delays) | Manual dealer paperwork | **`Caramel` (Bridge) → `Vitu` 50-State Digital DMV + `TxDMV webDEALER`** | Exact county tax/title to the penny + instant e-tag |

---

## Environment Variables Wired in `app/providers.py`

Once credentials are issued for any of the providers above, set on `hank.jockeyvc.com`:

```bash
# 1. Live Stripe Deposit & ACH Balance Checkout
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
CHECKOUT_ENABLED=true
PLATFORM_AGREEMENTS_VERIFIED=true

# 2. Direct Carrier Transport API (Super Dispatch or RunBuggy — $0 broker fee + $200 safety buffer)
SUPER_DISPATCH_API_KEY=...
RUNBUGGY_API_TOKEN=...

# 3. Embedded Auto Lending API (AutoFi + 700Credit / CUDL)
AUTOFI_API_KEY=...
AUTOFI_DEALER_CODE=...
```
