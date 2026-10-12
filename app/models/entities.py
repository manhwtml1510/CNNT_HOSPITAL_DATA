
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    BigInteger,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# 1. Bảng liên kết giữa users và roles

class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )


# 2. Bảng liên kết giữa roles và permissions

class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


# 3. Users

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(
        String(80), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    full_name: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles",
        back_populates="users",
    )


# 4. Roles

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    users: Mapped[list["User"]] = relationship(
        secondary="user_roles",
        back_populates="roles",
    )
    permissions: Mapped[list["Permission"]] = relationship(
        secondary="role_permissions",
        back_populates="roles",
    )


# 5. Permissions

class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary="role_permissions",
        back_populates="permissions",
    )


# 6. Medical records: chỉ lưu metadata hồ sơ

class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_number: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    patient_code: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    department: Mapped[str] = mapped_column(
        String(100), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), default="active", nullable=False
    )
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    files: Mapped[list["StoredFile"]] = relationship(
        back_populates="record",
    )

    __table_args__ = (
        Index("ix_records_department_status", "department", "status"),
    )


# 7. Stored files: metadata của tệp trên File Server

class StoredFile(Base):
    __tablename__ = "stored_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("medical_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(
        String(500), unique=True, nullable=False
    )
    mime_type: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    uploaded_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    record: Mapped["MedicalRecord"] = relationship(
        back_populates="files",
    )


# 8. Audit logs: lịch sử thao tác

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    outcome: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(
        String(45), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_audit_created_at", "created_at"),
        Index("ix_audit_actor_action", "actor_user_id", "action"),
    )


# 9. Backup jobs: theo dõi công việc sao lưu/khôi phục

class BackupJob(Base):
    __tablename__ = "backup_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    destination: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    bytes_total: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    checksum: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    message: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
