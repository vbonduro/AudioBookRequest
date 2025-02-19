import json
from typing import Annotated, Any, Optional, cast
import uuid
from aiohttp import ClientResponseError, ClientSession
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlmodel import Session, select

from app.db import get_session

from app.models import EventEnum, Notification, User, GroupEnum
from app.util.auth import (
    DetailedUser,
    create_user,
    get_authenticated_user,
    is_correct_password,
    raise_for_invalid_password,
)
from app.util.connection import get_connection
from app.util.notifications import send_notification
from app.util.prowlarr import prowlarr_config
from app.util.templates import template_response

router = APIRouter(prefix="/settings")


@router.get("/account")
def read_account(
    request: Request,
    user: Annotated[DetailedUser, Depends(get_authenticated_user())],
):
    return template_response(
        "settings_page/account.html", request, user, {"page": "account"}
    )


@router.post("/account/password")
def change_password(
    request: Request,
    old_password: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[DetailedUser, Depends(get_authenticated_user())],
):
    if not is_correct_password(user, old_password):
        return template_response(
            "settings_page/account.html",
            request,
            user,
            {
                "page": "account",
                "error": "Old password is wrong",
            },
            block_name="change_pw_messages",
        )
    try:
        raise_for_invalid_password(password, confirm_password)
    except HTTPException as e:
        return template_response(
            "settings_page/account.html",
            request,
            user,
            {"page": "account", "error": e.detail},
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
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
    session: Annotated[Session, Depends(get_session)],
):
    users = session.exec(select(User)).all()
    return template_response(
        "settings_page/users.html",
        request,
        admin_user,
        {"page": "users", "users": users},
    )


@router.post("/user")
def create_new_user(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    group: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
):
    if username.strip() == "":
        return template_response(
            "settings_page/users.html",
            request,
            admin_user,
            {"error": "Invalid username"},
            block_name="create_user_messages",
        )

    try:
        raise_for_invalid_password(password, ignore_confirm=True)
    except HTTPException as e:
        return template_response(
            "settings_page/users.html",
            request,
            admin_user,
            {"error": e.detail},
            block_name="create_user_messages",
        )

    if group not in GroupEnum.__members__:
        return template_response(
            "settings_page/users.html",
            request,
            admin_user,
            {"error": "Invalid group selected"},
            block_name="create_user_messages",
        )

    group = GroupEnum[group]

    user = session.exec(select(User).where(User.username == username)).first()
    if user:
        return template_response(
            "settings_page/users.html",
            request,
            admin_user,
            {"error": "Username already exists"},
            block_name="create_user_messages",
        )

    user = create_user(username, password, group)
    session.add(user)
    session.commit()

    users = session.exec(select(User)).all()

    return template_response(
        "settings_page/users.html",
        request,
        admin_user,
        {"users": users},
        block_name="user_block",
        headers={"HX-Retarget": "#user-list"},
    )


@router.delete("/user")
def delete_user(
    request: Request,
    username: str,
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
):
    if username == admin_user.username:
        return template_response(
            "settings_page/users.html",
            request,
            admin_user,
            {"error": "Cannot delete own user"},
            block_name="delete_user_messages",
        )

    user = session.exec(select(User).where(User.username == username)).one_or_none()
    if user and user.root:
        return template_response(
            "settings_page/users.html",
            request,
            admin_user,
            {"error": "Cannot delete root user"},
            block_name="delete_user_messages",
        )

    if user:
        session.delete(user)
        session.commit()

    users = session.exec(select(User)).all()

    return template_response(
        "settings_page/users.html",
        request,
        admin_user,
        {"users": users},
        block_name="user_block",
        headers={"HX-Retarget": "#user-list"},
    )


@router.get("/prowlarr")
def read_prowlarr(
    request: Request,
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
    session: Annotated[Session, Depends(get_session)],
    prowlarr_misconfigured: Optional[Any] = None,
):
    prowlarr_base_url = prowlarr_config.get_base_url(session)
    prowlarr_api_key = prowlarr_config.get_api_key(session)

    return template_response(
        "settings_page/prowlarr.html",
        request,
        admin_user,
        {
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
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
):
    prowlarr_config.set_api_key(session, api_key)
    session.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.put("/prowlarr/base-url")
def update_prowlarr_base_url(
    base_url: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
):
    prowlarr_config.set_base_url(session, base_url)
    session.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.get("/download")
def read_download(
    request: Request,
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
):
    return template_response(
        "settings_page/download.html", request, admin_user, {"page": "download"}
    )


@router.get("/notifications")
def read_notifications(
    request: Request,
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
    session: Annotated[Session, Depends(get_session)],
):
    notifications = session.exec(select(Notification)).all()
    return template_response(
        "settings_page/notifications.html",
        request,
        admin_user,
        {"page": "notifications", "notifications": notifications},
    )


@router.post("/notification")
def add_notification(
    request: Request,
    name: Annotated[str, Form()],
    apprise_url: Annotated[str, Form()],
    title_template: Annotated[str, Form()],
    body_template: Annotated[str, Form()],
    event: Annotated[str, Form()],
    headers: Annotated[str, Form()],
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
    session: Annotated[Session, Depends(get_session)],
):
    if not headers:
        headers = "{}"
    try:
        headers_json = json.loads(headers)
        if not isinstance(headers_json, dict) or any(
            not isinstance(v, str) for v in cast(dict[str, Any], headers_json).values()
        ):
            raise ValueError()
        headers_json = cast(dict[str, str], headers_json)
    except (json.JSONDecodeError, ValueError):
        return template_response(
            "settings_page/notifications.html",
            request,
            admin_user,
            {"page": "notifications", "error": "Invalid headers JSON"},
            block_name="form_error",
        )

    try:
        event_enum = EventEnum(event)
    except ValueError:
        return template_response(
            "settings_page/notifications.html",
            request,
            admin_user,
            {"page": "notifications", "error": "Invalid event type"},
            block_name="form_error",
        )

    notification = Notification(
        name=name,
        apprise_url=apprise_url,
        event=event_enum,
        title_template=title_template,
        body_template=body_template,
        headers=headers_json,
        enabled=True,
    )
    session.add(notification)
    session.commit()

    notifications = session.exec(select(Notification)).all()

    return template_response(
        "settings_page/notifications.html",
        request,
        admin_user,
        {"page": "notifications", "notifications": notifications},
        block_name="notfications_block",
        headers={"HX-Retarget": "#notification-list"},
    )


@router.delete("/notification/{notification_id}")
def delete_notification(
    request: Request,
    notification_id: uuid.UUID,
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
    session: Annotated[Session, Depends(get_session)],
):
    notifications = session.exec(select(Notification)).all()
    for notif in notifications:
        if notif.id == notification_id:
            print("DELETED")
            session.delete(notif)
            session.commit()
            break
    notifications = session.exec(select(Notification)).all()

    return template_response(
        "settings_page/notifications.html",
        request,
        admin_user,
        {"page": "notifications", "notifications": notifications},
        block_name="notfications_block",
    )


@router.post("/notification/{notification_id}")
async def execute_notification(
    notification_id: uuid.UUID,
    admin_user: Annotated[
        DetailedUser, Depends(get_authenticated_user(GroupEnum.admin))
    ],
    session: Annotated[Session, Depends(get_session)],
    client_session: Annotated[ClientSession, Depends(get_connection)],
):
    notification = session.exec(
        select(Notification).where(Notification.id == notification_id)
    ).one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    try:
        await send_notification(session, client_session, notification)
    except ClientResponseError:
        raise HTTPException(status_code=500, detail="Failed to send notification")

    return Response(status_code=204)
