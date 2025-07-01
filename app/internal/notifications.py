import json
from typing import Optional

from aiohttp import ClientSession
from sqlmodel import Session, select

from app.internal.models import (
    BookRequest,
    EventEnum,
    ManualBookRequest,
    Notification,
    NotificationServiceEnum,
)
from app.util import json_type
from app.util.db import open_session
from app.util.log import logger


def replace_variables(
    template: str,
    username: Optional[str] = None,
    book_title: Optional[str] = None,
    book_authors: Optional[str] = None,
    book_narrators: Optional[str] = None,
    event_type: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    if username:
        template = template.replace("{eventUser}", username)
    if book_title:
        template = template.replace("{bookTitle}", book_title)
    if book_authors:
        template = template.replace("{bookAuthors}", book_authors)
    if book_narrators:
        template = template.replace("{bookNarrators}", book_narrators)
    if event_type:
        template = template.replace("{eventType}", event_type)

    for key, value in other_replacements.items():
        template = template.replace(f"{{{key}}}", value)

    return template


async def _send(
    title: str,
    body: str,
    additional_fields: dict[str, json_type.JSON],
    notification: Notification,
    client_session: ClientSession,
):
    match notification.service:
        case NotificationServiceEnum.gotify:
            body_key = "message"
        case NotificationServiceEnum.apprise:
            body_key = "body"
        case NotificationServiceEnum.custom:
            body_key = ""

    if notification.service == NotificationServiceEnum.custom:
        json_body = {}
    else:
        json_body: dict[str, json_type.JSON] = {
            "title": title,
            body_key: body,
        }

    for key, value in additional_fields.items():
        if key in json_body.keys():
            logger.warning(
                "Key already exists in JSON body. Overwriting with value.",
                key=key,
                value=value,
            )
        json_body[key] = value

    print(json_body)

    async with client_session.post(
        notification.url,
        json=json_body,
        headers=notification.headers,
    ) as response:
        response.raise_for_status()
        return await response.json()


async def send_notification(
    session: Session,
    notification: Notification,
    requester_username: Optional[str] = None,
    book_asin: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    book_title = None
    book_authors = None
    book_narrators = None
    if book_asin:
        book = session.exec(
            select(BookRequest).where(BookRequest.asin == book_asin)
        ).first()
        if book:
            book_title = book.title
            book_authors = ",".join(book.authors)
            book_narrators = ",".join(book.narrators)

    title = replace_variables(
        notification.title_template,
        requester_username,
        book_title,
        book_authors,
        book_narrators,
        notification.event.value,
        other_replacements,
    )
    body = replace_variables(
        notification.body_template,
        requester_username,
        book_title,
        book_authors,
        book_narrators,
        notification.event.value,
        other_replacements,
    )
    additional_fields: dict[str, json_type.JSON] = json.loads(
        replace_variables(
            json.dumps(notification.additional_fields),
            requester_username,
            book_title,
            book_authors,
            book_narrators,
            notification.event.value,
            other_replacements,
        )
    )

    logger.info(
        "Sending notification",
        url=notification.url,
        title=title,
        event_type=notification.event.value,
    )

    async with ClientSession() as client_session:
        return await _send(title, body, additional_fields, notification, client_session)


async def send_all_notifications(
    event_type: EventEnum,
    requester_username: Optional[str] = None,
    book_asin: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    with open_session() as session:
        notifications = session.exec(
            select(Notification).where(
                Notification.event == event_type, Notification.enabled
            )
        ).all()
        for notification in notifications:
            await send_notification(
                session=session,
                notification=notification,
                requester_username=requester_username,
                book_asin=book_asin,
                other_replacements=other_replacements,
            )


async def send_manual_notification(
    notification: Notification,
    book: ManualBookRequest,
    requester_username: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    """Send a notification for manual book requests"""
    try:
        book_authors = ",".join(book.authors)
        book_narrators = ",".join(book.narrators)

        title = replace_variables(
            notification.title_template,
            requester_username,
            book.title,
            book_authors,
            book_narrators,
            notification.event.value,
            other_replacements,
        )
        body = replace_variables(
            notification.body_template,
            requester_username,
            book.title,
            book_authors,
            book_narrators,
            notification.event.value,
            other_replacements,
        )
        additional_fields: dict[str, json_type.JSON] = json.loads(
            replace_variables(
                json.dumps(notification.additional_fields),
                requester_username,
                book.title,
                book_authors,
                book_narrators,
                notification.event.value,
                other_replacements,
            )
        )

        logger.info(
            "Sending manual notification",
            url=notification.url,
            title=title,
            event_type=notification.event.value,
        )

        async with ClientSession() as client_session:
            await _send(title, body, additional_fields, notification, client_session)

    except Exception as e:
        logger.error("Failed to send notification", error=str(e))
        return None


async def send_all_manual_notifications(
    event_type: EventEnum,
    book_request: ManualBookRequest,
    other_replacements: dict[str, str] = {},
):
    with open_session() as session:
        notifications = session.exec(
            select(Notification).where(
                Notification.event == event_type, Notification.enabled
            )
        ).all()
        for notif in notifications:
            await send_manual_notification(
                notification=notif,
                book=book_request,
                requester_username=book_request.user_username,
                other_replacements=other_replacements,
            )
