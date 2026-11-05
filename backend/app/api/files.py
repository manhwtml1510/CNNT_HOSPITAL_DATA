from uuid import uuid4
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.dependencies import reject_during_backup_or_restore, require_permission
from app.core.file_storage import (
    calculate_sha256,
    get_department_directory,
    get_file_path,
    read_and_validate_upload,
    save_file,
)
from app.models import MedicalRecord, StoredFile, User
from app.api.records import scope_records_to_user


router = APIRouter(prefix="/files", tags=["Stored Files"])


@router.post("/records/{record_id}", status_code=201)
async def upload_file(
    record_id: int,
    request: Request,
    upload: UploadFile = File(...),
    db: Session = Depends(get_db),
    _maintenance: None = Depends(reject_during_backup_or_restore),
    user: User = Depends(require_permission("files:upload")),
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
            action="files.upload",
            resource_type="medical_record",
            resource_id=str(record_id),
            outcome="denied_or_not_found",
        )
        raise HTTPException(
            status_code=404,
            detail="Medical record not found",
        )

    content, filename, mime_type, checksum = (
        await read_and_validate_upload(upload)
    )

    directory = get_department_directory(record.department)
    storage_key = uuid4().hex
    file_path = directory / storage_key

    try:
        save_file(file_path, content)

        stored_file = StoredFile(
            record_id=record.id,
            original_filename=filename,
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=checksum,
            uploaded_by_id=user.id,
        )

        db.add(stored_file)
        db.commit()
        db.refresh(stored_file)

    except Exception:
        db.rollback()

        if file_path.exists():
            file_path.unlink()

        raise

    record_audit(
        db,
        request,
        actor_user_id=user.id,
        action="files.upload",
        resource_type="stored_file",
        resource_id=str(stored_file.id),
        outcome="success",
    )

    await upload.close()

    return {
        "id": stored_file.id,
        "record_id": stored_file.record_id,
        "original_filename": stored_file.original_filename,
        "size_bytes": stored_file.size_bytes,
        "sha256": stored_file.sha256,
        "created_at": stored_file.created_at,
    }


@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("files:download")),
):
    stored_file = db.scalar(
        select(StoredFile).where(StoredFile.id == file_id)
    )

    if stored_file is None:
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    statement = select(MedicalRecord).where(
        MedicalRecord.id == stored_file.record_id
    )
    statement = scope_records_to_user(statement, user)
    record = db.scalar(statement)

    if record is None:
        record_audit(
            db,
            request,
            actor_user_id=user.id,
            action="files.download",
            resource_type="stored_file",
            resource_id=str(file_id),
            outcome="denied_or_not_found",
        )
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    file_path = get_file_path(
        record.department,
        stored_file.storage_key,
    )

    if not file_path.is_file():
        record_audit(
            db,
            request,
            actor_user_id=user.id,
            action="files.download",
            resource_type="stored_file",
            resource_id=str(file_id),
            outcome="failure",
        )
        raise HTTPException(
            status_code=404,
            detail="Stored file is missing",
        )

    actual_checksum = calculate_sha256(file_path)

    if actual_checksum != stored_file.sha256:
        record_audit(
            db,
            request,
            actor_user_id=user.id,
            action="files.download",
            resource_type="stored_file",
            resource_id=str(file_id),
            outcome="integrity_failure",
        )
        raise HTTPException(
            status_code=409,
            detail="File integrity check failed",
        )

    record_audit(
        db,
        request,
        actor_user_id=user.id,
        action="files.download",
        resource_type="stored_file",
        resource_id=str(file_id),
        outcome="success",
    )

    safe_filename = Path(
        stored_file.original_filename
    ).name.replace("\r", "").replace("\n", "")

    return FileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=safe_filename,
    )
