import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.core.file_storage import ALLOWED_DEPARTMENTS
from app.models import BackupJob


ARCHIVE_FORMAT_VERSION = 1
_MANIFEST_NAME = "manifest.json"
_DATABASE_NAME = "database.sql"
_ARCHIVE_NAME = re.compile(r"^hospital-(?:backup|safety)-\d+-[0-9a-f-]+\.zip$")
_OPERATION_LOCK_NAME = "hospital_data_backup_restore"


class BackupOperationError(Exception):
    """An expected backup/restore failure safe to show to an operator."""


@contextmanager
def backup_operation_lock():
    lock_connection = engine.connect()
    try:
        acquired = lock_connection.execute(
            text("SELECT GET_LOCK(:lock_name, 0)"),
            {"lock_name": _OPERATION_LOCK_NAME},
        ).scalar_one_or_none()
        lock_connection.commit()
    except Exception as exc:
        lock_connection.rollback()
        lock_connection.close()
        raise BackupOperationError("Could not check whether a backup or restore is already running.") from exc

    if acquired != 1:
        lock_connection.close()
        raise BackupOperationError("A backup or restore is already running. Retry this operation shortly.")

    try:
        yield
    finally:
        try:
            released = lock_connection.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": _OPERATION_LOCK_NAME},
            ).scalar_one_or_none()
            lock_connection.commit()
            if released != 1:
                raise BackupOperationError("The backup/restore lock could not be released cleanly.")
        except Exception as exc:
            lock_connection.rollback()
            lock_connection.invalidate()
            if isinstance(exc, BackupOperationError):
                raise
            raise BackupOperationError("The backup/restore lock could not be released cleanly.") from exc
        finally:
            lock_connection.close()


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _backup_root() -> Path:
    root = Path(settings.backup_root).resolve()
    storage = Path(settings.storage_root).resolve()
    if root == storage or root.is_relative_to(storage):
        raise BackupOperationError("Backup folder must not be inside the medical-file storage folder.")
    if root == root.parent:
        raise BackupOperationError("Backup folder cannot be a drive or filesystem root.")
    return root


def _resolve_mysql_tool(configured: str, executable: str) -> str:
    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())

    located = shutil.which(configured)
    if located:
        return located

    if os.name == "nt":
        common_path = Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin") / executable
        if common_path.is_file():
            return str(common_path)

    raise BackupOperationError(
        f"MySQL client tool '{executable}' was not found. Set its path in the backend environment."
    )


