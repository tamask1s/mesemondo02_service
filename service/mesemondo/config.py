import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class Settings:
    profile: str
    database_url: str
    storage: Path
    public_base: str
    manifest_key: Path
    license_key: Path
    manifest_kid: str
    license_kid: str
    trusted_keys: Path
    replay_key: Path
    webhook_key: Path
    merchant: str = 'mesemondo-test'
    test_payments: bool = False
    secure_boot_public_key: Path | None = None

    @property
    def root_path(self):
        return urlsplit(self.public_base).path.removesuffix('/api/v1/')

    @property
    def audience(self):
        return 'mm02-dev' if self.profile == 'dev' else 'mm02-prod'

    def validate(self):
        u = urlsplit(self.public_base)
        if self.profile not in ('dev', 'production') or u.scheme != 'https' or not u.netloc or u.query or u.fragment or u.username or not u.path.endswith('/api/v1/'):
            raise ValueError('Invalid profile or HTTPS public_base')
        if self.profile == 'production' and self.test_payments:
            raise ValueError('Test payments forbidden in production')
        for p in (self.storage, self.manifest_key, self.license_key, self.trusted_keys, self.replay_key, self.webhook_key):
            if not p.is_absolute() or p.resolve().is_relative_to(ROOT):
                raise ValueError('Runtime files and secrets must be outside the repository')
        return self

    @classmethod
    def load(cls):
        p = Path(os.environ['MM02_CONFIG'])
        d = json.loads(p.read_text())
        for name in ('storage','manifest_key','license_key','trusted_keys','replay_key','webhook_key','secure_boot_public_key'):
            if d.get(name):
                d[name] = Path(d[name])
        return cls(**d).validate()
