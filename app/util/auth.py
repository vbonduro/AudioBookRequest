from enum import Enum
import os
import re
from typing import Annotated, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic
from sqlmodel import Session, select

from app.db import get_session
from app.models import Config, User, GroupEnum

SECRET_KEY = os.getenv("AUTH_SECRET")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

security = HTTPBasic()
ph = PasswordHasher()


class LoginTypeEnum(str, Enum):
    basic = "basic"
    forms = "forms"
    none = "none"


validate_password_regex = re.compile(
    r"^(?=[^A-Z]*[A-Z])(?=[^a-z]*[a-z])(?=\D*\d).{8,}$"
)


def raise_for_invalid_password(
    password: str, confirm_password: Optional[str] = None, ignore_confirm: bool = False
):
    if not ignore_confirm and password != confirm_password:
        raise HTTPException(
            status_code=400,
            detail="Passwords must be equal",
        )
    if not validate_password_regex.match(password):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, and one number",
        )


def is_correct_password(user: User, password: str) -> bool:
    try:
        return ph.verify(user.password, password)
    except VerifyMismatchError:
        return False


def create_user(
    username: str,
    password: str,
    group: GroupEnum = GroupEnum.untrusted,
    root: bool = False,
) -> User:
    password_hash = ph.hash(password)
    return User(username=username, password=password_hash, group=group, root=root)


def get_authenticated_user(lowest_allowed_group: GroupEnum = GroupEnum.untrusted):
    async def get_user(
        request: Request,
        session: Annotated[Session, Depends(get_session)],
    ) -> User:
        login_type = session.get(Config, "login_type")
        if login_type:
            login_type = LoginTypeEnum(login_type)
        else:
            login_type = LoginTypeEnum.basic

        if login_type == LoginTypeEnum.forms:
            return await _get_forms_auth(request, session, lowest_allowed_group)
        if login_type == LoginTypeEnum.none:
            return await _get_none_auth(request, session, lowest_allowed_group)

        return await _get_basic_auth(request, session, lowest_allowed_group)

    return get_user


async def _get_basic_auth(
    request: Request,
    session: Session,
    lowest_allowed_group: GroupEnum,
) -> User:
    credentials = await security(request)

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    user = session.exec(
        select(User).where(User.username == credentials.username)
    ).one_or_none()

    if not user:
        raise HTTPException(
            status_code=403,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        ph.verify(user.password, credentials.password)
    except VerifyMismatchError:
        raise HTTPException(
            status_code=403,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    if ph.check_needs_rehash(user.password):
        user.password = ph.hash(credentials.password)
        session.add(user)
        session.commit()

    if not user.is_above(lowest_allowed_group):
        raise HTTPException(status_code=403, detail="Forbidden")

    return user


async def _get_forms_auth(
    request: Request,
    session: Session,
    lowest_allowed_group: GroupEnum,
) -> User:
    print(request.form)


async def _get_none_auth(
    request: Request,
    session: Session,
    lowest_allowed_group: GroupEnum,
) -> User: ...
