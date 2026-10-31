import json
import time
import uuid

import stripe
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


VIN = "7SAYGDEE0TEST0001"
TOKEN = "operator-test-only-" + "x" * 40
ACCOUNT = "acct_1TQUJJRpS98C9h2R"


def quote_body():
    now = int(time.time())
    refs = {
        key: "evidence:test-document"
        for key in [
            "supplier_commitment_reference",
            "spread_agreement_reference",
            "seller_hold_reference",
            "title_history_reference",
            "lien_payoff_reference",
            "inspection_reference",
            "equipment_reference",
            "recall_reference",
            "tax_quote_reference",
            "carrier_quote_reference",
        ]
    }
    refs.update(
        {
            key: "https://example.test/terms/" + key
            for key in [
                "buyers_guide_reference",
                "warranty_terms_reference",
                "return_terms_reference",
                "deposit_terms_reference",
            ]
        }
    )
    return dict(
        dealer_id="synthetic-sandbox-dealer",
        dealer_vehicle_net_cents=2500000,
        vehicle_price_cents=2900000,
        tax_cents=181250,
        title_registration_cents=15000,
        documentation_cents=0,
        delivery_charge_cents=60000,
        demand_cost_cents=30000,
        platform_service_cost_cents=35000,
        platform_risk_reserve_cents=50000,
        platform_payment_cost_cents=15000,
        other_platform_cost_cents=0,
        seller_hold_until=now + 7200,
        valid_until=now + 3600,
        title_status="clean_verified",
        condition_status="accepted",
        recall_disposition="clear",
        **refs,
    )


def test_real_stripe_sdk_objects_normalize_across_deposit_and_refund(tmp_path, monkeypatch):
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"items": [{"vin": VIN}]}))
    settings = Settings(
        db_path=tmp_path / "orders.db",
        inventory_path=inv,
        admin_token=TOKEN,
        platform_agreements_verified=False,
        sandbox_mode=True,
        supported_states=("TX",),
        checkout_enabled=True,
        stripe_key="sk_test_fixture",
        stripe_publishable_key="pk_test_fixture",
        webhook_secret="whsec_fixture",
    )
    client = TestClient(create_app(settings))
    admin = {"Authorization": "Bearer " + TOKEN}
    dealer = dict(
        id="synthetic-sandbox-dealer",
        legal_name="SYNTHETIC SANDBOX DEALER (TEST ONLY)",
        license_number="TEST-SANDBOX-ONLY",
        address="100 Sandbox Test Way, Austin, TX 78701",
        supported_states=["TX"],
        stripe_account=ACCOUNT,
        agreement_reference="sandbox:test-only-dealer-agreement",
        license_evidence="sandbox:test-only-license",
        verified=True,
    )
    assert client.put("/api/admin/dealers/synthetic-sandbox-dealer", json=dealer, headers=admin).status_code == 200
    created = client.post(
        "/api/requests",
        json=dict(vin=VIN, name="Test Buyer", email="buyer@example.test", state="TX", zip="78701", consent=True),
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201
    order = created.json()
    auth = {"Authorization": "Bearer " + order["access_token"]}
    assert client.post(f"/api/admin/orders/{order['id']}/quote", json=quote_body(), headers=admin).status_code == 200

    session_obj = stripe.checkout.Session.construct_from(
        {
            "id": "cs_test_sdk_shape",
            "object": "checkout.session",
            "client_secret": "cs_test_sdk_shape_secret_123",
            "status": "open",
            "payment_status": "paid",
            "amount_total": 25000,
            "currency": "usd",
            "mode": "payment",
            "livemode": False,
            "payment_intent": "pi_test_sdk_shape",
            "metadata": {"order_id": order["id"], "quote_version": "1", "payment_stage": "deposit"},
        },
        "sk_test_fixture",
    )
    monkeypatch.setattr(
        stripe.Account,
        "retrieve",
        lambda *a, **k: stripe.Account.construct_from(
            {"id": ACCOUNT, "object": "account", "charges_enabled": True, "details_submitted": True},
            "sk_test_fixture",
        ),
    )
    monkeypatch.setattr(stripe.checkout.Session, "create", lambda *a, **k: session_obj)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", lambda *a, **k: session_obj)
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda *a, **k: stripe.Event.construct_from(
            {
                "id": "evt_test_sdk_shape",
                "object": "event",
                "type": "checkout.session.completed",
                "account": ACCOUNT,
                "data": {"object": {"id": "cs_test_sdk_shape", "object": "checkout.session"}},
            },
            "sk_test_fixture",
        ),
    )
    monkeypatch.setattr(
        stripe.Refund,
        "create",
        lambda *a, **k: stripe.Refund.construct_from(
            {
                "id": "re_test_sdk_shape",
                "object": "refund",
                "amount": 25000,
                "payment_intent": "pi_test_sdk_shape",
                "status": "succeeded",
            },
            "sk_test_fixture",
        ),
    )

    checkout = client.post(
        f"/api/orders/{order['id']}/checkout",
        json={"quote_version": 1, "terms_accepted": True},
        headers=auth,
    )
    assert checkout.status_code == 200
    assert checkout.json()["client_secret"] == "cs_test_sdk_shape_secret_123"

    webhook = client.post(
        "/api/stripe/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fixture"},
    )
    assert webhook.status_code == 200
    assert client.get(f"/api/orders/{order['id']}", headers=auth).json()["state"] == "deposit_paid"

    cancelled = client.post(
        f"/api/orders/{order['id']}/cancel",
        json={"reason": "Customer requested cancellation"},
        headers=auth,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "refund_pending"

    refunded = client.post(f"/api/admin/orders/{order['id']}/refund", json={}, headers=admin)
    assert refunded.status_code == 200
    assert refunded.json()["state"] == "refunded"
