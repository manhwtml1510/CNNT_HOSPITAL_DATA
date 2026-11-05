from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    actor_user_id: int | None
    actor_username: str | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    ip_address: str | None
    created_at: datetime


class AuditLogPageResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int
