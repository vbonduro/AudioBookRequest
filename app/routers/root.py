from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session

from app.internal.auth.config import LoginTypeEnum, auth_config
from app.internal.auth.authentication import (
    DetailedUser,
    create_user,
    get_authenticated_user,
    raise_for_invalid_password,
)
from app.internal.models import GroupEnum
from app.util.db import get_session
from app.util.templates import templates

router = APIRouter()


root = Path("static")


@router.get("/static/globals.css")
def read_globals_css():
    return FileResponse(root / "globals.css", media_type="text/css")


@router.get("/static/nouislider.css")
def read_nouislider_css():
    return FileResponse(root / "nouislider.min.css", media_type="text/css")


@router.get("/static/nouislider.js")
def read_nouislider_js():
    return FileResponse(root / "nouislider.min.js", media_type="text/javascript")


@router.get("/static/apple-touch-icon.png")
def read_apple_touch_icon():
    return FileResponse(root / "apple-touch-icon.png", media_type="image/png")


@router.get("/static/favicon-32x32.png")
def read_favicon_32():
    return FileResponse(root / "favicon-32x32.png", media_type="image/png")


@router.get("/static/favicon-16x16.png")
def read_favicon_16():
    return FileResponse(root / "favicon-16x16.png", media_type="image/png")


@router.get("/static/site.webmanifest")
def read_site_webmanifest():
    return FileResponse(
        root / "site.webmanifest", media_type="application/manifest+json"
    )


@router.get("/static/htmx.js")
def read_htmx():
    return FileResponse(root / "htmx.js", media_type="application/javascript")


@router.get("/static/htmx-preload.js")
def read_htmx_preload():
    return FileResponse(root / "htmx-preload.js", media_type="application/javascript")


@router.get("/static/alpine.js")
def read_alpinejs():
    return FileResponse(root / "alpine.js", media_type="application/javascript")


@router.get("/static/favicon.svg")
def read_favicon_svg():
    return FileResponse(root / "favicon.svg", media_type="image/svg+xml")


@router.get("/")
def read_root(
    request: Request,
    user: Annotated[DetailedUser, Depends(get_authenticated_user())],
):
    return RedirectResponse("/search")
    # TODO: create a root page
    # return templates.TemplateResponse(
    #     "root.html",
    #     {"request": request, "user": user},
    # )


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
        raise_for_invalid_password(session, password, confirm_password)
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
def redirect_login(request: Request):
    return RedirectResponse("/auth/login?" + urlencode(request.query_params))
