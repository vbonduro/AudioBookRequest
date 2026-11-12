from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import aiohttp
from aiohttp import ClientSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.internal.download_backend import get_download_backend
from app.internal.models import Audiobook, AudiobookRequest, GroupEnum, User
from app.internal.prowlarr.util import prowlarr_config
from app.internal.query import query_sources, schedule_retry
from app.internal.ranking.quality import quality_config
from app.util.db import get_session
from app.util.log import logger

SCHEDULER_INTERVAL_MINUTES = 15


def get_due_books(session: Session, now: datetime) -> list[Audiobook]:
    """Unfulfilled books wanted by a user whose requests may be fetched automatically."""
    return list(
        session.exec(
            select(Audiobook)
            .join(AudiobookRequest, col(AudiobookRequest.asin) == col(Audiobook.asin))
            .join(User, col(User.username) == col(AudiobookRequest.user_username))
            .where(col(Audiobook.fulfilled).is_(False))
            .where(col(User.group).in_([GroupEnum.trusted, GroupEnum.admin]))
            .where(
                or_(
                    col(Audiobook.next_search_at).is_(None),
                    col(Audiobook.next_search_at) <= now,
                )
            )
            .distinct()
        ).all()
    )


async def retry_due_books() -> None:
    """Search again for requested books that no earlier search could fulfil."""
    try:
        with next(get_session()) as session:
            if not quality_config.get_auto_download(session):
                return
            if get_download_backend(session) != "prowlarr":
                return
            if not prowlarr_config.is_valid(session):
                return

            books = get_due_books(session, datetime.now(UTC))
            if not books:
                logger.debug("Scheduler: no books due for a search")
                return
            logger.info("Scheduler: searching for books", count=len(books))

            # Read the keys now: each search commits, which expires the loaded books
            asins = [book.asin for book in books]
            async with ClientSession(timeout=aiohttp.ClientTimeout(60)) as client:
                for asin in asins:
                    await _retry_book(session, client, asin)
    except Exception as e:
        logger.error("Scheduler run failed", error=str(e))


async def _retry_book(
    session: Session, client_session: ClientSession, asin: str
) -> None:
    try:
        await query_sources(
            asin_or_uuid=asin,
            session=session,
            client_session=client_session,
            # a cached result would hide releases that appeared since the last try
            force_refresh=True,
            start_auto_download=True,
        )
    except HTTPException as e:
        logger.error("Scheduled search failed", asin=asin, error=e.detail)
    except Exception as e:
        logger.error("Scheduled search crashed", asin=asin, error=str(e))
    else:
        return

    # A failure that leaves the book unfulfilled must still back off, or it would be
    # retried (and could fire notifications) on every run.
    session.rollback()
    book = session.get(Audiobook, asin)
    if book is not None and not book.fulfilled:
        schedule_retry(session, book)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _ = app
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        retry_due_books,
        "interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
