"""Exercise money arithmetic and unsupported-route behavior through the shipped JS module."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def js(expression):
    result = subprocess.run(
        ['node', '-e', "const p=require('./web/pricing.js');console.log(JSON.stringify(" + expression + '));'],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def test_delivery_budget_grows_with_distance_instead_of_dropping_at_tiers():
    rows = js("[0,100,499,500,501,999,1000,1001,1500,2000,2500].map(m=>p.deliveryBudget(m,'Model Y','TX').budgetCents)")
    assert rows == sorted(rows)
    assert rows[1] == 75000
    assert rows[3] == 105000
    assert rows[6] == 170000
    assert rows[9] == 295000


def test_delivery_has_no_invented_price_for_oversize_or_ocean_routes():
    assert js("p.deliveryBudget(1000,'Cybertruck','TX')") is None
    assert js("p.deliveryBudget(1000,'Model Y','HI')") is None
    for state in ('AK', 'HI', 'PR'):
        assert js("p.deliveryBudget(1000,'Model Y','TX'," + json.dumps(state) + ")") is None
        assert js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'TX',originState:" + json.dumps(state) + "})")['totalCents'] is None
    assert js("p.deliveryBudget(null,'Model Y','TX')") is None
    assert js("p.deliveryBudget(-1,'Model 3','TX')") is None


def test_texas_preview_reconciles_to_cents_and_includes_ev_fee_allowance():
    result = js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'TX',downPayment:5000,apr:6.5,term:60})")
    assert result['delivery']['budgetCents'] == 105000
    assert result['taxCents'] == 225313  # 6.25% of $36,050; conservative pre-sale delivery basis.
    assert result['registrationCents'] == 35000
    assert result['documentationCents'] == 0
    assert result['totalCents'] == 3865313
    assert result['totalCents'] == result['vehicleCents'] + result['delivery']['budgetCents'] + result['taxCents'] + result['registrationCents']
    assert result['finance']['principalCents'] == 3365313  # Down payment once; no phantom $250 credit.
    assert result['finance']['monthlyCents'] == 65846


def test_unverified_state_tax_never_becomes_an_invented_complete_total():
    result = js("p.preview({vehiclePrice:35000,miles:500,model:'Model Y',state:'CA'})")
    assert result['taxCents'] is None
    assert result['totalCents'] is None
    assert result['financeIncludesEstimatedCosts'] is False


def test_zero_interest_and_paid_in_full_never_produce_nan_or_negative_payments():
    assert js('p.loanPayment(3000000,0,0,60)')['monthlyCents'] == 50000
    assert js('p.loanPayment(3000000,4000000,6.5,72)')['monthlyCents'] == 0
    assert js('p.loanPayment(3000000,-1,6.5,72)') is None
    assert js('p.loanPayment(3000000,0,6.5,0)') is None


def test_longer_term_reduces_payment_but_raises_total_interest():
    result = js('[60,72].map(term=>p.loanPayment(3000000,0,6.5,term))')
    assert result[0]['monthlyCents'] > result[1]['monthlyCents']
    assert result[0]['estimatedInterestCents'] < result[1]['estimatedInterestCents']


def test_route_sensitivity_bounds_the_budget_and_suv_allowance_exceeds_sedan():
    result = js("['Model 3','Model Y'].map(model=>p.deliveryBudget(1000,model,'TX'))")
    assert result[0]['budgetCents'] < result[1]['budgetCents']
    for row in result:
        assert row['lowScenarioCents'] <= row['budgetCents'] <= row['highScenarioCents']
        assert row['contingencyCents'] >= 25000
        assert row['binding'] is False
