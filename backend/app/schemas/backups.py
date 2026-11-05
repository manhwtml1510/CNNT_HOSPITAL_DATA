from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field


class BackupJobResponse(BaseModel):
    id: int
    job_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    destination: str | None
    archive_available: bool
    bytes_total: int | None
    checksum: str | None
    message: str | None
    created_at: datetime

class BackupJobPageResponse(BaseModel):
    items: list[BackupJobResponse]
    total: int
    limit: int
    offset: int


class RestoreRequest(BaseModel):
    confirm: Literal[True] = Field(description="Must be true to replace the live database and file store")
    restore_quarantine: bool = Field(default=False, description="Restore quarantined files into an isolated folder")
    restore_application_logs: bool = Field(default=False, description="Restore application logs into an isolated folder")
