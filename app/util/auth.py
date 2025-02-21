import base64
from datetime import timedelta, datetime, timezone
from enum import Enum
import re
import secrets
from typing import Annotated, Literal, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, OAuth2PasswordBearer
import jwt
from sqlmodel import Session

from app.db import get_session
from app.models import User, GroupEnum
from app.util.cache import StringConfigCache

JWT_ALGORITHM = "HS256"


class LoginTypeEnum(str, Enum):
    basic = "basic"
    forms = "forms"
    none = "none"

    def is_basic(self):
        return self == LoginTypeEnum.basic

    def is_forms(self):
        return self == LoginTypeEnum.forms

    def is_none(self):
        return self == LoginTypeEnum.none


AuthConfigKey = Literal["login_type", "access_token_expiry_minutes", "auth_secret"]


class AuthConfig(StringConfigCache[AuthConfigKey]):
    def get_login_type(self, session: Session) -> LoginTypeEnum:
        login_type = self.get(session, "login_type")
        if login_type:
            return LoginTypeEnum(login_type)
        return LoginTypeEnum.basic

    def set_login_type(self, session: Session, login_Type: LoginTypeEnum):
        self.set(session, "login_type", login_Type.value)

    def reset_auth_secret(self, session: Session):
        auth_secret = base64.encodebytes(secrets.token_bytes(64)).decode("utf-8")
        self.set(session, "auth_secret", auth_secret)

    def get_auth_secret(self, session: Session) -> str:
        auth_secret = self.get(session, "auth_secret")
        if auth_secret:
            return auth_secret
        auth_secret = base64.encodebytes(secrets.token_bytes(64)).decode("utf-8")
        self.set(session, "auth_secret", auth_secret)
        return auth_secret

    def get_access_token_expiry_minutes(self, session: Session):
        return self.get_int(session, "access_token_expiry_minutes", 60 * 24 * 7)

    def set_access_token_expiry_minutes(self, session: Session, expiry: int):
        self.set_int(session, "access_token_expiry_minutes", expiry)


class DetailedUser(User):
    login_type: LoginTypeEnum

    def can_logout(self):
        return self.login_type == LoginTypeEnum.forms


security = HTTPBasic()
ph = PasswordHasher()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)
auth_config = AuthConfig()


validate_password_regex = re.compile(
    r"^(?=[^A-Z]*[A-Z])(?=[^a-z]*[a-z])(?=\D*\d).{8,}$"
)


def raise_for_invalid_password(
    password: str, confirm_password: Optional[str] = None, ignore_confirm: bool = False
):
    if not ignore_confirm and password != confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords must be equal",
        )
    if not validate_password_regex.match(password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, and one number",
        )


def is_correct_password(user: User, password: str) -> bool:
    try:
        return ph.verify(user.password, password)
    except VerifyMismatchError:
        return False


def authenticate_user(session: Session, username: str, password: str) -> Optional[User]:
    user = session.get(User, username)
    if not user:
        return None

    try:
        ph.verify(user.password, password)
    except VerifyMismatchError:
        return None

    if ph.check_needs_rehash(user.password):
        user.password = ph.hash(password)
        session.add(user)
        session.commit()

    return user


def create_access_token(
    auth_secret: str, data: dict[str, str | datetime], expires_delta: timedelta
):
    to_encode = data.copy()
    expires = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expires})
    encoded_jwt = jwt.encode(to_encode, auth_secret, algorithm=JWT_ALGORITHM)  # pyright: ignore[reportUnknownMemberType]
    return encoded_jwt


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
    ) -> DetailedUser:
        login_type = auth_config.get_login_type(session)

        if login_type == LoginTypeEnum.forms:
            user = await _get_forms_auth(request, session)
        elif login_type == LoginTypeEnum.none:
            user = await _get_none_auth()
        else:
            user = await _get_basic_auth(request, session)

        if not user.is_above(lowest_allowed_group):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
            )

        user = DetailedUser.model_validate(user, update={"login_type": login_type})

        return user

    return get_user


async def _get_basic_auth(
    request: Request,
    session: Session,
) -> User:
    invalid_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )

    credentials = await security(request)

    if not credentials:
        raise invalid_exception

    user = authenticate_user(session, credentials.username, credentials.password)
    if not user:
        raise invalid_exception

    return user


class RequiresLoginException(Exception):
    def __init__(self, detail: Optional[str] = None, **kwargs: object):
        super().__init__(**kwargs)
        self.detail = detail


async def _get_forms_auth(
    request: Request,
    session: Session,
) -> User:
    # Authentication is either through Authorization header or cookie
    token = await oauth2_scheme(request)
    if not token:
        token = request.cookies.get("audio_sess")
        if not token:
            raise RequiresLoginException()

    try:
        payload = jwt.decode(  # pyright: ignore[reportUnknownMemberType]
            token, auth_config.get_auth_secret(session), algorithms=[JWT_ALGORITHM]
        )
    except jwt.InvalidTokenError:
        raise RequiresLoginException("Token is expired/invalid")

    username = payload.get("sub")
    if username is None:
        raise RequiresLoginException("Token is invalid")

    user = session.get(User, username)
    if not user:
        raise RequiresLoginException("User does not exist")

    return user


async def _get_none_auth() -> User:
    """Treats every request as being root / turns off authentication"""
    return User(username="no-login", password="", group=GroupEnum.admin, root=True)
