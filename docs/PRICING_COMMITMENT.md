# Vehicle price and complete purchase quote

The storefront shows a vehicle price. Delivery, tax, title and registration stay separate until the selling dealer confirms them.

## Price rule

New requests save the server catalog vehicle price, exact catalog revision and comparison snapshot. The browser submits its displayed price for a consistency check. A changed price requires review before request creation.

The quoted vehicle price cannot exceed the saved request price. Lower prices are allowed. If the vehicle cannot be supplied profitably at that price, cancel the unavailable request. Do not hide a vehicle-price increase in delivery or other fees. Any replacement vehicle needs the buyer's agreement and its own request.

A request does not reserve inventory or guarantee availability. A confirmed seller hold, approved complete quote and accepted terms still precede the $250 deposit.

Historical requests without a saved price have no invented guarantee. Their existing explicit quote and acceptance flow remains available.

## Comparison and margin

Pricing remains deterministic and keeps uncapped modeled spread. This release does not change prices or the pricing algorithm. Peer asking-price comparisons are estimates, not sold-price proof. New private requests retain their original comparison basis after catalog changes.

## Payment readiness

The existing JENNi account is owned by JENNI PRO INC. Ben confirmed Volts & VINs is its brand. Live credentials are installed, but customer checkout remains disabled.

Production checkout remains disabled without a real licensed seller, agreed terms, eligible payment access and actual vehicle evidence. Jockey remains a draft label. Financing, carrier booking and full-photo feeds still require authorized provider or dealer access. Vendor inquiries remain drafts.


## Delivery budget and loan arithmetic

The storefront estimates open transport for operable Model 3, S, Y, and X vehicles. Cybertruck and ocean routes need actual carrier quotes.

Planning policy:

- Approximate road miles equal straight-line miles multiplied by 1.25, rounded up.
- Route benchmark equals the greater of $400 or $250 plus $0.65 per approximate road mile.
- The planning multiplier is 1.10 for sedans and 1.20 for SUVs.
- Add the greater of $250 or 30% of that vehicle-adjusted benchmark.
- Round the final delivery budget up to $50.

These are commercial planning assumptions. They are not negotiated carrier payables, Carvana rates, or guaranteed customer delivery charges.

Public transport benchmarks informed this conservative budget. They do not establish our actual costs.
Sources checked November 2, 2026: [Montway](https://www.montway.com/how-much-does-it-cost-ship-car) and [Sherpa](https://www.sherpaautotransport.com/guides/car-shipping-cost/).

[Carvana](https://www.carvana.com/help/pickup-and-delivery/whats-the-difference-between-shipping-and-delivery-fees) prices shipping by vehicle and destination. No universal Carvana mileage rate is used.
A lower-price comparison requires an actual comparable vehicle and destination quote. Vehicle benchmarks never imply lower shipping or a lower delivered total.

Texas previews use 6.25% motor-vehicle tax. They conservatively include the delivery budget in taxable consideration.
A $350 title/registration allowance includes room for EV registration fees. The documentation fee preview is zero.
The written quote determines actual transport classification, county charges, and seller fees.
Other destinations show vehicle and delivery subtotals until a verified vehicle-tax quote exists. No generic 6% fallback applies.

Sources: [Texas motor-vehicle tax](https://comptroller.texas.gov/taxes/motor-vehicle/sales-use.php), [taxable consideration](https://comptroller.texas.gov/taxes/publications/96-254/total-consideration.php), and [EV registration](https://www.txdmv.gov/motorists/register-your-vehicle).

All totals use integer cents. Monthly payments use the amortization formula and the buyer's selected illustrative APR and term.
The down payment is deducted once. An uncaptured $250 hold never reduces loan principal, settled funding, or the purchase balance.
Only a verified collected deposit receives credit. Calculator results are not credit decisions or locked rates.
