from typing import Optional
from aiohttp import ClientSession
from sqlmodel import select

from app.db import open_session
from app.models import BookRequest, Notification


async def send_notification(
    notification: Notification,
    requester_username: Optional[str] = None,
    book_asin: Optional[str] = None,
):
    with open_session() as session:
        async with ClientSession() as client_session:
            title = notification.title_template
            body = notification.body_template

            if requester_username:
                title = title.replace("{eventUser}", requester_username)
                body = body.replace("{eventUser}", requester_username)

            if book_asin:
                book = session.exec(
                    select(BookRequest).where(BookRequest.asin == book_asin)
                ).first()
                if book:
                    title = title.replace("{bookTitle}", book.title)
                    body = body.replace("{bookTitle}", book.title)
                    title = title.replace("{bookAuthors}", ",".join(book.authors))
                    body = body.replace("{bookAuthors}", ",".join(book.authors))
                    title = title.replace("{bookNarrators}", ",".join(book.narrators))
                    body = body.replace("{bookNarrators}", ",".join(book.narrators))

            title = title.replace("{eventType}", notification.event.value)
            body = body.replace("{eventType}", notification.event.value)

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
