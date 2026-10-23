
import hashlib
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.core.config import settings


MAX_UPLOAD_SIZE = settings.max_upload_size_bytes

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".csv": "text/csv",
}

ALLOWED_DEPARTMENTS = {
    "Clinical",
    "Laboratory",
    "Imaging",
    "Administration",
    "HR",
}


def get_department_directory(department: str) -> Path:
    if department not in ALLOWED_DEPARTMENTS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported department",
        )

    root = Path(settings.storage_root).resolve()
    directory = (root / department).resolve()

    if not directory.is_relative_to(root):
        raise HTTPException(
            status_code=400,
            detail="Invalid storage directory",
        )

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def validate_storage_key(storage_key: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}", storage_key):
        raise HTTPException(
            status_code=500,
            detail="Invalid storage metadata",
        )


def get_file_path(department: str, storage_key: str) -> Path:
    validate_storage_key(storage_key)

    directory = get_department_directory(department)
    path = (directory / storage_key).resolve()

    if not path.is_relative_to(directory):
        raise HTTPException(
            status_code=400,
            detail="Invalid file path",
        )

    return path


async def read_and_validate_upload(
    upload: UploadFile,
) -> tuple[bytes, str, str, str]:
    filename = Path(upload.filename or "").name

    if not filename or filename in {".", ".."}:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename",
        )

    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="File type is not allowed",
        )

    content = await upload.read(MAX_UPLOAD_SIZE + 1)

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Empty files are not allowed",
        )

    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the upload size limit",
        )

    mime_type = ALLOWED_EXTENSIONS[extension]

    # Kiểm tra chữ ký cơ bản cho các định dạng nhị phân.
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=415,
            detail="Invalid PDF file signature",
        )

    if extension == ".png" and not content.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        raise HTTPException(
            status_code=415,
            detail="Invalid PNG file signature",
        )

    if extension in {".jpg", ".jpeg"} and not content.startswith(
        b"\xff\xd8\xff"
    ):
        raise HTTPException(
            status_code=415,
            detail="Invalid JPEG file signature",
        )

    if extension in {".txt", ".csv"} and b"\x00" in content:
        raise HTTPException(
            status_code=415,
            detail="Invalid text file content",
        )

    checksum = hashlib.sha256(content).hexdigest()
    storage_key = uuid4().hex

    return content, filename, mime_type, checksum


def save_file(path: Path, content: bytes) -> None:
    # Mở ở chế độ độc quyền: không ghi đè file đã tồn tại.
    with path.open("xb") as file:
        file.write(content)


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()
