from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / '.data/orders.db'
    inventory_path: Path = ROOT / 'inventory.json'
    sourcing_path: Path = ROOT / '.data/source_snapshot.json'
    origin: str = 'http://127.0.0.1:8000'
    admin_token: str = ''
    platform_agreements_verified: bool = False
    supported_states: tuple[str, ...] = ()
    checkout_enabled: bool = False
    stripe_key: str = ''
    webhook_secret: str = ''
    stripe_publishable_key: str = ''
    checkout_ui_mode: str = 'embedded_page'
    payment_method_types: tuple[str, ...] = ('card',)
    balance_payment_method_types: tuple[str, ...] = ('us_bank_account',)
    min_contribution_cents: int = 100000
    retention_days: int = 90
    sandbox_mode: bool = False

    @property
    def is_test_sandbox(self):
        return bool(self.sandbox_mode and not self.stripe_key.startswith('sk_live_'))

    @property
    def agreements_gate_passed(self):
        return bool(self.platform_agreements_verified or (self.is_test_sandbox and self.stripe_key.startswith('sk_test_')))

    @property
    def payments_ready(self):
        return bool(self.agreements_gate_passed and self.checkout_enabled and self.stripe_key and self.webhook_secret
                    and self.stripe_key.startswith(('sk_test_','sk_live_'))
                    and self.checkout_ui_mode in ('embedded_page','hosted_page')
                    and self.payment_method_types and set(self.payment_method_types)<={'card','us_bank_account'}
                    and self.balance_payment_method_types and set(self.balance_payment_method_types)<={'us_bank_account'}
                    and (self.checkout_ui_mode=='hosted_page' or (
                        self.stripe_publishable_key.startswith('pk_live_' if self.stripe_key.startswith('sk_live_') else 'pk_test_')))
                    and (not self.stripe_key.startswith('sk_live_') or (self.origin.startswith('https://') and self.platform_agreements_verified)))

    @classmethod
    def from_env(cls):
        methods = tuple(x.strip() for x in os.getenv('STRIPE_PAYMENT_METHODS', 'card').split(',') if x.strip())
        return cls(
            db_path=Path(os.getenv('ORDERS_DB', str(ROOT / '.data/orders.db'))),
            inventory_path=Path(os.getenv('INVENTORY_JSON', str(ROOT / 'inventory.json'))),
            sourcing_path=Path(os.getenv('SOURCING_JSON',str(ROOT/'.data/source_snapshot.json'))),
            origin=os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8000').rstrip('/'),
            admin_token=os.getenv('ADMIN_TOKEN', ''),
            platform_agreements_verified=os.getenv('PLATFORM_AGREEMENTS_VERIFIED','').lower()=='true',
            supported_states=tuple(x.strip().upper() for x in os.getenv('SUPPORTED_STATES', '').split(',') if x.strip()),
            checkout_enabled=os.getenv('CHECKOUT_ENABLED', '').lower() == 'true',
            stripe_key=os.getenv('STRIPE_SECRET_KEY', ''), webhook_secret=os.getenv('STRIPE_WEBHOOK_SECRET', ''),
            stripe_publishable_key=os.getenv('STRIPE_PUBLISHABLE_KEY',''),
            checkout_ui_mode=os.getenv('CHECKOUT_UI_MODE','embedded_page'),
            payment_method_types=methods or ('card',),
            min_contribution_cents=int(os.getenv('MIN_CONTRIBUTION_CENTS', '100000')),
            retention_days=int(os.getenv('REQUEST_RETENTION_DAYS', '90')),
            sandbox_mode=os.getenv('SANDBOX_MODE', '').lower() == 'true',
        )
