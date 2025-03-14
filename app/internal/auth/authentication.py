from typing import Annotated, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, OAuth2PasswordBearer, OpenIdConnect
from sqlmodel import Session, select

from app.internal.auth.config import LoginTypeEnum, auth_config
from app.internal.models import GroupEnum, User
from app.util.db import get_session

JWT_ALGORITHM = "HS256"


class DetailedUser(User):
    login_type: LoginTypeEnum

    def can_logout(self):
        return self.login_type in [LoginTypeEnum.forms, LoginTypeEnum.oidc]


def raise_for_invalid_password(
    session: Session,
    password: str,
    confirm_password: Optional[str] = None,
    ignore_confirm: bool = False,
):
    if not ignore_confirm and password != confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords must be equal",
        )

    min_password_length = auth_config.get_min_password_length(session)
    if not len(password) >= min_password_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {min_password_length} characters long",
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


def create_user(
    username: str,
    password: str,
    group: GroupEnum = GroupEnum.untrusted,
    root: bool = False,
) -> User:
    password_hash = ph.hash(password)
    return User(username=username, password=password_hash, group=group, root=root)


class RequiresLoginException(Exception):
    def __init__(self, detail: Optional[str] = None, **kwargs: object):
        super().__init__(**kwargs)
        self.detail = detail


class ABRAuth:
    def __init__(self):
        self.oidc_scheme: Optional[OpenIdConnect] = None
        self.none_user: Optional[User] = None

    def get_authenticated_user(self, lowest_allowed_group: GroupEnum):
        async def get_user(
            request: Request,
            session: Annotated[Session, Depends(get_session)],
        ) -> DetailedUser:
            login_type = auth_config.get_login_type(session)

            if login_type == LoginTypeEnum.forms or login_type == LoginTypeEnum.oidc:
                user = await self._get_session_auth(request, session)
            elif login_type == LoginTypeEnum.none:
                user = await self._get_none_auth(session)
            else:
                user = await self._get_basic_auth(request, session)

            if not user.is_above(lowest_allowed_group):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
                )

            user = DetailedUser.model_validate(user, update={"login_type": login_type})

            return user

        return get_user

    async def _get_basic_auth(
        self,
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

    async def _get_session_auth(
        self,
        request: Request,
        session: Session,
    ) -> User:
        # It's enough to get the username from the signed session cookie
        username = request.session.get("sub")
        if not username:
            raise RequiresLoginException()

        user = session.get(User, username)
        if not user:
            raise RequiresLoginException("User does not exist")

        return user

    async def _get_none_auth(self, session: Session) -> User:
        """Treats every request as being root by returning the first admin user"""
        if self.none_user:
            return self.none_user
        self.none_user = session.exec(
            select(User).where(User.group == GroupEnum.admin).limit(1)
        ).one()
        return self.none_user


security = HTTPBasic()
ph = PasswordHasher()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)
abr_authentication = ABRAuth()


def get_authenticated_user(lowest_allowed_group: GroupEnum = GroupEnum.untrusted):
    return abr_authentication.get_authenticated_user(lowest_allowed_group)
