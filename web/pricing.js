'use strict';
// Planning policy, not a carrier rate card or a lender offer.
(function (root) {
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const cents = value => Math.round(value * 100);
  const roundUp50 = amount => Math.ceil(amount / 5000) * 5000;
  const TX_RATE = 0.0625;
  const TX_REGISTRATION_ALLOWANCE_CENTS = 35000;

  function shippingAt(miles, model, roadFactor) {
    if (!finite(miles) || miles < 0 || !['Model 3', 'Model S', 'Model Y', 'Model X'].includes(model)) return null;
    const roadMiles = Math.ceil(miles * roadFactor);
    const vehicleFactor = ['Model Y', 'Model X'].includes(model) ? 1.2 : 1.1;
    const routeBenchmarkCents = Math.max(40000, 25000 + roadMiles * 65);
    const vehicleBenchmarkCents = Math.round(routeBenchmarkCents * vehicleFactor);
    const contingencyCents = Math.max(25000, Math.round(vehicleBenchmarkCents * 0.30));
    return {roadMiles, routeBenchmarkCents, vehicleBenchmarkCents, contingencyCents,
      budgetCents: roundUp50(vehicleBenchmarkCents + contingencyCents)};
  }

  function deliveryBudget(miles, model, destinationState, originState) {
    if (!destinationState || ['AK', 'HI', 'PR'].includes(destinationState) || ['AK', 'HI', 'PR'].includes(originState)) return null;
    const base = shippingAt(miles, model, 1.25);
    if (!base) return null;
    return {...base, lowScenarioCents: shippingAt(miles, model, 1.10).budgetCents,
      highScenarioCents: shippingAt(miles, model, 1.50).budgetCents,
      binding: false, policy: 'open-operable-ev-planning-v1'};
  }

  function loanPayment(totalCents, downCents, aprPercent, termMonths) {
    if (![totalCents, downCents].every(Number.isSafeInteger) || totalCents < 0 || downCents < 0 ||
        !finite(aprPercent) || aprPercent < 0 || aprPercent > 36 || !Number.isInteger(termMonths) || termMonths < 12 || termMonths > 84) return null;
    const principalCents = Math.max(0, totalCents - downCents);
    const rate = aprPercent / 1200;
    const monthlyCents = principalCents === 0 ? 0 : rate === 0 ? Math.round(principalCents / termMonths) :
      Math.round(principalCents * rate / (1 - Math.pow(1 + rate, -termMonths)));
    return {principalCents, monthlyCents, totalPaymentsCents: monthlyCents * termMonths,
      estimatedInterestCents: Math.max(0, monthlyCents * termMonths - principalCents)};
  }

  function preview({vehiclePrice, miles, model, state, originState, downPayment = 3500, apr = 6.5, term = 60}) {
    if (!finite(vehiclePrice) || vehiclePrice <= 0) throw new Error('Vehicle price is unavailable');
    const vehicleCents = cents(vehiclePrice);
    const delivery = deliveryBudget(miles, model, state, originState);
    // Texas preview conservatively treats transport as pre-sale consideration.
    // The written quote classifies the actual delivery and county fees.
    const taxCents = state === 'TX' && delivery ? Math.round((vehicleCents + delivery.budgetCents) * TX_RATE) : null;
    const registrationCents = state === 'TX' ? TX_REGISTRATION_ALLOWANCE_CENTS : null;
    const totalCents = delivery && taxCents !== null ? vehicleCents + delivery.budgetCents + taxCents + registrationCents : null;
    const finance = loanPayment(totalCents ?? vehicleCents, cents(downPayment), apr, term);
    return {vehicleCents, delivery, taxCents, taxRate: state === 'TX' ? TX_RATE : null,
      registrationCents, documentationCents: 0, totalCents, finance,
      financeIncludesEstimatedCosts: totalCents !== null, apr, term, downPaymentCents: cents(downPayment)};
  }

  const api = {deliveryBudget, loanPayment, preview};
  root.VoltsPricing = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
