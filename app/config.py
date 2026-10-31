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
    min_contribution_cents: int = 100000
    retention_days: int = 90

    @property
    def payments_ready(self):
        return bool(self.platform_agreements_verified and self.checkout_enabled and self.stripe_key and self.webhook_secret
                    and (not self.stripe_key.startswith('sk_live_') or self.origin.startswith('https://')))

    @classmethod
    def from_env(cls):
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
            min_contribution_cents=int(os.getenv('MIN_CONTRIBUTION_CENTS', '100000')),
            retention_days=int(os.getenv('REQUEST_RETENTION_DAYS', '90')),
        )
