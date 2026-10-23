
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine, get_db

from app.api.auth import router as auth_router
from app.api.records import router as records_router
from app.api.files import router as files_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Xác nhận kết nối database khi ứng dụng khởi động.
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    yield

    # Giải phóng connection pool khi ứng dụng dừng.
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Hospital storage and data protection system",
    lifespan=lifespan,
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(records_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")


@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@app.get("/api/v1/health/db", tags=["System"])
def database_health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))

        return {
            "status": "ok",
            "database": settings.db_name,
            "message": "MySQL connection successful",
        }
    except Exception as exc:
        # Không trả thông tin kết nối hoặc chi tiết lỗi nội bộ ra API.
        raise HTTPException(
            status_code=503,
            detail="Database connection failed",
        ) from exc
