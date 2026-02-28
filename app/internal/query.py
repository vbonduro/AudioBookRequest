# what is currently being queried
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Literal, Optional

import pydantic
from aiohttp import ClientSession
from fastapi import HTTPException
from sqlmodel import Session, select

from app.internal.models import BookRequest, ProwlarrSource
from app.internal.prowlarr.prowlarr import (
    prowlarr_config,
    query_prowlarr,
    start_download,
)
from app.internal.ranking.download_ranking import CompareSource, rank_sources
from app.util.log import logger

_BACKOFF_BASE_MINUTES = 15
_BACKOFF_MAX_MINUTES = 24 * 60  # 24 hours

querying: set[str] = set()


@contextmanager
def manage_queried(asin: str):
    querying.add(asin)
    try:
        yield
    finally:
        try:
            querying.remove(asin)
        except KeyError:
            pass


class QueryResult(pydantic.BaseModel):
    sources: Optional[list[ProwlarrSource]]
    book: BookRequest
    state: Literal["ok", "querying", "uncached"]
    query_used: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.state == "ok"


async def query_sources(
    asin: str,
    session: Session,
    client_session: ClientSession,
    requester_username: str,
    force_refresh: bool = False,
    start_auto_download: bool = False,
    only_return_if_cached: bool = False,
    custom_query: Optional[str] = None,
    reset_backoff: bool = False,
) -> QueryResult:
    book = session.exec(select(BookRequest).where(BookRequest.asin == asin)).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Reset backoff if requested (e.g. manual retry)
    if reset_backoff:
        logger.info(
            "Resetting backoff for book",
            asin=asin,
            previous_attempts=book.search_attempts,
            previous_next_search_at=str(book.next_search_at),
        )
        for b in session.exec(select(BookRequest).where(BookRequest.asin == asin)).all():
            b.search_attempts = 0
            b.next_search_at = None
            session.add(b)
        session.commit()

    # Determine the query to use
    query_to_use = custom_query if custom_query else book.title + " " + book.authors[0]

    if asin in querying:
        return QueryResult(
            sources=None,
            book=book,
            state="querying",
            query_used=query_to_use,
        )

    with manage_queried(asin):
        prowlarr_config.raise_if_invalid(session)

        sources = await query_prowlarr(
            session,
            client_session,
            book,
            query_to_use,
            force_refresh=force_refresh,
            only_return_if_cached=only_return_if_cached,
            indexer_ids=prowlarr_config.get_indexers(session),
        )
        if sources is None:
            return QueryResult(
                sources=None,
                book=book,
                state="uncached",
                query_used=query_to_use,
            )

        ranked = await rank_sources(session, client_session, sources, book)

        # start download if requested
        if start_auto_download and not book.downloaded:
            compare = CompareSource(session, book)
            valid_ranked = [rs for rs in ranked if compare.is_valid_quality(rs)]
            logger.info(
                "Auto-download ranking complete",
                asin=asin,
                title=book.title,
                total_ranked=len(ranked),
                valid_ranked=len(valid_ranked),
                sources=[
                    {"title": rs.source.title, "format": rs.quality.file_format, "kbits": rs.quality.kbits}
                    for rs in ranked
                ],
            )
            if len(valid_ranked) > 0:
                top = valid_ranked[0].source
                logger.info(
                    "Auto-download selecting top-ranked source",
                    asin=asin,
                    title=book.title,
                    source_title=top.title,
                    indexer=top.indexer,
                    guid=top.guid,
                    protocol=top.protocol,
                    publish_date=str(top.publish_date),
                    total_ranked=len(ranked),
                    valid_ranked=len(valid_ranked),
                )
                resp, source_title = await start_download(
                    session=session,
                    client_session=client_session,
                    guid=top.guid,
                    indexer_id=top.indexer_id,
                    requester_username=requester_username,
                    book_asin=asin,
                    source_title=top.title,
                )
                if resp.ok:
                    for b in session.exec(
                        select(BookRequest).where(BookRequest.asin == asin)
                    ).all():
                        b.downloaded = True
                        b.downloaded_file = source_title
                        session.add(b)
                    session.commit()
                else:
                    raise HTTPException(status_code=500, detail="Failed to start download")
            else:
                # No valid sources found — update backoff for all matching books
                attempts = book.search_attempts + 1
                interval_minutes = min(_BACKOFF_BASE_MINUTES * (2 ** attempts), _BACKOFF_MAX_MINUTES)
                next_search_at = datetime.now() + timedelta(minutes=interval_minutes)
                logger.info(
                    "No sources found for auto-download, scheduling retry",
                    asin=asin,
                    title=book.title,
                    attempt=attempts,
                    next_search_at=str(next_search_at),
                    interval_minutes=interval_minutes,
                )
                for b in session.exec(
                    select(BookRequest).where(BookRequest.asin == asin)
                ).all():
                    b.search_attempts = attempts
                    b.next_search_at = next_search_at
                    session.add(b)
                session.commit()

        return QueryResult(
            sources=[rs.source for rs in ranked],
            book=book,
            state="ok",
            query_used=query_to_use,
        )
