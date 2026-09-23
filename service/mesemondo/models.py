from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool

UUID = Annotated[str, Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
Secret = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{43}$')]
Integer = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')

class ChallengeRequest(Model):
    device_id: UUID
class Challenge(ChallengeRequest):
    challenge_id: UUID
    nonce: Secret
    expires_at: Integer
    audience: Literal['mm02-dev','mm02-prod']
class SessionRequest(Model):
    challenge_id: UUID
    signature: Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{512}$')]
class Session(Model):
    access_token: Secret
    expires_at: Integer
    device_id: UUID
class CatalogItem(Model):
    content_id: UUID
    title: str
    description: str
    price_minor: Integer
    currency: Literal['HUF']
class Catalog(Model):
    items: list[CatalogItem]
    next_cursor: str | None
class Entitlement(Model):
    content_id: UUID
    grant_id: UUID
    issued_at: Integer
class Entitlements(Model):
    items: list[Entitlement]
    next_cursor: str | None
class FileURL(Model):
    file_id: UUID
    url: str
    expires_at: Integer
class FirmwareDelivery(Model):
    manifest_jws: str
    files: list[FileURL]
class Delivery(FirmwareDelivery):
    license_jws: str
class OrderRequest(Model):
    content_ids: Annotated[list[UUID], Field(min_length=1,max_length=32)]
class OrderCreated(Model):
    order_id: UUID
    checkout_url: str
class OrderStatus(Model):
    order_id: UUID
    status: Literal['pending','paid','failed','cancelled']
    expires_at: Integer
class RecoveryRequest(Model):
    rotate: StrictBool
class Recovery(Model):
    recovery_key: Secret
class TransferRequest(Model):
    source_device_id: UUID
    source_access_token: Secret | None = None
    recovery_key: Secret | None = None
class PaymentEvent(Model):
    event_id: UUID
    order_id: UUID
    merchant: Annotated[str, Field(min_length=1,max_length=128)]
    amount_minor: Integer
    currency: Literal['HUF']
    status: Literal['paid','failed','cancelled']
class Accepted(Model):
    accepted: bool
class Health(Model):
    status: str
class ErrorInfo(Model):
    code: str
    message: str
class Error(Model):
    error: ErrorInfo
    request_id: str
