'use strict';
// Planning policy, not a carrier rate card or a lender offer.
(function (root) {
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const cents = value => Math.round(value * 100);
  const roundUp50 = amount => Math.ceil(amount / 5000) * 5000;
  const TX_RATE = 0.0625;
  const TX_REGISTRATION_ALLOWANCE_CENTS = 35000;
  const STATE_RULES = {
    AL: { rate: 0.02, regCents: 16500 },
    AK: { rate: 0.00, regCents: 20000 },
    AZ: { rate: 0.056, regCents: 35000 },
    AR: { rate: 0.065, regCents: 15000 },
    CA: { rate: 0.0725, regCents: 37500 },
    CO: { rate: 0.029, regCents: 35000 },
    CT: { rate: 0.0635, regCents: 25000 },
    DE: { rate: 0.0425, regCents: 15000 },
    DC: { rate: 0.06, regCents: 25000 },
    FL: { rate: 0.06, regCents: 35000 },
    GA: { rate: 0.066, regCents: 15000 },
    HI: { rate: 0.04, regCents: 25000 },
    ID: { rate: 0.06, regCents: 20000 },
    IL: { rate: 0.0625, regCents: 35000 },
    IN: { rate: 0.07, regCents: 25000 },
    IA: { rate: 0.05, regCents: 25000 },
    KS: { rate: 0.065, regCents: 20000 },
    KY: { rate: 0.06, regCents: 15000 },
    LA: { rate: 0.0445, regCents: 25000 },
    ME: { rate: 0.055, regCents: 20000 },
    MD: { rate: 0.06, regCents: 30000 },
    MA: { rate: 0.0625, regCents: 25000 },
    MI: { rate: 0.06, regCents: 30000 },
    MN: { rate: 0.06875, regCents: 25000 },
    MS: { rate: 0.05, regCents: 25000 },
    MO: { rate: 0.04225, regCents: 20000 },
    MT: { rate: 0.00, regCents: 30000 },
    NE: { rate: 0.055, regCents: 25000 },
    NV: { rate: 0.0685, regCents: 35000 },
    NH: { rate: 0.00, regCents: 25000 },
    NJ: { rate: 0.033125, regCents: 30000 },
    NM: { rate: 0.04, regCents: 15000 },
    NY: { rate: 0.04, regCents: 30000 },
    NC: { rate: 0.03, regCents: 25000 },
    ND: { rate: 0.05, regCents: 20000 },
    OH: { rate: 0.0575, regCents: 30000 },
    OK: { rate: 0.0325, regCents: 20000 },
    OR: { rate: 0.005, regCents: 30000 },
    PA: { rate: 0.06, regCents: 25000 },
    RI: { rate: 0.07, regCents: 25000 },
    SC: { rate: 0.05, regCents: 15000, maxTaxCents: 50000 },
    SD: { rate: 0.04, regCents: 15000 },
    TN: { rate: 0.07, regCents: 25000 },
    TX: { rate: TX_RATE, regCents: TX_REGISTRATION_ALLOWANCE_CENTS },
    UT: { rate: 0.0685, regCents: 25000 },
    VT: { rate: 0.06, regCents: 20000 },
    VA: { rate: 0.0415, regCents: 25000 },
    WA: { rate: 0.065, regCents: 35000 },
    WV: { rate: 0.06, regCents: 20000 },
    WI: { rate: 0.05, regCents: 25000 },
    WY: { rate: 0.04, regCents: 25000 }
  };

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
    const stateCode = state && typeof state === 'string' ? state.toUpperCase() : '';
    const rule = STATE_RULES[stateCode] || null;
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
      taxState: rule ? stateCode : null,
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

  const api = {deliveryBudget, loanPayment, preview};
  root.VoltsPricing = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
