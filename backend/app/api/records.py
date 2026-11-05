from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.dependencies import (
    get_current_user,
    reject_during_backup_or_restore,
    require_permission,
)
from app.models import MedicalRecord, User
from app.schemas.records import (
    MedicalRecordCreateRequest,
    MedicalRecordResponse,
    MedicalRecordUpdateRequest,
)


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


@router.post("", response_model=MedicalRecordResponse, status_code=201)
def create_record(
    payload: MedicalRecordCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    _maintenance: None = Depends(reject_during_backup_or_restore),
    user: User = Depends(require_permission("records:create")),
):
    # Người dùng thông thường chỉ được tạo hồ sơ trong khoa của mình.
    if not is_system_admin(user) and payload.department != user.department:
        record_audit(
            db,
            request,
            actor_user_id=user.id,
            action="records.create",
            resource_type="medical_record",
            resource_id=payload.record_number,
            outcome="denied",
        )
        raise HTTPException(
            status_code=403,
            detail="You cannot create records for another department",
        )

    record = MedicalRecord(
        record_number=payload.record_number,
        patient_code=payload.patient_code,
        title=payload.title,
        department=payload.department,
        status="active",
        created_by_id=user.id,
    )

    db.add(record)

    try:
        db.commit()
        db.refresh(record)
    except IntegrityError:
        db.rollback()
        record_audit(
            db,
            request,
            actor_user_id=user.id,
            action="records.create",
            resource_type="medical_record",
            resource_id=payload.record_number,
            outcome="failure",
        )
        raise HTTPException(
            status_code=409,
            detail="Record number already exists or data violates a database constraint",
        )

    record_audit(
        db,
        request,
        actor_user_id=user.id,
        action="records.create",
        resource_type="medical_record",
        resource_id=str(record.id),
        outcome="success",
    )
    return record


@router.patch("/{record_id}", response_model=MedicalRecordResponse)
def update_record(
    record_id: int,
    payload: MedicalRecordUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    _maintenance: None = Depends(reject_during_backup_or_restore),
    user: User = Depends(require_permission("records:update")),
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
            action="records.update",
            resource_type="medical_record",
            resource_id=str(record_id),
            outcome="denied_or_not_found",
        )
        raise HTTPException(
            status_code=404,
            detail="Medical record not found",
        )

    record.title = payload.title
    record.status = payload.status
    db.commit()
    db.refresh(record)

    record_audit(
        db,
        request,
        actor_user_id=user.id,
        action="records.update",
        resource_type="medical_record",
        resource_id=str(record.id),
        outcome="success",
    )
    return record
