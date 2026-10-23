from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

class MedicalRecordCreateRequest(BaseModel):
    record_number: str = Field(min_length=1, max_length=50)
    patient_code: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=255)
    department: Literal[
        "Clinical",
        "Laboratory",
        "Imaging",
        "Administration",
        "HR",
    ]


class MedicalRecordUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    status: Literal["active", "archived"]
