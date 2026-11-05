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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.core.file_storage import ALLOWED_DEPARTMENTS
from app.models import BackupJob


ARCHIVE_FORMAT_VERSION = 2
_MANIFEST_NAME = "metadata/manifest.json"
_LEGACY_MANIFEST_NAME = "manifest.json"
_DATABASE_NAME = "database.sql"
_BACKUP_METADATA_NAME = "logs/backup_metadata.json"
_DEPARTMENT_NAMES = tuple(sorted(ALLOWED_DEPARTMENTS))
_ARCHIVE_NAME = re.compile(r"^hospital-(?:backup|safety)-\d+(?:-[0-9a-f-]+)?\.zip$")
_OPERATION_LOCK_NAME = "hospital_data_backup_restore"


class BackupOperationError(Exception):
    """An expected backup/restore failure safe to show to an operator."""


@dataclass(frozen=True)
class StagedArchive:
    database_file: Path
    departments_root: Path
    quarantine_root: Path
    application_logs_root: Path


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


def _create_mysql_defaults_file(
    user: str | None = None,
    password: str | None = None,
) -> Path:
    mysql_user = settings.db_user if user is None else user
    mysql_password = settings.db_password if password is None else password
    descriptor, name = tempfile.mkstemp(prefix=".hospital-mysql-", suffix=".cnf")
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("[client]\n")
            stream.write(f"host={_option_value(settings.db_host)}\n")
            stream.write(f"port={settings.db_port}\n")
            stream.write(f"user={_option_value(mysql_user)}\n")
            stream.write(f"password={_option_value(mysql_password)}\n")
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


def _raise_storage_walk_error(exc: OSError) -> None:
    raise BackupOperationError(
        "Medical-file storage could not be fully read; backup stopped."
    ) from exc


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _component_entries(
    component_root: Path,
    archive_prefix: str,
    *,
    department: str | None = None,
):
    if component_root.exists() and (
        _is_link_or_junction(component_root) or not component_root.is_dir()
    ):
        raise BackupOperationError(
            f"Configured backup component is not a regular directory: {archive_prefix}"
        )

    yield f"{archive_prefix}/", component_root if component_root.exists() else None, True
    if not component_root.exists():
        return

    for current, directories, filenames in os.walk(
        component_root,
        followlinks=False,
        onerror=_raise_storage_walk_error,
    ):
        current_path = Path(current)
        current_relative = current_path.relative_to(component_root)

        for directory in directories:
            directory_path = current_path / directory
            if _is_link_or_junction(directory_path):
                raise BackupOperationError(
                    "Medical-file storage contains a symbolic link or junction; backup stopped."
                )
            relative = PurePosixPath(current_relative.as_posix(), directory)
            yield f"{archive_prefix}/{relative.as_posix()}/", directory_path, True

        for filename in filenames:
            file_path = current_path / filename
            if _is_link_or_junction(file_path) or not file_path.is_file():
                raise BackupOperationError(
                    "Medical-file storage contains a non-regular file; backup stopped."
                )
            relative = PurePosixPath(current_relative.as_posix(), filename)
            if (
                department is not None
                and len(relative.parts) == 1
                and re.fullmatch(r"[a-f0-9]{32}", filename) is None
            ):
                raise BackupOperationError(
                    f"Invalid medical storage key in department {department}: {filename}"
                )
            yield f"{archive_prefix}/{relative.as_posix()}", file_path, False


def _iter_backup_components(storage_root: Path):
    yield "files/", None, True
    for department in _DEPARTMENT_NAMES:
        yield from _component_entries(
            storage_root / department,
            f"files/{department}",
            department=department,
        )

    yield from _component_entries(storage_root / "Quarantine", "quarantine")
    yield "logs/", None, True
    yield from _component_entries(
        storage_root / "System" / "ApplicationLogs",
        "logs/application",
    )
    yield "metadata/", None, True


