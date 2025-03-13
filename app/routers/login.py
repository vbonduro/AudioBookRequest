from typing import Annotated, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.internal.auth.config import LoginTypeEnum, auth_config
from app.internal.auth.login import RequiresLoginException, get_authenticated_user
from app.internal.auth.oidc_config import InvalidOIDCConfiguration, oidc_config
from app.util.db import get_session
from app.util.templates import templates

router = APIRouter(prefix="/login")


@router.get("")
async def login(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    error: Optional[str] = None,
    redirect_uri: str = "/",
):
    login_type = auth_config.get(session, "login_type")
    if login_type in [LoginTypeEnum.basic, LoginTypeEnum.none]:
        return RedirectResponse(redirect_uri)

    try:
        await get_authenticated_user()(request, session)
        # already logged in
        return RedirectResponse(redirect_uri)
    except (HTTPException, RequiresLoginException):
        pass

    if login_type == LoginTypeEnum.oidc:
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
        },
    )
