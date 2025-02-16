from typing import Annotated, Any, Optional
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from jinja2_fragments.fastapi import Jinja2Blocks
from sqlmodel import Session, select

from app.db import get_session

from app.models import Config, User, GroupEnum
from app.util.auth import (
    create_user,
    get_authenticated_user,
    raise_for_invalid_password,
)

router = APIRouter(prefix="/settings")

templates = Jinja2Blocks(directory="templates")
templates.env.filters["quote_plus"] = lambda u: quote_plus(u)  # pyright: ignore[reportUnknownLambdaType,reportUnknownMemberType,reportUnknownArgumentType]


@router.get("/")
def read_settings(
    request: Request,
    user: Annotated[User, Depends(get_authenticated_user())],
    session: Annotated[Session, Depends(get_session)],
    prowlarr_misconfigured: Optional[Any] = None,
):
    if user.is_admin():
        users = session.exec(select(User)).all()
    else:
        users = []

    prowlarr_base_url = session.exec(
        select(Config.value).where(Config.key == "prowlarr_base_url")
    ).one_or_none()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "prowlarr_base_url": prowlarr_base_url or "",
            "prowlarr_misconfigured": True if prowlarr_misconfigured else False,
        },
    )


@router.post("/user")
def create_new_user(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    group: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if group not in GroupEnum.__members__:
        raise HTTPException(status_code=400, detail="Invalid group")
    group = GroupEnum[group]

    raise_for_invalid_password(password)

    user = session.exec(select(User).where(User.username == username)).first()
    if user:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = create_user(username, password, group)
    session.add(user)
    session.commit()

    users = session.exec(select(User)).all()

    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "user": user, "users": users},
        block_name="user_block",
    )


@router.delete("/user")
def delete_user(
    request: Request,
    username: str,
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    if username == admin_user.username:
        raise HTTPException(status_code=400, detail="Cannot delete own user")

    user = session.exec(select(User).where(User.username == username)).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    session.delete(user)
    session.commit()

    users = session.exec(select(User)).all()

    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "user": user, "users": users},
        block_name="user_block",
    )


@router.post("/password")
def change_password(
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_authenticated_user())],
):
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    raise_for_invalid_password(password)

    new_user = create_user(user.username, password, user.group)

    user.password = new_user.password
    session.add(user)
    session.commit()

    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.put("/prowlarr/api-key")
def update_prowlarr_api_key(
    api_key: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    config = session.exec(
        select(Config).where(Config.key == "prowlarr_api_key")
    ).one_or_none()
    if config:
        config.value = api_key
    else:
        config = Config(key="prowlarr_api_key", value=api_key)
    session.add(config)
    session.commit()

    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.put("/prowlarr/base-url")
def update_prowlarr_base_url(
    base_url: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[User, Depends(get_authenticated_user(GroupEnum.admin))],
):
    config = session.exec(
        select(Config).where(Config.key == "prowlarr_base_url")
    ).one_or_none()

    base_url = base_url.strip("/")

    if config:
        config.value = base_url
    else:
        config = Config(key="prowlarr_base_url", value=base_url)
    session.add(config)
    session.commit()

    return Response(status_code=204, headers={"HX-Refresh": "true"})
