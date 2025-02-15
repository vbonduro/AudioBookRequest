from typing import Annotated
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from sqlmodel import Session, select
from app.db import get_session
from app.models import User

security = HTTPBasic()


def get_username(
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
):
    username_bytes = credentials.username.encode("utf-8")
    password_bytes = credentials.password.encode("utf-8")

    user = session.exec(
        select(User).where(User.username == username_bytes)
    ).one_or_none()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    is_correct_username = secrets.compare_digest(user.username, username_bytes)
    is_correct_password = secrets.compare_digest(user.password, password_bytes)

    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
