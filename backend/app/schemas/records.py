from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MedicalRecordResponse(BaseModel):
    id: int
    record_number: str
    patient_code: str
    title: str
    department: str
    status: str
    created_by_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
