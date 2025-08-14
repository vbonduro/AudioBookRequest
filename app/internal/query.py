# what is currently being queried
from contextlib import contextmanager
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
from app.internal.ranking.download_ranking import rank_sources

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
) -> QueryResult:
    book = session.exec(select(BookRequest).where(BookRequest.asin == asin)).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

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
        if start_auto_download and not book.downloaded and len(ranked) > 0:
            resp = await start_download(
                session=session,
                client_session=client_session,
                guid=ranked[0].guid,
                indexer_id=ranked[0].indexer_id,
                requester_username=requester_username,
                book_asin=asin,
            )
            if resp.ok:
                same_books = session.exec(
                    select(BookRequest).where(BookRequest.asin == asin)
                ).all()
                for b in same_books:
                    b.downloaded = True
                    session.add(b)
                session.commit()
            else:
                raise HTTPException(status_code=500, detail="Failed to start download")

        return QueryResult(
            sources=ranked,
            book=book,
            state="ok",
            query_used=query_to_use,
        )
