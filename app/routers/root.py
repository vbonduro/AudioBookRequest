from datetime import timedelta
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from jinja2_fragments.fastapi import Jinja2Blocks
from sqlmodel import Session

from app.db import get_session

from app.models import GroupEnum
from app.util.auth import (
    DetailedUser,
    LoginTypeEnum,
    RequiresLoginException,
    authenticate_user,
    create_access_token,
    create_user,
    get_authenticated_user,
    raise_for_invalid_password,
    auth_config,
)

router = APIRouter()

templates = Jinja2Blocks(directory="templates")


@router.get("/globals.css")
def read_globals_css():
    return FileResponse("static/globals.css", media_type="text/css")


@router.get("/")
def read_root(
    request: Request,
    user: Annotated[DetailedUser, Depends(get_authenticated_user())],
):
    return templates.TemplateResponse(
        "root.html",
        {"request": request, "user": user},
    )


@router.get("/init")
def read_init(request: Request):
    return templates.TemplateResponse(
        "init.html", {"request": request, "hide_navbar": True}
    )


@router.post("/init")
def create_init(
    request: Request,
    login_type: Annotated[LoginTypeEnum, Form()],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
):
    if username.strip() == "":
        return templates.TemplateResponse(
            "init.html",
            {"request": request, "error": "Invalid username"},
            block_name="init_messages",
        )

    try:
        raise_for_invalid_password(password, confirm_password)
    except HTTPException as e:
        return templates.TemplateResponse(
            "init.html",
            {"request": request, "error": e.detail},
            block_name="init_messages",
        )

    user = create_user(username, password, GroupEnum.admin, root=True)
    session.add(user)
    auth_config.set_login_type(session, login_type)
    session.commit()

    return Response(status_code=201, headers={"HX-Redirect": "/"})


@router.get("/login")
async def login(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    error: Optional[str] = None,
):
    login_type = auth_config.get(session, "login_type")
    if login_type != LoginTypeEnum.forms:
        return RedirectResponse("/")

    try:
        await get_authenticated_user()(request, session)
        # already logged in
        return RedirectResponse("/")
    except (HTTPException, RequiresLoginException):
        pass

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "hide_navbar": True, "error": error},
    )


@router.post("/auth/logout")
def logout(user: Annotated[DetailedUser, Depends(get_authenticated_user())]):
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            "Set-Cookie": "audio_sess=; Path=/; SameSite=Strict; HttpOnly; Expires=Thu, 01 Jan 1970 00:00:00 GMT",
            "HX-Redirect": "/login",
        },
    )


@router.post("/auth/token")
def login_access_token(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
):
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "hide_navbar": True, "error": "Invalid login"},
            block_name="error_message",
        )

    access_token_expires_minues = auth_config.get_access_token_expiry_minutes(session)
    access_token_exires = timedelta(minutes=access_token_expires_minues)
    access_token = create_access_token(
        auth_config.get_auth_secret(session),
        {"sub": form_data.username},
        access_token_exires,
    )

    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "HX-Redirect": "/",
            "Set-Cookie": f"audio_sess={access_token}; Path=/; SameSite=Strict; HttpOnly; ",
        },
    )
