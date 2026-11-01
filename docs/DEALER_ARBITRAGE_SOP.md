# Volts & VINs — Invisible Back-to-Back Wholesale Arbitrage SOP

## Core Commercial Rule
The retail customer deals **100% with Volts & VINs** (and the disclosed licensed retail dealer of record). The original source dealership is **never** exposed to the customer on the website, quote, bill of sale, or delivery paperwork.

---

## 1. Day-1 Core Stack (Zero Fluff — Only What Closes Deals)

1. **Licensed Retail Seller (`TxDMV GDN`)**
   - **Weeks 1–4 (Bridge):** Licensed Texas Partner Dealership executes the wholesale purchase from the source dealer and the retail sale to the Volts & VINs buyer for a flat `$350/car` clearing fee.
   - **Week 4+ (Permanent):** Volts & VINs LLC holds its own Texas Independent Motor Vehicle Dealer License (`GDN`) + `TxDMV webDEALER` account.

2. **Checkout & Payments (`Stripe`)**
   - `$250` refundable reservation via Stripe Embedded Checkout (`app/payments.py`).
   - Remaining balance via Stripe Financial Connections (ACH wire/debit) or lender proceeds wire.

3. **Financing (`700Credit` + `Origence CUDL` / `AutoFi`)**
   - Soft-pull credit check (`700Credit`) + multi-lender credit union & prime bank routing (`Origence CUDL` / `AutoFi` in `app/providers.py`).
   - Lender wires funded proceeds directly to the retail dealer account; Volts & VINs captures the `$600–$1,200` dealer reserve.

4. **Blind Carrier Transport (`Super Dispatch` / `RunBuggy` / `Central Dispatch`)**
   - Customer pays the distance-band shipping rate (`$200` / `$590` / `$790` / `$1,090` / `$1,390` — includes `+$200` safety buffer).
   - Carrier is dispatched on a **Blind eBOL** (`Super Dispatch` / `RunBuggy` in `app/providers.py`):
     - **Pickup Contact:** Source dealer wholesale/fleet manager (carrier is instructed: *"Pickup for wholesale buyer; do not hand source-dealer invoice or marketing materials to recipient"*).
     - **Delivery Contact:** Retail customer address with Volts & VINs digital delivery checklist.

---

## 2. Step-by-Step Deal Execution Sequence (Per Vehicle)

1. **Buyer Submits Quote Request (`$0` today)** on `voltsandvins.com` for a target VIN.
2. **Wholesale Desk Confirms Source VIN (`< 30 mins`):**
   - Look up the source dealer in private `.data/source_snapshot.json` / `.data/arbitrage_opportunities.json`.
   - Call/text source dealer wholesale desk: confirm VIN is on the lot, clean title in hand, and lock wholesale net price (`agreed_dealer_net_cents`) + 48-hour dealer hold.
3. **Publish Written Quote to Buyer:**
   - Issue the quote via `tools/dealer_ops.py` with retail price, state tax, `$285` title/reg, and shipping (`$200–$1,390`).
4. **Buyer Pays `$250` Deposit & Completes Balance / Financing:**
   - Buyer pays `$250` on `voltsandvins.com`, signs the retail buyer's order, and completes ACH balance or lender funding.
5. **Back-to-Back Wholesale Purchase & Blind Dispatch:**
   - Wire wholesale net price to source dealer; receive signed wholesale title reassignment.
   - Dispatch carrier via **Super Dispatch / RunBuggy** on a blind eBOL directly from the source lot to the customer's driveway.
   - Issue Texas buyer e-tag via `TxDMV webDEALER` and file retail title transfer.
