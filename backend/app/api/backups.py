from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.backup import BackupOperationError, backup_job_public_data, create_backup, restore_backup
from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models import BackupJob, User
from app.schemas.backups import BackupJobPageResponse, BackupJobResponse, RestoreRequest


router = APIRouter(prefix="/backups", tags=["Backups and Restore"])


def _actor_after_restore(db: Session, actor_id: int) -> int | None:
    db.expire_all()
    return db.scalar(select(User.id).where(User.id == actor_id))


@router.get("", response_model=BackupJobPageResponse)
def list_backup_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("backup:read")),
):
    total = db.scalar(select(func.count()).select_from(BackupJob)) or 0
    jobs = db.scalars(
        select(BackupJob)
        .order_by(BackupJob.created_at.desc(), BackupJob.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return BackupJobPageResponse(
        items=[BackupJobResponse(**backup_job_public_data(job)) for job in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=BackupJobResponse)
def run_backup(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("backup:execute")),
):
    job = create_backup(db, "backup")
    record_audit(
        db,
        request,
        actor_user_id=user.id,
        action="backup.create",
        resource_type="backup_job",
        resource_id=str(job.id),
        outcome="success" if job.status == "success" else "failure",
    )
    return BackupJobResponse(**backup_job_public_data(job))


@router.post("/{backup_job_id}/restore", response_model=BackupJobResponse)
def run_restore(
    backup_job_id: int,
    body: RestoreRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("restore:execute")),
):
    selected = db.get(BackupJob, backup_job_id)
    if selected is None or selected.job_type not in {"backup", "safety_backup"}:
        raise HTTPException(status_code=404, detail="Backup archive not found")
    if selected.status != "success" or not selected.destination:
        raise HTTPException(status_code=409, detail="Backup archive is not available for restore")

    try:
        job = restore_backup(
            db,
            backup_job_id,
            body.confirm,
            restore_quarantine=body.restore_quarantine,
            restore_application_logs=body.restore_application_logs,
        )
    except BackupOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    actor_id = _actor_after_restore(db, user.id)
    record_audit(
        db,
        request,
        actor_user_id=actor_id,
        action="backup.restore",
        resource_type="backup_job",
        resource_id=str(backup_job_id),
        outcome="success" if job.status == "success" else "failure",
    )
    return BackupJobResponse(**backup_job_public_data(job))
