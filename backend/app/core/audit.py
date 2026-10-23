from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog

def record_audit(
    db: Session,
    request: Request,
    *,
    actor_user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
) -> None:

    ip_address = request.client.host if request.client else None

    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            ip_address=ip_address,
        )
    )


    db.commit()
