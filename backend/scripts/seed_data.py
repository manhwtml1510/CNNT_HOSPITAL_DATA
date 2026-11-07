
from pwdlib import PasswordHash
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Permission, Role, User


password_hasher = PasswordHash.recommended()


# Quyền được định nghĩa tập trung.
PERMISSIONS = {
    "records:read": "Xem metadata hồ sơ",
    "records:create": "Tạo hồ sơ",
    "records:update": "Cập nhật hồ sơ",
    "files:upload": "Tải tệp lên",
    "files:download": "Tải tệp xuống",
    "users:manage": "Quản lý tài khoản",
    "audit:read": "Xem nhật ký kiểm toán",
    "backup:read": "Xem trạng thái sao lưu",
    "backup:execute": "Thực hiện sao lưu",
    "restore:execute": "Thực hiện khôi phục",
}

# Quyền thao tác theo từng vai trò.
ROLE_PERMISSIONS = {
    "system_admin": list(PERMISSIONS.keys()),

    "doctor": [
        "records:read",
        "records:create",
        "records:update",
        "files:upload",
        "files:download",
    ],

    "nurse": [
        "records:read",
        "files:download",
    ],

    "lab_staff": [
        "records:read",
        "records:update",
        "files:upload",
        "files:download",
    ],

    "admin_staff": [
        "records:read",
        "records:create",
        "records:update",
    ],

    "backup_operator": [
        "backup:read",
        "backup:execute",
    ],

    "restore_operator": [
        "backup:read",
        "restore:execute",
    ],
}

ROLES = {
    "system_admin": ("Quản trị hệ thống", "Quản trị demo"),
    "doctor": ("Bác sĩ", "Tài khoản bác sĩ demo"),
    "nurse": ("Điều dưỡng", "Tài khoản điều dưỡng demo"),
    "lab_staff": ("Nhân viên xét nghiệm", "Tài khoản xét nghiệm demo"),
    "admin_staff": ("Nhân viên hành chính", "Tài khoản hành chính demo"),
    "backup_operator": ("Nhân viên sao lưu", "Quản lý sao lưu demo"),
    "restore_operator": ("Nhân viên khôi phục", "Quản lý khôi phục demo"),
}

DEMO_USERS = [
    {
        "username": "demo_doctor",
        "full_name": "Bác sĩ Demo",
        "department": "Clinical",
        "role": "doctor",
        "password": settings.demo_doctor_password,
    },
    {
        "username": "demo_nurse",
        "full_name": "Điều dưỡng Demo",
        "department": "Clinical",
        "role": "nurse",
        "password": settings.demo_nurse_password,
    },
    {
        "username": "demo_lab",
        "full_name": "Nhân viên xét nghiệm Demo",
        "department": "Laboratory",
        "role": "lab_staff",
        "password": settings.demo_lab_password,
    },
    {
        "username": "demo_admin",
        "full_name": "Quản trị Demo",
        "department": "Administration",
        "role": "system_admin",
        "password": settings.demo_admin_password,
    },
    {
        "username": "demo_adminstaff",
        "full_name": "Nhân viên hành chính Demo",
        "department": "Administration",
        "role": "admin_staff",
        "password": settings.demo_adminstaff_password,
    },
]


def seed() -> None:
    missing_passwords = [
        user["username"]
        for user in DEMO_USERS
        if not user["password"].strip()
    ]

    if missing_passwords:
        raise RuntimeError(
            "Chưa cấu hình mật khẩu demo trong .env cho: "
            + ", ".join(missing_passwords)
        )

    with SessionLocal() as db:
        # Tạo hoặc lấy permissions hiện có.
        permission_objects = {}

        for code, description in PERMISSIONS.items():
            permission = db.scalar(
                select(Permission).where(Permission.code == code)
            )

            if permission is None:
                permission = Permission(
                    code=code,
                    description=description,
                )
                db.add(permission)

            permission_objects[code] = permission

        db.flush()

        # Tạo hoặc cập nhật vai trò và quyền của vai trò.
        role_objects = {}

        for code, (name, description) in ROLES.items():
            role = db.scalar(
                select(Role).where(Role.code == code)
            )

            if role is None:
                role = Role(code=code, name=name, description=description)
                db.add(role)

            role.permissions = [
                permission_objects[p]
                for p in ROLE_PERMISSIONS[code]
            ]
            role_objects[code] = role

        db.flush()

        # Tạo tài khoản nếu chưa tồn tại.
        # Nếu tài khoản đã có, không tự ghi đè mật khẩu.
        for item in DEMO_USERS:
            user = db.scalar(
                select(User).where(User.username == item["username"])
            )

            if user is None:
                user = User(
                    username=item["username"],
                    password_hash=password_hasher.hash(item["password"]),
                    full_name=item["full_name"],
                    department=item["department"],
                    is_active=True,
                )
                user.roles = [role_objects[item["role"]]]
                db.add(user)
            else:
                # Chỉ bảo đảm vai trò demo cần thiết đã được gán.
                role = role_objects[item["role"]]
                if role not in user.roles:
                    user.roles.append(role)

        db.commit()

    print("Seed thành công: permissions, roles và tài khoản demo.")


if __name__ == "__main__":
    seed()
