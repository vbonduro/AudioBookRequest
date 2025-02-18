from typing import Annotated, Any, Optional
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from jinja2_fragments.fastapi import Jinja2Blocks
from sqlmodel import Session, select

from app.db import get_session

from app.models import User, GroupEnum
from app.util.auth import (
    create_user,
    get_authenticated_user,
    is_correct_password,
    raise_for_invalid_password,
)
from app.util.prowlarr import prowlarr_config

router = APIRouter(prefix="/settings")

templates = Jinja2Blocks(directory="templates")
templates.env.filters["quote_plus"] = lambda u: quote_plus(u)  # pyright: ignore[reportUnknownLambdaType,reportUnknownMemberType,reportUnknownArgumentType]


@router.get("/account")
def read_account(
    request: Request,
    user: Annotated[User, Depends(get_authenticated_user())],
):
    return templates.TemplateResponse(
        "settings_page/account.html",
        {"request": request, "user": user, "page": "account"},
    )


@router.post("/account/password")
def change_password(
    request: Request,
    old_password: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_authenticated_user())],
):
    if not is_correct_password(user, old_password):
        return templates.TemplateResponse(
            "settings_page/account.html",
            {
                "request": request,
                "user": user,
                "page": "account",
                "error": "Old password is wrong",
            },
            block_name="change_pw_messages",
        )
    try:
        raise_for_invalid_password(password, confirm_password)
    except HTTPException as e:
        return templates.TemplateResponse(
            "settings_page/account.html",
            {"request": request, "user": user, "page": "account", "error": e.detail},
            block_name="change_pw_messages",
        )

    new_user = create_user(user.username, password, user.group)

    user.password = new_user.password
    session.add(user)
    session.commit()

    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.get("/users")
def read_users(
    request: Request,
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
    session: Annotated[Session, Depends(get_session)],
):
    users = session.exec(select(User)).all()
    return templates.TemplateResponse(
        "settings_page/users.html",
        {"request": request, "user": admin_user, "page": "users", "users": users},
    )


@router.post("/user")
def create_new_user(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    group: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    if username.strip() == "":
        return templates.TemplateResponse(
            "settings_page/users.html",
            {"request": request, "user": admin_user, "error": "Invalid username"},
            block_name="create_user_messages",
        )

    try:
        raise_for_invalid_password(password, ignore_confirm=True)
    except HTTPException as e:
        return templates.TemplateResponse(
            "settings_page/users.html",
            {"request": request, "user": admin_user, "error": e.detail},
            block_name="create_user_messages",
        )

    if group not in GroupEnum.__members__:
        return templates.TemplateResponse(
            "settings_page/users.html",
            {"request": request, "user": admin_user, "error": "Invalid group selected"},
            block_name="create_user_messages",
        )

    group = GroupEnum[group]

    user = session.exec(select(User).where(User.username == username)).first()
    if user:
        return templates.TemplateResponse(
            "settings_page/users.html",
            {
                "request": request,
                "user": admin_user,
                "error": "Username already exists",
            },
            block_name="create_user_messages",
        )

    user = create_user(username, password, group)
    session.add(user)
    session.commit()

    users = session.exec(select(User)).all()

    return templates.TemplateResponse(
        "settings_page/users.html",
        {"request": request, "user": admin_user, "users": users},
        block_name="user_block",
        headers={"HX-Retarget": "#user-list"},
    )


@router.delete("/user")
def delete_user(
    request: Request,
    username: str,
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    if username == admin_user.username:
        return templates.TemplateResponse(
            "settings_page/users.html",
            {"request": request, "user": admin_user, "error": "Cannot delete own user"},
            block_name="delete_user_messages",
        )

    user = session.exec(select(User).where(User.username == username)).one_or_none()
    if user and user.root:
        return templates.TemplateResponse(
            "settings_page/users.html",
            {
                "request": request,
                "user": admin_user,
                "error": "Cannot delete root user",
            },
            block_name="delete_user_messages",
        )

    if user:
        session.delete(user)
        session.commit()

    users = session.exec(select(User)).all()

    return templates.TemplateResponse(
        "settings_page/users.html",
        {"request": request, "user": admin_user, "users": users},
        block_name="user_block",
        headers={"HX-Retarget": "#user-list"},
    )


@router.get("/prowlarr")
def read_prowlarr(
    request: Request,
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
    session: Annotated[Session, Depends(get_session)],
    prowlarr_misconfigured: Optional[Any] = None,
):
    prowlarr_base_url = prowlarr_config.get_base_url(session)
    prowlarr_api_key = prowlarr_config.get_api_key(session)

    return templates.TemplateResponse(
        "settings_page/prowlarr.html",
        {
            "request": request,
            "user": admin_user,
            "page": "prowlarr",
            "prowlarr_base_url": prowlarr_base_url or "",
            "prowlarr_api_key": prowlarr_api_key,
            "prowlarr_misconfigured": True if prowlarr_misconfigured else False,
        },
    )


@router.put("/prowlarr/api-key")
def update_prowlarr_api_key(
    api_key: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    prowlarr_config.set_api_key(session, api_key)
    session.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.put("/prowlarr/base-url")
def update_prowlarr_base_url(
    base_url: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    prowlarr_config.set_base_url(session, base_url)
    session.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.get("/download")
def read_download(
    request: Request,
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    return templates.TemplateResponse(
        "settings_page/download.html",
        {"request": request, "user": admin_user, "page": "download"},
    )


@router.get("/notifications")
def read_notifications(
    request: Request,
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    return templates.TemplateResponse(
        "settings_page/notifications.html",
        {"request": request, "user": admin_user, "page": "notifications"},
    )
