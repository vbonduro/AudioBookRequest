import asyncio
from datetime import datetime

from aiohttp import ClientSession
from sqlmodel import col, select

from app.internal.models import BookRequest, GroupEnum, User
from app.internal.query import query_sources
from app.internal.ranking.quality import quality_config
from app.util.db import open_session
from app.util.log import logger

SCHEDULER_INTERVAL_MINUTES = 15


async def run_auto_download_scheduler() -> None:
    """Background task that periodically searches for and downloads wishlist books."""
    while True:
        logger.info("Scheduler woke up, checking wishlist books")
        try:
            await _check_wishlist_books()
        except Exception as e:
            logger.error("Scheduler error during wishlist check", error=str(e))
        await asyncio.sleep(SCHEDULER_INTERVAL_MINUTES * 60)


async def _check_wishlist_books() -> None:
    with open_session() as session:
        if not quality_config.get_auto_download(session):
            logger.info("Scheduler skipping: auto-download is disabled")
            return
        if not quality_config.get_scheduler_enabled(session):
            logger.info("Scheduler skipping: scheduler is disabled")
            return

        now = datetime.now()
        books = session.exec(
            select(BookRequest)
            .join(User, BookRequest.user_username == User.username)  # type: ignore[arg-type]
            .where(col(BookRequest.downloaded) == False)  # noqa: E712
            .where(col(BookRequest.user_username).is_not(None))
            .where(col(User.group).in_([GroupEnum.trusted, GroupEnum.admin]))
            .where(
                col(BookRequest.next_search_at).is_(None)
                | (col(BookRequest.next_search_at) <= now)
            )
        ).all()

        # Deduplicate by asin
        seen_asins: set[str] = set()
        unique_books: list[BookRequest] = []
        for book in books:
            if book.asin not in seen_asins:
                seen_asins.add(book.asin)
                unique_books.append(book)

        if not unique_books:
            logger.info("Scheduler: no books due for retry")
            return

        logger.info("Scheduler processing books", count=len(unique_books))

        async with ClientSession() as client_session:
            for book in unique_books:
                logger.info(
                    "Scheduler attempting auto-download",
                    asin=book.asin,
                    title=book.title,
                    search_attempts=book.search_attempts,
                )
                try:
                    result = await query_sources(
                        asin=book.asin,
                        session=session,
                        client_session=client_session,
                        requester_username="scheduler",
                        start_auto_download=True,
                    )
                    logger.info(
                        "Scheduler finished book",
                        asin=book.asin,
                        title=book.title,
                        sources_found=len(result.sources) if result.sources else 0,
                        downloaded=result.book.downloaded,
                        next_search_at=str(result.book.next_search_at),
                    )
                except Exception as e:
                    logger.error(
                        "Scheduler failed to process book",
                        asin=book.asin,
                        title=book.title,
                        error=str(e),
                    )
