
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Hospital Data Protection API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "hospital_storage"
    db_user: str = "hospital_app"
    db_password: str
    
    demo_doctor_password: str = ""
    demo_nurse_password: str = ""
    demo_lab_password: str = ""
    demo_admin_password: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

