from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: UUID
    organization_id: UUID | None
    actor_user_id: UUID | None
    action: str
    target_type: str
    target_id: str
    extra: dict
    created_at: datetime

    model_config = {"from_attributes": True}