def _option_value(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _create_mysql_defaults_file() -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".hospital-mysql-", suffix=".cnf")
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("[client]\n")
            stream.write(f"host={_option_value(settings.db_host)}\n")
            stream.write(f"port={settings.db_port}\n")
            stream.write(f"user={_option_value(settings.db_user)}\n")
            stream.write(f"password={_option_value(settings.db_password)}\n")
        if os.name != "nt":
            path.chmod(0o600)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _remove_defaults_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise BackupOperationError(
            "Temporary MySQL credentials could not be deleted; restrict the backend temporary directory."
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_dump(database_file: Path) -> None:
    tool = _resolve_mysql_tool(settings.mysqldump_path, "mysqldump.exe" if os.name == "nt" else "mysqldump")
    defaults_file = _create_mysql_defaults_file()
    command = [
        tool,
        f"--defaults-extra-file={defaults_file}",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--events",
        "--hex-blob",
        "--no-tablespaces",
        "--set-gtid-purged=OFF",
        f"--ignore-table={settings.db_name}.backup_jobs",
        "--databases",
        settings.db_name,
    ]
    try:
        with database_file.open("xb") as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            database_file.unlink(missing_ok=True)
            raise BackupOperationError(
                f"MySQL database export failed (exit code {result.returncode}). Check database access and MySQL privileges."
            )
        if database_file.stat().st_size == 0:
            raise BackupOperationError("MySQL database export returned an empty file.")
    except OSError as exc:
        database_file.unlink(missing_ok=True)
        if isinstance(exc, FileNotFoundError):
            raise BackupOperationError("MySQL database export could not start. Check the configured mysqldump path.") from exc
        raise BackupOperationError("MySQL database export could not write its temporary file.") from exc
    finally:
        _remove_defaults_file(defaults_file)


def _storage_files(storage_root: Path):
    if not storage_root.exists():
        return

    if storage_root.is_symlink() or not storage_root.is_dir():
        raise BackupOperationError(
            "Medical-file storage must be a regular directory."
        )

    for department in sorted(ALLOWED_DEPARTMENTS):
        department_path = storage_root / department

        # Phòng ban chưa có file thì không cần tạo thư mục.
        if not department_path.exists():
            continue

        if department_path.is_symlink() or not department_path.is_dir():
            raise BackupOperationError(
                f"Invalid medical department directory: {department}"
            )

        for current, directories, filenames in os.walk(
            department_path,
            followlinks=False,
        ):
            current_path = Path(current)

            # Không cho phép symbolic link trong vùng lưu trữ.
            for directory in directories:
                directory_path = current_path / directory

                if directory_path.is_symlink():
                    raise BackupOperationError(
                        "Medical-file storage contains a symbolic link; "
                        "backup stopped."
                    )

            # File phải nằm trực tiếp trong thư mục phòng ban.
            if current_path != department_path:
                raise BackupOperationError(
                    f"Nested directories are not supported in "
                    f"department storage: {department}"
                )

            for filename in filenames:
                file_path = current_path / filename

                if file_path.is_symlink() or not file_path.is_file():
                    raise BackupOperationError(
                        "Medical-file storage contains a non-regular "
                        "file; backup stopped."
                    )

                if re.fullmatch(r"[a-f0-9]{32}", filename) is None:
                    raise BackupOperationError(
                        f"Invalid medical storage key in department "
                        f"{department}: {filename}"
                    )

                yield file_path


def _build_archive(job_id: int, job_type: str, root: Path) -> tuple[Path, int, str]:
    root.mkdir(parents=True, exist_ok=True)
    storage_root = Path(settings.storage_root).resolve()
    with tempfile.TemporaryDirectory(prefix=f".backup-{job_id}-", dir=root) as working_name:
        working = Path(working_name)
        database_file = working / _DATABASE_NAME
        _run_dump(database_file)

        entries: dict[str, dict[str, object]] = {
            _DATABASE_NAME: {
                "sha256": _sha256_file(database_file),
                "size_bytes": database_file.stat().st_size,
            }
        }
        final_name = f"hospital-{ 'safety' if job_type == 'safety_backup' else 'backup'}-{job_id}-{uuid.uuid4().hex}.zip"
        final_path = root / final_name
        temporary_path = working / "archive.zip"
        try:
            with zipfile.ZipFile(
                temporary_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as archive:
                archive.write(database_file, _DATABASE_NAME)
                for file_path in _storage_files(storage_root) or ():
                    relative = file_path.relative_to(storage_root)
                    archive_name = f"files/{relative.as_posix()}"
                    if not _safe_archive_member(archive_name):
                        raise BackupOperationError(
                            "Medical-file storage contains a file outside the supported department storage layout."
                        )
                    entries[archive_name] = {
                        "sha256": _sha256_file(file_path),
                        "size_bytes": file_path.stat().st_size,
                    }
                    archive.write(file_path, archive_name)

                manifest = {
                    "format_version": ARCHIVE_FORMAT_VERSION,
                    "database": settings.db_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "entries": entries,
                }
                archive.writestr(
                    _MANIFEST_NAME,
                    json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                )
            os.replace(temporary_path, final_path)
        except Exception:
            final_path.unlink(missing_ok=True)
            raise

    return final_path, final_path.stat().st_size, _sha256_file(final_path)


def _set_job_failed(db: Session, job_id: int, message: str) -> BackupJob:
    db.rollback()
    job = db.get(BackupJob, job_id)
    if job is None:
        raise BackupOperationError("Backup job state could not be saved.")
    job.status = "failed"
    job.finished_at = _now_naive_utc()
    job.message = message[:500]
    db.commit()
    db.refresh(job)
    return job


def _create_job(db: Session, job_type: str, destination: str | None = None) -> BackupJob:
    job = BackupJob(job_type=job_type, status="running", started_at=_now_naive_utc())
    job.destination = destination
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _create_backup_locked(db: Session, job: BackupJob) -> BackupJob:
    try:
        root = _backup_root()
        root.mkdir(parents=True, exist_ok=True)
        destination, size_bytes, checksum = _build_archive(job.id, job.job_type, root)
        job.status = "success"
        job.finished_at = _now_naive_utc()
        job.destination = str(destination)
        job.bytes_total = size_bytes
        job.checksum = checksum
        job.message = None
        db.commit()
        db.refresh(job)
        return job
    except BackupOperationError as exc:
        return _set_job_failed(db, job.id, str(exc))
    except Exception:
        return _set_job_failed(db, job.id, "Backup failed due to an unexpected server error.")


def create_backup(db: Session, job_type: str = "backup") -> BackupJob:
    if job_type not in {"backup", "safety_backup"}:
        raise ValueError("Unsupported backup job type")

    job = _create_job(db, job_type)
    try:
        with backup_operation_lock():
            return _create_backup_locked(db, job)
    except BackupOperationError as exc:
        return _set_job_failed(db, job.id, str(exc))


def _resolve_archive(job: BackupJob, root: Path) -> Path:
    if job.job_type not in {"backup", "safety_backup"} or job.status != "success":
        raise BackupOperationError("The selected backup is not available for restore.")
    if not job.destination or not job.checksum:
        raise BackupOperationError("The selected backup is missing archive metadata.")
    raw_path = Path(job.destination)
    if raw_path.is_symlink():
        raise BackupOperationError("The selected backup archive is not available.")
    path = raw_path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise BackupOperationError("The selected backup archive is not available.")
    if not _ARCHIVE_NAME.fullmatch(path.name):
        raise BackupOperationError("The selected backup archive has an invalid name.")
    expected_kind = "safety" if job.job_type == "safety_backup" else "backup"
    if not path.name.startswith(f"hospital-{expected_kind}-{job.id}-"):
        raise BackupOperationError("The selected backup archive does not match its job.")
    if _sha256_file(path) != job.checksum:
        raise BackupOperationError("The selected backup archive checksum does not match.")
    return path


def _safe_archive_member(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    raw_parts = name.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in raw_parts):
        return False
    path = PurePosixPath(name)
    if path.is_absolute():
        return False
    if name == _DATABASE_NAME or name == _MANIFEST_NAME:
        return True
    return len(path.parts) == 3 and path.parts[0] == "files" and path.parts[1] in ALLOWED_DEPARTMENTS and re.fullmatch(r"[a-f0-9]{32}", path.parts[2]) is not None


def _validate_and_stage_archive(
    archive_path: Path,
    expected_checksum: str,
    staging_root: Path,
) -> tuple[Path, Path]:
    if _sha256_file(archive_path) != expected_checksum:
        raise BackupOperationError("The selected backup archive checksum does not match.")

    database_path = staging_root / _DATABASE_NAME
    files_path = staging_root / "files"
    files_path.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info in archive.infolist():
                name = info.filename
                if info.is_dir() or not _safe_archive_member(name) or name in seen:
                    raise BackupOperationError("Backup archive contains an unsupported or unsafe entry.")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise BackupOperationError("Backup archive contains a symbolic link.")
                seen.add(name)

            if _MANIFEST_NAME not in seen or _DATABASE_NAME not in seen:
                raise BackupOperationError("Backup archive is missing its manifest or database dump.")
            manifest = json.loads(archive.read(_MANIFEST_NAME))
            if not isinstance(manifest, dict):
                raise BackupOperationError("Backup archive manifest is invalid.")
            if manifest.get("format_version") != ARCHIVE_FORMAT_VERSION or manifest.get("database") != settings.db_name:
                raise BackupOperationError("Backup archive format or database does not match this installation.")
            entries = manifest.get("entries")
            if not isinstance(entries, dict) or set(entries) != seen - {_MANIFEST_NAME}:
                raise BackupOperationError("Backup archive manifest does not match its contents.")

            for name, metadata in entries.items():
                expected_hash = metadata.get("sha256") if isinstance(metadata, dict) else None
                if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
                    raise BackupOperationError("Backup archive manifest has invalid checksum metadata.")
                source = archive.open(name, "r")
                if name == _DATABASE_NAME:
                    destination = database_path
                else:
                    destination = files_path.joinpath(*PurePosixPath(name).parts[1:])
                    destination.parent.mkdir(parents=True, exist_ok=True)

                digest = hashlib.sha256()
                size = 0
                with source, destination.open("xb") as output:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                        output.write(chunk)
                if digest.hexdigest() != expected_hash or size != metadata.get("size_bytes"):
                    raise BackupOperationError("A backup archive entry failed integrity validation.")
    except BackupOperationError:
        raise
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise BackupOperationError("Backup archive is damaged or unreadable.") from exc

    if not database_path.is_file() or database_path.stat().st_size == 0:
        raise BackupOperationError("Backup archive contains an empty database dump.")
    return database_path, files_path


def _import_database(database_file: Path) -> None:
    tool = _resolve_mysql_tool(settings.mysql_path, "mysql.exe" if os.name == "nt" else "mysql")
    defaults_file = _create_mysql_defaults_file()
    command = [tool, f"--defaults-extra-file={defaults_file}", "--binary-mode", settings.db_name]
    try:
        with database_file.open("rb") as source:
            result = subprocess.run(command, stdin=source, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise BackupOperationError(
                f"MySQL database restore failed (exit code {result.returncode}). The safety backup will be reapplied."
            )
    except OSError as exc:
        raise BackupOperationError("MySQL database restore could not start. Check the configured mysql path.") from exc
    finally:
        _remove_defaults_file(defaults_file)


def _replace_storage_tree(staged_files: Path) -> None:
    storage_root = Path(settings.storage_root)
    if storage_root.is_symlink():
        raise BackupOperationError("Configured medical-file storage cannot be a symbolic link.")
    storage_root = storage_root.resolve()
    if storage_root == storage_root.parent:
        raise BackupOperationError("Configured medical-file storage cannot be a drive or filesystem root.")

    parent = storage_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    incoming = parent / f".{storage_root.name}.restore-new-{uuid.uuid4().hex}"
    previous = parent / f".{storage_root.name}.restore-old-{uuid.uuid4().hex}"
    had_previous = storage_root.exists()
    try:
        shutil.copytree(staged_files, incoming)
        if had_previous:
            storage_root.rename(previous)
        try:
            incoming.rename(storage_root)
        except Exception:
            if had_previous and previous.exists():
                previous.rename(storage_root)
            raise
    except Exception as exc:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)
        if had_previous and previous.exists() and not storage_root.exists():
            try:
                previous.rename(storage_root)
            except OSError as restore_exc:
                raise BackupOperationError(
                    "Medical-file storage could not be replaced or restored to its previous directory."
                ) from restore_exc
        if isinstance(exc, BackupOperationError):
            raise
        raise BackupOperationError("Medical-file storage could not be replaced.") from exc

    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)


def _apply_archive(archive_path: Path, expected_checksum: str, root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix=".restore-stage-", dir=root) as staging_name:
        database_file, staged_files = _validate_and_stage_archive(
            archive_path,
            expected_checksum,
            Path(staging_name),
        )
        _import_database(database_file)
        _replace_storage_tree(staged_files)


def _record_restore_failure(db: Session, job_id: int, message: str) -> BackupJob:
    return _set_job_failed(db, job_id, message)


def _restore_locked(db: Session, backup_job_id: int, job: BackupJob) -> BackupJob:
    safety_job: BackupJob | None = None
    try:
        root = _backup_root()
        root.mkdir(parents=True, exist_ok=True)
        safety_job = _create_backup_locked(db, _create_job(db, "safety_backup"))
        if safety_job.status != "success":
            raise BackupOperationError("A pre-restore safety backup could not be created; restore was cancelled.")

        selected = db.scalar(select(BackupJob).where(BackupJob.id == backup_job_id))
        if selected is None:
            raise BackupOperationError("The selected backup was not found.")
        selected_path = _resolve_archive(selected, root)
        _apply_archive(selected_path, selected.checksum or "", root)

        job.status = "success"
        job.finished_at = _now_naive_utc()
        job.message = f"Restored successfully. Safety backup job #{safety_job.id}."
        db.commit()
        db.refresh(job)
        return job
    except BackupOperationError as exc:
        message = str(exc)
    except Exception:
        message = "Restore failed due to an unexpected server error."

    if safety_job and safety_job.status == "success" and safety_job.destination and safety_job.checksum:
        try:
            root = _backup_root()
            safety_path = _resolve_archive(safety_job, root)
            _apply_archive(safety_path, safety_job.checksum, root)
        except Exception:
            message = "Restore failed and automatic rollback also failed. Manual recovery is required."

    return _record_restore_failure(db, job.id, message)


def restore_backup(db: Session, backup_job_id: int, confirm: bool) -> BackupJob:
    if confirm is not True:
        raise BackupOperationError("Explicit confirmation is required before restoring a backup.")

    selected = db.scalar(select(BackupJob).where(BackupJob.id == backup_job_id))
    if selected is None:
        raise BackupOperationError("The selected backup was not found.")
    job = _create_job(db, "restore", destination=selected.destination)

    try:
        with backup_operation_lock():
            return _restore_locked(db, backup_job_id, job)
    except BackupOperationError as exc:
        return _record_restore_failure(db, job.id, str(exc))
    except Exception:
        return _record_restore_failure(db, job.id, "Restore failed due to an unexpected server error.")


def backup_job_public_data(job: BackupJob) -> dict[str, object]:
    destination_name = None
    archive_available = False
    if job.destination:
        raw_path = Path(job.destination)
        destination_name = raw_path.name
        try:
            root = _backup_root()
            path = raw_path.resolve()
            archive_available = (
                job.status == "success"
                and bool(job.checksum)
                and path.is_relative_to(root)
                and not raw_path.is_symlink()
                and path.is_file()
                and bool(_ARCHIVE_NAME.fullmatch(path.name))
            )
        except (OSError, BackupOperationError):
            archive_available = False

    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "destination": destination_name,
        "archive_available": archive_available,
        "bytes_total": job.bytes_total,
        "checksum": job.checksum,
        "message": job.message,
        "created_at": job.created_at,
    }
