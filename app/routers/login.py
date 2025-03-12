from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.internal.auth.config import LoginTypeEnum, auth_config
from app.internal.auth.login import RequiresLoginException, get_authenticated_user
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
    if login_type != LoginTypeEnum.forms:
        return RedirectResponse(redirect_uri)

    try:
        await get_authenticated_user()(request, session)
        # already logged in
        return RedirectResponse(redirect_uri)
    except (HTTPException, RequiresLoginException):
        pass

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "hide_navbar": True,
            "error": error,
            "redirect_uri": redirect_uri,
        },
    )
