from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models import AuditLog, User
from app.schemas.audit import AuditLogPageResponse, AuditLogResponse


router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("", response_model=AuditLogPageResponse)
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, min_length=1, max_length=100),
    outcome: str | None = Query(default=None, min_length=1, max_length=30),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("audit:read")),
):
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if outcome:
        filters.append(AuditLog.outcome == outcome)

    total = db.scalar(
        select(func.count()).select_from(AuditLog).where(*filters)
    ) or 0
    rows = db.execute(
        select(AuditLog, User.username)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        AuditLogResponse(
            id=log.id,
            actor_user_id=log.actor_user_id,
            actor_username=username,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            outcome=log.outcome,
            ip_address=log.ip_address,
            created_at=log.created_at,
        )
        for log, username in rows
    ]
    return AuditLogPageResponse(items=items, total=total, limit=limit, offset=offset)
