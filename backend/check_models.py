
from app.core.database import Base
from app import models

print("Các bảng đã đăng ký:")
for table_name in sorted(Base.metadata.tables):
    print(f"- {table_name}")

expected_tables = {
    "users",
    "roles",
    "permissions",
    "user_roles",
    "role_permissions",
    "medical_records",
    "stored_files",
    "audit_logs",
    "backup_jobs",
}

missing = expected_tables - set(Base.metadata.tables)

if missing:
    raise SystemExit(f"Thiếu bảng: {sorted(missing)}")

print("\nModel registration OK")
