"""Provider boundary. Production providers must implement original-body verification."""
import hashlib
import hmac
from typing import Protocol
from .crypto import strict_json
from .models import PaymentEvent

class Provider(Protocol):
    name: str
    def verify(self, body: bytes, timestamp: str, signature: str, now: int) -> PaymentEvent: ...

class TestProvider:
    name = 'test'
    def __init__(self, key):
        if len(key) < 32:
            raise ValueError('Webhook key must have at least 256 bits')
        self.key = key

    def signature(self, body, timestamp):
        return hmac.new(self.key, timestamp.encode()+b'.'+body, hashlib.sha256).hexdigest()

    def verify(self, body, timestamp, signature, now):
        if not timestamp.isdigit() or abs(now-int(timestamp)) > 300 or not hmac.compare_digest(self.signature(body,timestamp), signature):
            raise ValueError('Invalid webhook authentication')
        return PaymentEvent.model_validate(strict_json(body))
