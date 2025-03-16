import logging
from typing import Optional

from aiohttp import ClientSession
from sqlmodel import Session, select

from app.internal.models import BookRequest, EventEnum, ManualBookRequest, Notification
from app.util.db import open_session

logger = logging.getLogger(__name__)


def replace_variables(
    title_template: str,
    body_template: str,
    username: Optional[str] = None,
    book_title: Optional[str] = None,
    book_authors: Optional[str] = None,
    book_narrators: Optional[str] = None,
    event_type: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    title = title_template
    body = body_template

    if username:
        title = title.replace("{eventUser}", username)
        body = body.replace("{eventUser}", username)
    if book_title:
        title = title.replace("{bookTitle}", book_title)
        body = body.replace("{bookTitle}", book_title)
    if book_authors:
        title = title.replace("{bookAuthors}", book_authors)
        body = body.replace("{bookAuthors}", book_authors)
    if book_narrators:
        title = title.replace("{bookNarrators}", book_narrators)
        body = body.replace("{bookNarrators}", book_narrators)
    if event_type:
        title = title.replace("{eventType}", event_type)
        body = body.replace("{eventType}", event_type)

    for key, value in other_replacements.items():
        title = title.replace(f"{{{key}}}", value)
        body = body.replace(f"{{{key}}}", value)

    return title, body


async def send_all_notifications(
    event_type: EventEnum,
    requester_username: Optional[str] = None,
    book_asin: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    with open_session() as session:
        notifications = session.exec(
            select(Notification).where(Notification.event == event_type)
        ).all()
        for notification in notifications:
            await send_notification(
                session=session,
                notification=notification,
                requester_username=requester_username,
                book_asin=book_asin,
                other_replacements=other_replacements,
            )


async def send_notification(
    session: Session,
    notification: Notification,
    requester_username: Optional[str] = None,
    book_asin: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    async with ClientSession() as client_session:
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

        title, body = replace_variables(
            notification.title_template,
            notification.body_template,
            requester_username,
            book_title,
            book_authors,
            book_narrators,
            notification.event.value,
            other_replacements,
        )

        async with client_session.post(
            notification.apprise_url,
            json={
                "title": title,
                "body": body,
            },
            headers=notification.headers,
        ) as response:
            response.raise_for_status()
            return await response.json()


async def send_manual_notification(
    notification: Notification,
    book: ManualBookRequest,
    requester_username: Optional[str] = None,
    other_replacements: dict[str, str] = {},
):
    """Send a notification for manual book requests"""
    try:
        async with ClientSession() as client_session:
            title, body = replace_variables(
                notification.title_template,
                notification.body_template,
                requester_username,
                book.title,
                ",".join(book.authors),
                ",".join(book.narrators),
                notification.event.value,
                other_replacements,
            )

            async with client_session.post(
                notification.apprise_url,
                json={
                    "title": title,
                    "body": body,
                },
                headers=notification.headers,
            ) as response:
                response.raise_for_status()
                return await response.json()
    except Exception as e:
        logger.error("Failed to send notification", e)
        return None
