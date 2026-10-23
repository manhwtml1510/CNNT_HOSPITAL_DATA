
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import create_access_token, verify_password
from app.models import AuditLog, Role, User
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UserMeResponse,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])


def write_audit_log(
    db: Session,
    *,
    actor_user_id: int | None,
    action: str,
    outcome: str,
    request: Request,
) -> None:
    #Không ghi username, mật khẩu, token hoặc dữ liệu hồ sơ vào log.
    client_ip = request.client.host if request.client else None

    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            resource_type="authentication",
            outcome=outcome,
            ip_address=client_ip,
        )
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    statement = (
        select(User)
        .where(User.username == body.username)
        .options(
            selectinload(User.roles).selectinload(Role.permissions)
        )
    )
    user = db.scalar(statement)

    #không cho biết tài khoản có tồn tại hay không
    if (
        user is None
        or not user.is_active
        or not verify_password(body.password, user.password_hash)
    ):
        write_audit_log(
            db,
            actor_user_id=user.id if user else None,
            action="login",
            outcome="failure",
            request=request,
        )
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    write_audit_log(
        db,
        actor_user_id=user.id,
        action="login",
        outcome="success",
        request=request,
    )
    db.commit()

    token = create_access_token(user.id)

    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserMeResponse)
def read_me(
    user: User = Depends(get_current_user),
):
    roles = sorted(role.code for role in user.roles)
    permissions = sorted({
        permission.code
        for role in user.roles
        for permission in role.permissions
    })

    return UserMeResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        department=user.department,
        roles=roles,
        permissions=permissions,
    )