def _build_archive(job_id: int, job_type: str, root: Path) -> tuple[Path, int, str]:
    root.mkdir(parents=True, exist_ok=True)
    storage_root = Path(settings.storage_root)
    if _is_link_or_junction(storage_root):
        raise BackupOperationError(
            "Configured medical-file storage cannot be a symbolic link or junction."
        )
    storage_root = storage_root.resolve()
    with tempfile.TemporaryDirectory(prefix=f".backup-{job_id}-", dir=root) as working_name:
        working = Path(working_name)
        database_file = working / _DATABASE_NAME
        _run_dump(database_file)

        entries: dict[str, dict[str, object]] = {}
        final_name = f"hospital-{'safety' if job_type == 'safety_backup' else 'backup'}-{job_id}.zip"
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
                entries[_DATABASE_NAME] = {
                    "type": "file",
                    "sha256": _sha256_file(database_file),
                    "size_bytes": database_file.stat().st_size,
                }

                for archive_name, source_path, is_directory in _iter_backup_components(storage_root):
                    if not _safe_archive_member(archive_name):
                        raise BackupOperationError(
                            "A selected storage component contains a path that cannot be safely archived."
                        )
                    if is_directory:
                        entries[archive_name] = {
                            "type": "directory",
                            "sha256": hashlib.sha256(b"").hexdigest(),
                            "size_bytes": 0,
                        }
                        archive.writestr(archive_name, b"")
                        continue
                    if source_path is None:
                        raise BackupOperationError("A selected storage file is unavailable.")
                    entries[archive_name] = {
                        "type": "file",
                        "sha256": _sha256_file(source_path),
                        "size_bytes": source_path.stat().st_size,
                    }
                    archive.write(source_path, archive_name)

                created_at = datetime.now(timezone.utc).isoformat()
                backup_metadata = {
                    "backup_job_id": job_id,
                    "job_type": job_type,
                    "created_at": created_at,
                    "system_version": settings.app_version,
                    "archive_format_version": ARCHIVE_FORMAT_VERSION,
                    "database": settings.db_name,
                    "included_components": [
                        *[f"files/{name}" for name in _DEPARTMENT_NAMES],
                        "quarantine/",
                        "logs/application/",
                    ],
                    "excluded_components": [
                        "Backup/Incoming/",
                        "Backup/Repository/",
                        "RestoreTest/",
                        "other storage paths",
                    ],
                }
                metadata_bytes = json.dumps(
                    backup_metadata,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                archive.writestr(_BACKUP_METADATA_NAME, metadata_bytes)
                entries[_BACKUP_METADATA_NAME] = {
                    "type": "file",
                    "sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                    "size_bytes": len(metadata_bytes),
                }

                manifest = {
                    "format_version": ARCHIVE_FORMAT_VERSION,
                    "database": settings.db_name,
                    "created_at": created_at,
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
    current_name = f"hospital-{expected_kind}-{job.id}.zip"
    legacy_prefix = f"hospital-{expected_kind}-{job.id}-"
    if path.name != current_name and not path.name.startswith(legacy_prefix):
        raise BackupOperationError("The selected backup archive does not match its job.")
    if _sha256_file(path) != job.checksum:
        raise BackupOperationError("The selected backup archive checksum does not match.")
    return path


def _safe_archive_member(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    directory_entry = name.endswith("/")
    normalized_name = name[:-1] if directory_entry else name
    raw_parts = normalized_name.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in raw_parts):
        return False
    path = PurePosixPath(normalized_name)
    if path.is_absolute():
        return False
    if not directory_entry and normalized_name in {
        _DATABASE_NAME,
        _MANIFEST_NAME,
        _LEGACY_MANIFEST_NAME,
        _BACKUP_METADATA_NAME,
    }:
        return True
    if len(path.parts) == 1 and directory_entry:
        return path.parts[0] in {"files", "quarantine", "logs", "metadata"}
    if directory_entry and path.parts == ("logs", "application"):
        return True
    if path.parts[0] == "files":
        return len(path.parts) >= 2
    if path.parts[0] == "quarantine":
        return len(path.parts) >= 2
    if path.parts[:2] == ("logs", "application"):
        return len(path.parts) >= 3
    return directory_entry and path.parts == ("metadata",)


def _v2_member_is_allowed(name: str, info: zipfile.ZipInfo) -> bool:
    normalized = name[:-1] if info.is_dir() and name.endswith("/") else name
    parts = PurePosixPath(normalized).parts
    if normalized in {_DATABASE_NAME, _MANIFEST_NAME, _BACKUP_METADATA_NAME}:
        return not info.is_dir()
    if info.is_dir() and normalized in {"files", "quarantine", "logs", "metadata", "logs/application"}:
        return True
    if parts and parts[0] == "files":
        if len(parts) < 2 or parts[1] not in ALLOWED_DEPARTMENTS:
            return False
        if len(parts) == 2:
            return info.is_dir()
        if not info.is_dir() and len(parts) == 3:
            return re.fullmatch(r"[a-f0-9]{32}", parts[-1]) is not None
        return True
    if parts and parts[0] == "quarantine":
        return len(parts) == 1 and info.is_dir() or len(parts) > 1
    if parts[:2] == ("logs", "application"):
        return len(parts) == 2 and info.is_dir() or len(parts) > 2
    return False


def _staging_destination(
    member_name: str,
    format_version: int,
    database_file: Path,
    departments_root: Path,
    quarantine_root: Path,
    application_logs_root: Path,
) -> Path | None:
    if member_name == _DATABASE_NAME:
        return database_file

    name = member_name[:-1] if member_name.endswith("/") else member_name
    parts = PurePosixPath(name).parts
    if format_version == 2:
        if len(parts) >= 2 and parts[0] == "files" and parts[1] in ALLOWED_DEPARTMENTS:
            return departments_root.joinpath(*parts[1:])
        if parts[0] == "quarantine" and len(parts) >= 2:
            return quarantine_root.joinpath(*parts[1:])
        if parts[:2] == ("logs", "application") and len(parts) >= 3:
            return application_logs_root.joinpath(*parts[2:])
        return None

    if len(parts) < 2 or parts[0] != "files":
        return None
    legacy_parts = parts[1:]
    if legacy_parts[0] in ALLOWED_DEPARTMENTS:
        return departments_root.joinpath(*legacy_parts)
    if legacy_parts[0] == "Quarantine" and len(legacy_parts) >= 2:
        return quarantine_root.joinpath(*legacy_parts[1:])
    if legacy_parts[:2] == ("System", "ApplicationLogs") and len(legacy_parts) >= 3:
        return application_logs_root.joinpath(*legacy_parts[2:])
    return None


def _validate_and_stage_archive(
    archive_path: Path,
    expected_checksum: str,
    staging_root: Path,
) -> StagedArchive:
    if _sha256_file(archive_path) != expected_checksum:
        raise BackupOperationError("The selected backup archive checksum does not match.")

    database_path = staging_root / _DATABASE_NAME
    departments_root = staging_root / "departments"
    quarantine_root = staging_root / "quarantine"
    application_logs_root = staging_root / "application_logs"
    departments_root.mkdir(parents=True, exist_ok=False)
    for department in _DEPARTMENT_NAMES:
        (departments_root / department).mkdir()
    quarantine_root.mkdir()
    application_logs_root.mkdir()
    seen: set[str] = set()
    normalized_members: set[str] = set()
    file_members: set[str] = set()
    members: dict[str, zipfile.ZipInfo] = {}
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info in archive.infolist():
                name = info.filename
                normalized_name = name[:-1] if info.is_dir() and name.endswith("/") else name
                if (
                    not _safe_archive_member(name)
                    or name in seen
                    or normalized_name in normalized_members
                    or (info.is_dir() and info.file_size != 0)
                ):
                    raise BackupOperationError("Backup archive contains an unsupported or unsafe entry.")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise BackupOperationError("Backup archive contains a symbolic link.")
                seen.add(name)
                normalized_members.add(normalized_name)
                members[name] = info
                if not info.is_dir():
                    file_members.add(normalized_name)

            for file_member in file_members:
                if any(str(parent) in file_members for parent in PurePosixPath(file_member).parents):
                    raise BackupOperationError("Backup archive contains conflicting file and directory paths.")

            if _DATABASE_NAME not in seen:
                raise BackupOperationError("Backup archive is missing its manifest or database dump.")
            manifest_name = (
                _MANIFEST_NAME
                if _MANIFEST_NAME in seen
                else _LEGACY_MANIFEST_NAME if _LEGACY_MANIFEST_NAME in seen else None
            )
            if manifest_name is None:
                raise BackupOperationError("Backup archive is missing its manifest or database dump.")
            manifest = json.loads(archive.read(manifest_name))
            if not isinstance(manifest, dict):
                raise BackupOperationError("Backup archive manifest is invalid.")
            format_version = manifest.get("format_version")
            if format_version not in {1, ARCHIVE_FORMAT_VERSION} or manifest.get("database") != settings.db_name:
                raise BackupOperationError("Backup archive format or database does not match this installation.")
            if (format_version == 1 and manifest_name != _LEGACY_MANIFEST_NAME) or (
                format_version == ARCHIVE_FORMAT_VERSION and manifest_name != _MANIFEST_NAME
            ):
                raise BackupOperationError("Backup archive manifest path does not match its format version.")
            if format_version == 2 and any(
                not _v2_member_is_allowed(name, info)
                for name, info in members.items()
            ):
                raise BackupOperationError("Backup archive contains a component outside the version 2 scope.")
            entries = manifest.get("entries")
            if not isinstance(entries, dict) or set(entries) != seen - {manifest_name}:
                raise BackupOperationError("Backup archive manifest does not match its contents.")

            if format_version == 2:
                required_directories = {
                    "files/",
                    "quarantine/",
                    "logs/",
                    "logs/application/",
                    "metadata/",
                    *[f"files/{department}/" for department in _DEPARTMENT_NAMES],
                }
                if not required_directories.issubset(seen) or _BACKUP_METADATA_NAME not in seen:
                    raise BackupOperationError("Backup archive is missing a required scoped component.")

            for name, metadata in entries.items():
                expected_hash = metadata.get("sha256") if isinstance(metadata, dict) else None
                if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
                    raise BackupOperationError("Backup archive manifest has invalid checksum metadata.")
                info = members[name]
                entry_type = metadata.get("type") if isinstance(metadata, dict) else None
                if format_version == 2 and entry_type != ("directory" if info.is_dir() else "file"):
                    raise BackupOperationError("Backup archive manifest entry type does not match its content.")
                destination = _staging_destination(
                    name,
                    format_version,
                    database_path,
                    departments_root,
                    quarantine_root,
                    application_logs_root,
                )
                if name.endswith("/"):
                    if metadata.get("size_bytes") != 0 or expected_hash != hashlib.sha256(b"").hexdigest():
                        raise BackupOperationError("Backup archive manifest has invalid directory metadata.")
                    if destination is not None:
                        destination.mkdir(parents=True, exist_ok=True)
                    continue
                source = archive.open(name, "r")
                if destination is not None:
                    destination.parent.mkdir(parents=True, exist_ok=True)

                digest = hashlib.sha256()
                size = 0
                with source:
                    if destination is None:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                            size += len(chunk)
                    else:
                        with destination.open("xb") as output:
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
    return StagedArchive(
        database_file=database_path,
        departments_root=departments_root,
        quarantine_root=quarantine_root,
        application_logs_root=application_logs_root,
    )


def _import_database(
    database_file: Path,
    on_apply_started: Callable[[], None] | None = None,
) -> None:
    if not settings.mysql_restore_user or settings.mysql_restore_password is None:
        raise BackupOperationError(
            "MySQL restore credentials are not configured. Set "
            "MYSQL_RESTORE_USER and MYSQL_RESTORE_PASSWORD to a MySQL account "
            "with privileges to import the configured database dump."
        )

    tool = _resolve_mysql_tool(settings.mysql_path, "mysql.exe" if os.name == "nt" else "mysql")
    defaults_file = _create_mysql_defaults_file(
        settings.mysql_restore_user,
        settings.mysql_restore_password,
    )
    command = [tool, f"--defaults-extra-file={defaults_file}", "--binary-mode", settings.db_name]
    try:
        with database_file.open("rb") as source:
            process = subprocess.Popen(
                command,
                stdin=source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            if on_apply_started is not None:
                on_apply_started()
            _, stderr = process.communicate()
        if process.returncode != 0:
            reason = _mysql_import_failure_reason(stderr)
            raise BackupOperationError(
                f"MySQL database import failed (exit code {process.returncode}). {reason}"
            )
    except OSError as exc:
        raise BackupOperationError("MySQL database restore could not start. Check the configured mysql path.") from exc
    finally:
        _remove_defaults_file(defaults_file)


def _mysql_import_failure_reason(stderr: bytes | None) -> str:
    diagnostic = (stderr or b"").decode("utf-8", errors="replace").casefold()
    if any(marker in diagnostic for marker in ("access denied", "command denied", "does not have the privilege", "insufficient privilege")):
        return "MySQL denied the restore account; verify its database restore privileges."
    if any(marker in diagnostic for marker in ("can't connect", "cannot connect", "connection refused", "lost connection")):
        return "The MySQL client could not maintain a connection to the configured server."
    if "unknown option" in diagnostic or "unknown variable" in diagnostic:
        return "The configured MySQL client does not support the restore options."
    return "MySQL rejected the dump; check the configured client/server versions and restore privileges."


def _replace_directory_tree(target: Path, staged: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if _is_link_or_junction(target):
        raise BackupOperationError("A restore target is a symbolic link or junction.")
    if target.exists() and not target.is_dir():
        raise BackupOperationError("A restore target exists but is not a directory.")

    incoming = target.with_name(f".{target.name}.restore-new-{uuid.uuid4().hex}")
    previous = target.with_name(f".{target.name}.restore-old-{uuid.uuid4().hex}")
    had_previous = target.exists()
    try:
        shutil.copytree(staged, incoming)
        if had_previous:
            target.rename(previous)
        try:
            incoming.rename(target)
        except Exception:
            if had_previous and previous.exists():
                previous.rename(target)
            raise
    except Exception as exc:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)
        if had_previous and previous.exists() and not target.exists():
            try:
                previous.rename(target)
            except OSError as restore_exc:
                raise BackupOperationError(
                    "A department directory could not be replaced or returned to its prior state."
                ) from restore_exc
        if isinstance(exc, BackupOperationError):
            raise
        raise BackupOperationError("A selected department directory could not be replaced.") from exc

    if previous.exists():
        shutil.rmtree(previous, ignore_errors=True)


def _replace_department_trees(staged_departments: Path) -> None:
    storage_root = Path(settings.storage_root)
    if _is_link_or_junction(storage_root):
        raise BackupOperationError("Configured medical-file storage cannot be a symbolic link or junction.")
    storage_root = storage_root.resolve()
    if storage_root == storage_root.parent:
        raise BackupOperationError("Configured medical-file storage cannot be a drive or filesystem root.")
    storage_root.mkdir(parents=True, exist_ok=True)
    for department in _DEPARTMENT_NAMES:
        staged = staged_departments / department
        if not staged.is_dir():
            raise BackupOperationError(f"Restore archive is missing department folder {department}.")
        _replace_directory_tree(storage_root / department, staged)


def _append_isolated_component(
    staged_component: Path,
    target_parent: Path,
    restore_job_id: int,
) -> Path:
    configured_root = Path(settings.storage_root)
    if _is_link_or_junction(configured_root):
        raise BackupOperationError("Configured medical-file storage cannot be a symbolic link or junction.")
    storage_root = configured_root.resolve()
    if not target_parent.is_relative_to(storage_root):
        raise BackupOperationError("Optional restore destination is outside medical-file storage.")
    relative_parent = target_parent.relative_to(storage_root)
    safe_parent = storage_root
    for part in relative_parent.parts:
        safe_parent = safe_parent / part
        if safe_parent.exists():
            if _is_link_or_junction(safe_parent) or not safe_parent.is_dir():
                raise BackupOperationError("An optional restore destination is not a regular directory.")
        else:
            safe_parent.mkdir()
    target_parent = safe_parent
    destination = target_parent / f"RestoredFromBackup-{restore_job_id}"
    if destination.exists():
        raise BackupOperationError("The isolated restore destination already exists.")
    incoming = target_parent / f".restore-new-{restore_job_id}-{uuid.uuid4().hex}"
    try:
        shutil.copytree(staged_component, incoming)
        incoming.rename(destination)
    except Exception as exc:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)
        if isinstance(exc, BackupOperationError):
            raise
        raise BackupOperationError("Optional restore data could not be copied into its isolated folder.") from exc
    return destination


def _apply_archive(
    archive_path: Path,
    expected_checksum: str,
    root: Path,
    on_apply_started: Callable[[], None] | None = None,
    restore_job_id: int | None = None,
    restore_quarantine: bool = False,
    restore_application_logs: bool = False,
) -> None:
    with tempfile.TemporaryDirectory(prefix=".restore-stage-", dir=root) as staging_name:
        staged = _validate_and_stage_archive(
            archive_path,
            expected_checksum,
            Path(staging_name),
        )
        created_optional_paths: list[Path] = []
        try:
            _import_database(staged.database_file, on_apply_started)
            _replace_department_trees(staged.departments_root)

            if restore_quarantine or restore_application_logs:
                if restore_job_id is None:
                    raise BackupOperationError("Restore job ID is required for isolated optional restores.")
                storage_root = Path(settings.storage_root).resolve()
                if restore_quarantine:
                    created_optional_paths.append(
                        _append_isolated_component(
                            staged.quarantine_root,
                            storage_root / "Quarantine",
                            restore_job_id,
                        )
                    )
                if restore_application_logs:
                    created_optional_paths.append(
                        _append_isolated_component(
                            staged.application_logs_root,
                            storage_root / "System" / "ApplicationLogs",
                            restore_job_id,
                        )
                    )
        except Exception:
            for optional_path in reversed(created_optional_paths):
                shutil.rmtree(optional_path, ignore_errors=True)
            raise


def _record_restore_failure(db: Session, job_id: int, message: str) -> BackupJob:
    return _set_job_failed(db, job_id, message)


def _restore_locked(
    db: Session,
    backup_job_id: int,
    job: BackupJob,
    restore_quarantine: bool,
    restore_application_logs: bool,
) -> BackupJob:
    safety_job: BackupJob | None = None
    apply_started = False

    def mark_apply_started() -> None:
        nonlocal apply_started
        apply_started = True

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
        _apply_archive(
            selected_path,
            selected.checksum or "",
            root,
            on_apply_started=mark_apply_started,
            restore_job_id=job.id,
            restore_quarantine=restore_quarantine,
            restore_application_logs=restore_application_logs,
        )

        job.status = "success"
        job.finished_at = _now_naive_utc()
        restored_separately = []
        if restore_quarantine:
            restored_separately.append(f"Quarantine\\RestoredFromBackup-{job.id}")
        if restore_application_logs:
            restored_separately.append(f"System\\ApplicationLogs\\RestoredFromBackup-{job.id}")
        optional_message = (
            f" Separately restored: {', '.join(restored_separately)}."
            if restored_separately
            else ""
        )
        job.message = f"Restored successfully. Safety backup job #{safety_job.id}.{optional_message}"
        db.commit()
        db.refresh(job)
        return job
    except BackupOperationError as exc:
        message = str(exc)
    except Exception:
        message = "Restore failed due to an unexpected server error."

    if (
        apply_started
        and safety_job
        and safety_job.status == "success"
        and safety_job.destination
        and safety_job.checksum
    ):
        try:
            root = _backup_root()
            safety_path = _resolve_archive(safety_job, root)
            _apply_archive(safety_path, safety_job.checksum, root)
        except BackupOperationError as rollback_error:
            message = (
                f"Restore failed: {message} Safety rollback also failed: "
                f"{rollback_error}. Manual recovery is required."
            )
        except Exception:
            message = (
                f"Restore failed: {message} Safety rollback also failed due to "
                "an unexpected error. Manual recovery is required."
            )

    return _record_restore_failure(db, job.id, message)


def restore_backup(
    db: Session,
    backup_job_id: int,
    confirm: bool,
    restore_quarantine: bool = False,
    restore_application_logs: bool = False,
) -> BackupJob:
    if confirm is not True:
        raise BackupOperationError("Explicit confirmation is required before restoring a backup.")

    selected = db.scalar(select(BackupJob).where(BackupJob.id == backup_job_id))
    if selected is None:
        raise BackupOperationError("The selected backup was not found.")
    job = _create_job(db, "restore", destination=selected.destination)

    try:
        with backup_operation_lock():
            return _restore_locked(
                db,
                backup_job_id,
                job,
                restore_quarantine,
                restore_application_logs,
            )
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
