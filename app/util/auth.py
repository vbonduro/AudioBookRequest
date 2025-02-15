from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlmodel import Session, select

from app.db import get_session
from app.models import User

security = HTTPBasic()
ph = PasswordHasher()


def create_user(username: str, password: str) -> User:
    password_hash = ph.hash(password)
    return User(username=username, password=password_hash)


def get_username(
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
):
    user = session.exec(
        select(User).where(User.username == credentials.username)
    ).one_or_none()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        ph.verify(user.password, credentials.password)
    except VerifyMismatchError:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    if ph.check_needs_rehash(user.password):
        user.password = ph.hash(credentials.password)
        session.add(user)
        session.commit()

    return credentials.username
