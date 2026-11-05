import jwt

from collections.abc import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.backup import BackupOperationError, backup_operation_lock
from app.core.security import decode_access_token
from app.models import Role, User


bearer_scheme = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=401,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise unauthorized

    statement = (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.roles).selectinload(Role.permissions)
        )
    )
    user = db.scalar(statement)

    if user is None or not user.is_active:
        raise unauthorized

    return user

def require_permission(permission_code: str):
    def permission_checker(
        user: User = Depends(get_current_user),
    ) -> User:
        granted = {
            permission.code
            for role in user.roles
            for permission in role.permissions
        }

        if permission_code not in granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )

        return user

    return permission_checker


def reject_during_backup_or_restore() -> Generator[None, None, None]:
    try:
        with backup_operation_lock():
            yield
    except BackupOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
