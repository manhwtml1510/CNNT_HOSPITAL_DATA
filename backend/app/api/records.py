
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    require_permission,
)
from app.models import MedicalRecord, User
from app.schemas.records import MedicalRecordResponse


router = APIRouter(prefix="/records", tags=["Medical Records"])


def is_system_admin(user: User) -> bool:
    return any(role.code == "system_admin" for role in user.roles)


def scope_records_to_user(statement, user: User):

    if is_system_admin(user):
        return statement

    if not user.department:
        # Không có phạm vi được gán thì mặc định không có dữ liệu.
        return statement.where(MedicalRecord.id == -1)

    return statement.where(
        MedicalRecord.department == user.department
    )


@router.get("", response_model=list[MedicalRecordResponse])
def list_records(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("records:read")),
):
    statement = (
        select(MedicalRecord)
        .order_by(MedicalRecord.id.desc())
        .limit(limit)
        .offset(offset)
    )
    statement = scope_records_to_user(statement, user)
    records = list(db.scalars(statement).all())

    record_audit(
        db,
        request,
        actor_user_id=user.id,
        action="records.list",
        resource_type="medical_record",
        resource_id=None,
        outcome="success",
    )

    return records


@router.get("/{record_id}", response_model=MedicalRecordResponse)
def get_record(
    record_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("records:read")),
):
    statement = select(MedicalRecord).where(
        MedicalRecord.id == record_id
    )
    statement = scope_records_to_user(statement, user)

    record = db.scalar(statement)

    if record is None:
        record_audit(
            db,
            request,
            actor_user_id=user.id,
            action="records.read",
            resource_type="medical_record",
            resource_id=str(record_id),
            outcome="denied_or_not_found",
        )

        # Không tiết lộ hồ sơ có tồn tại nhưng thuộc khoa khác hay không.
        raise HTTPException(
            status_code=404,
            detail="Medical record not found",
        )

    record_audit(
        db,
        request,
        actor_user_id=user.id,
        action="records.read",
        resource_type="medical_record",
        resource_id=str(record.id),
        outcome="success",
    )

    return record
