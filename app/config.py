from dataclasses import dataclass
from pathlib import Path
import os
import re

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
    balance_checkout_enabled: bool = False
    stripe_key: str = ''
    deposit_collection_mode: str = 'dealer_direct'
    stripe_platform_account: str = ''
    platform_collection_legal_name: str = ''
    webhook_secret: str = ''
    stripe_publishable_key: str = ''
    checkout_ui_mode: str = 'embedded_page'
    payment_method_types: tuple[str, ...] = ('card',)
    balance_payment_method_types: tuple[str, ...] = ('us_bank_account',)
    min_contribution_cents: int = 100000
    retention_days: int = 90
    sandbox_mode: bool = False
    auto_refund_enabled: bool = False
    super_dispatch_api_key: str = ''
    shipping_estimates_enabled: bool = False

    @property
    def stripe_mode(self):
        """Classify account secret/restricted keys; never treat unknown keys as TEST."""
        if not isinstance(self.stripe_key,str) or any(c.isspace() for c in self.stripe_key):return None
        for mode in ('test','live'):
            for kind in ('sk','rk'):
                prefix=f'{kind}_{mode}_'
                if self.stripe_key.startswith(prefix) and len(self.stripe_key)>len(prefix):return mode
        return None

    @property
    def is_test_sandbox(self):
        return bool(self.sandbox_mode and self.stripe_mode=='test')

    @property
    def publishable_key_matches_mode(self):
        prefix=f'pk_{self.stripe_mode}_'
        return bool(self.stripe_mode in ('test','live') and isinstance(self.stripe_publishable_key,str)
                    and self.stripe_publishable_key.startswith(prefix) and len(self.stripe_publishable_key)>len(prefix)
                    and not any(c.isspace() for c in self.stripe_publishable_key))

    @property
    def agreements_gate_passed(self):
        return bool(self.platform_agreements_verified or self.is_test_sandbox)

    @property
    def valid_platform_account(self):
        return bool(isinstance(self.stripe_platform_account,str) and re.fullmatch(r'acct_[A-Za-z0-9]+',self.stripe_platform_account))

    @property
    def collection_ready(self):
        return bool(self.deposit_collection_mode=='dealer_direct' or (
            self.deposit_collection_mode=='platform' and self.valid_platform_account
            and isinstance(self.platform_collection_legal_name,str) and len(self.platform_collection_legal_name.strip())>=3
            and self.platform_agreements_verified))

    @property
    def payments_ready(self):
        return bool(self.collection_ready and self.agreements_gate_passed and self.checkout_enabled and self.stripe_key and self.webhook_secret
                    and self.stripe_mode in ('test','live')
                    and (not self.sandbox_mode or self.stripe_mode=='test')
                    and self.checkout_ui_mode in ('embedded_page','hosted_page')
                    and self.payment_method_types and set(self.payment_method_types)<={'card','us_bank_account'}
                    and (self.checkout_ui_mode=='hosted_page' or self.publishable_key_matches_mode)
                    and (self.stripe_mode!='live' or (self.origin.startswith('https://') and self.platform_agreements_verified)))

    @property
    def balance_payments_ready(self):
        return bool(self.deposit_collection_mode=='dealer_direct' and self.balance_checkout_enabled and self.payments_ready
                    and self.balance_payment_method_types
                    and set(self.balance_payment_method_types)<={'us_bank_account'})

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
            balance_checkout_enabled=os.getenv('BALANCE_CHECKOUT_ENABLED', '').lower() == 'true',
            deposit_collection_mode=os.getenv('DEPOSIT_COLLECTION_MODE', 'dealer_direct'),
            stripe_platform_account=os.getenv('STRIPE_PLATFORM_ACCOUNT', ''),
            platform_collection_legal_name=os.getenv('PLATFORM_COLLECTION_LEGAL_NAME', '').strip(),
            stripe_key=os.getenv('STRIPE_SECRET_KEY', ''), webhook_secret=os.getenv('STRIPE_WEBHOOK_SECRET', ''),
            stripe_publishable_key=os.getenv('STRIPE_PUBLISHABLE_KEY',''),
            checkout_ui_mode=os.getenv('CHECKOUT_UI_MODE','embedded_page'),
            payment_method_types=methods or ('card',),
            min_contribution_cents=int(os.getenv('MIN_CONTRIBUTION_CENTS', '100000')),
            retention_days=int(os.getenv('REQUEST_RETENTION_DAYS', '90')),
            sandbox_mode=os.getenv('SANDBOX_MODE', '').lower() == 'true',
            auto_refund_enabled=os.getenv('AUTO_REFUND_ENABLED', 'true').lower() == 'true',
            super_dispatch_api_key=os.getenv('SUPER_DISPATCH_API_KEY',''),
            shipping_estimates_enabled=os.getenv('SHIPPING_ESTIMATES_ENABLED','').lower()=='true',
        )
