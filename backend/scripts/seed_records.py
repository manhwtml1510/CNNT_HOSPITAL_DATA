
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import MedicalRecord, User


DEMO_RECORDS = [
    {
        "record_number": "DEMO-CL-001",
        "patient_code": "PAT-DEMO-001",
        "title": "Hồ sơ khám tổng quát giả lập",
        "department": "Clinical",
        "status": "active",
        "created_by": "demo_doctor",
    },
    {
        "record_number": "DEMO-LAB-001",
        "patient_code": "PAT-DEMO-002",
        "title": "Hồ sơ xét nghiệm giả lập",
        "department": "Laboratory",
        "status": "active",
        "created_by": "demo_lab",
    },
    {
        "record_number": "DEMO-ADM-001",
        "patient_code": "PAT-DEMO-003",
        "title": "Hồ sơ hành chính giả lập",
        "department": "Administration",
        "status": "active",
        "created_by": "demo_admin",
    },
]


def seed_records() -> None:
    with SessionLocal() as db:
        for item in DEMO_RECORDS:
            existing = db.scalar(
                select(MedicalRecord).where(
                    MedicalRecord.record_number == item["record_number"]
                )
            )

            if existing:
                continue

            creator = db.scalar(
                select(User).where(User.username == item["created_by"])
            )

            if creator is None:
                raise RuntimeError(
                    f"Không tìm thấy tài khoản {item['created_by']}"
                )

            db.add(
                MedicalRecord(
                    record_number=item["record_number"],
                    patient_code=item["patient_code"],
                    title=item["title"],
                    department=item["department"],
                    status=item["status"],
                    created_by_id=creator.id,
                )
            )

        db.commit()

    print("Đã tạo dữ liệu hồ sơ giả lập.")


if __name__ == "__main__":
    seed_records()
