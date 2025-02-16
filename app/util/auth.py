from typing import Annotated, Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlmodel import Session, select

from app.db import get_session
from app.models import User

security = HTTPBasic()
ph = PasswordHasher()


def create_user(
    username: str,
    password: str,
    group: Literal["admin", "trusted", "untrusted"] = "untrusted",
) -> User:
    password_hash = ph.hash(password)
    return User(username=username, password=password_hash, group=group)


def get_authenticated_user(
    lowest_allowed_group: Literal["admin", "trusted", "untrusted"] = "untrusted",
):
    def get_user(
        session: Annotated[Session, Depends(get_session)],
        credentials: Annotated[HTTPBasicCredentials, Depends(security)],
    ) -> User:
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

        if lowest_allowed_group == "admin":
            if user.group != "admin":
                raise HTTPException(status_code=403, detail="Forbidden")
        elif lowest_allowed_group == "trusted":
            if user.group not in ["admin", "trusted"]:
                raise HTTPException(status_code=403, detail="Forbidden")

        return user

    return get_user
