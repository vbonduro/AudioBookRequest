# what is currently being queried
from contextlib import contextmanager
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

from app.internal.indexers.mam import MamIndexer
from app.internal.indexers.base import BaseIndexer
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
    sources: list[ProwlarrSource]
    book: BookRequest


async def query_sources(
    asin: str,
    session: Session,
    client_session: ClientSession,
    requester_username: str,
    force_refresh: bool = False,
    start_auto_download: bool = False,
) -> QueryResult:
    with manage_queried(asin):
        prowlarr_config.raise_if_invalid(session)

        book = session.exec(select(BookRequest).where(BookRequest.asin == asin)).first()
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        book = session.exec(select(BookRequest).where(BookRequest.asin == asin)).first()
        if not book:
            raise HTTPException(status_code=500, detail="Book asin error")

        query = book.title + " " + " ".join(book.authors)

        sources = await query_prowlarr(
            session,
            client_session,
            query,
            force_refresh=force_refresh,
        )
        # TODO: Maybe move this list somewhere configurable?
        # We have to list all possible types of indexers since there is no common superclass.
        indexers: list[MamIndexer | BaseIndexer[str]] = [MamIndexer(session)]
        for indexer in indexers:
            if indexer.is_active() and indexer.valid_config():
                sources = await indexer.enrichResults(client_session, query, sources)
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
        )
