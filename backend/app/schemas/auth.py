from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class UserMeResponse(BaseModel):
    id: int
    username: str
    full_name: str
    department: str | None
    roles: list[str]
    permissions: list[str]
