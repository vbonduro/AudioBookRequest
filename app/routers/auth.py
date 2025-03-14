import base64
import secrets
from typing import Annotated, Optional
from urllib.parse import urlencode

from aiohttp import ClientSession
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
import jwt
from sqlmodel import Session, select

from app.internal.auth.config import LoginTypeEnum, auth_config
from app.internal.auth.oidc_config import InvalidOIDCConfiguration, oidc_config
from app.internal.auth.authentication import (
    DetailedUser,
    RequiresLoginException,
    authenticate_user,
    create_user,
    get_authenticated_user,
)
from app.internal.models import GroupEnum, User
from app.util.connection import get_connection
from app.util.db import get_session
from app.util.templates import templates

router = APIRouter(prefix="/auth")


@router.get("/login")
async def login(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    error: Optional[str] = None,
    redirect_uri: str = "/",
    backup: bool = False,
):
    login_type = auth_config.get(session, "login_type")
    if login_type in [LoginTypeEnum.basic, LoginTypeEnum.none]:
        return RedirectResponse(redirect_uri)
    if login_type != LoginTypeEnum.oidc and backup:
        backup = False

    try:
        await get_authenticated_user()(request, session)
        # already logged in
        return RedirectResponse(redirect_uri)
    except (HTTPException, RequiresLoginException):
        pass

    if login_type == LoginTypeEnum.oidc and not backup:
        authorize_endpoint = oidc_config.get(session, "oidc_authorize_endpoint")
        client_id = oidc_config.get(session, "oidc_client_id")
        scope = oidc_config.get(session, "oidc_scope") or "openid"
        if not authorize_endpoint:
            raise InvalidOIDCConfiguration("Missing OIDC endpoint")
        if not client_id:
            raise InvalidOIDCConfiguration("Missing OIDC client ID")

        base_url = str(request.base_url).rstrip("/")
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": f"{base_url}/auth/oidc",
            "scope": scope,
            "state": redirect_uri,
        }
        return RedirectResponse(f"{authorize_endpoint}?" + urlencode(params))

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "hide_navbar": True,
            "error": error,
            "redirect_uri": redirect_uri,
            "backup": backup,
        },
    )


@router.post("/logout")
def logout(
    request: Request, user: Annotated[DetailedUser, Depends(get_authenticated_user())]
):
    request.session["sub"] = ""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT, headers={"HX-Redirect": "/login"}
    )


@router.post("/token")
def login_access_token(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    redirect_uri: str = Form("/"),
):
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "hide_navbar": True, "error": "Invalid login"},
            block_name="error_toast",
        )

    # only admins can use the backup forms login
    login_type = auth_config.get_login_type(session)
    if login_type == LoginTypeEnum.oidc and not user.root:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "hide_navbar": True, "error": "Not root admin"},
            block_name="error_toast",
        )

    request.session["sub"] = form_data.username
    return Response(
        status_code=status.HTTP_200_OK, headers={"HX-Redirect": redirect_uri}
    )


@router.get("/oidc")
async def login_oidc(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    client_session: Annotated[ClientSession, Depends(get_connection)],
    code: str,
    state: Optional[str] = None,
):
    token_endpoint = oidc_config.get(session, "oidc_token_endpoint")
    client_id = oidc_config.get(session, "oidc_client_id")
    client_secret = oidc_config.get(session, "oidc_client_secret")
    username_claim = oidc_config.get(session, "oidc_username_claim")
    group_claim = oidc_config.get(session, "oidc_group_claim")

    if not token_endpoint:
        raise InvalidOIDCConfiguration("Missing OIDC endpoint")
    if not client_id:
        raise InvalidOIDCConfiguration("Missing OIDC client ID")
    if not client_secret:
        raise InvalidOIDCConfiguration("Missing OIDC client secret")
    if not username_claim:
        raise InvalidOIDCConfiguration("Missing OIDC username claim")
    if not group_claim:
        raise InvalidOIDCConfiguration("Missing OIDC group claim")

    base_url = str(request.base_url).rstrip("/")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": f"{base_url}/auth/oidc",
    }
    async with client_session.post(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        body = await response.json()

    id_token = body.get("id_token")
    if not id_token:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        # TODO: Verify signature
        decoded = jwt.decode(  # pyright: ignore[reportUnknownMemberType]
            id_token,
            options={"verify_signature": False},
            require=[
                username_claim,
                group_claim,
            ],  # TODO: 'require' has no effect if verify_signature is False
        )
    except jwt.InvalidTokenError as e:
        print(f"Invalid id_token: {e}")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    username = decoded.get(username_claim)
    if not username:
        raise InvalidOIDCConfiguration("Missing username claim")

    groups: list[str] | str = decoded.get(group_claim, [])
    if isinstance(groups, str):
        groups = groups.split(" ")

    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        user = create_user(
            username=username,
            # assign a random password to users created via OIDC
            password=base64.encodebytes(secrets.token_bytes(64)).decode("utf-8"),
        )

    # Don't overwrite the group if the user is root admin
    if not user.root:
        ensure_group = GroupEnum.untrusted
        for group in groups:
            if group.lower() == "admin":
                ensure_group = GroupEnum.admin
                break
            elif group.lower() == "trusted":
                ensure_group = GroupEnum.trusted
                break
            elif group.lower() == "untrusted":
                ensure_group = GroupEnum.untrusted
                break
        user.group = ensure_group
        session.add(user)
        session.commit()

    request.session["sub"] = decoded[username_claim]

    # We can't redirect server side, because that results in an infinite loop.
    # The session token is never correctly set causing any other endpoint to
    # redirect to the login page which in turn starts the OIDC flow again.
    # The redirect page allows for the cookie to properly be set on the browser
    # and then redirects client-side.
    return templates.TemplateResponse(
        "redirect.html",
        {
            "request": request,
            "hide_navbar": True,
            "redirect_uri": state or "/",
        },
    )


@router.get("/invalid-oidc")
def invalid_oidc(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    error: Optional[str] = None,
):
    if auth_config.get_login_type(session) != LoginTypeEnum.oidc:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return templates.TemplateResponse(
        "invalid_oidc.html",
        {
            "request": request,
            "error": error,
            "hide_navbar": True,
        },
        status_code=status.HTTP_200_OK,
    )
