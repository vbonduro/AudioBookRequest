# what is currently being queried
from contextlib import asynccontextmanager, contextmanager
from typing import Optional
from aiohttp import ClientSession
from fastapi import HTTPException
import pydantic
from sqlmodel import Session, select

from app.models import BookRequest, Indexer, ProwlarrSource
from app.util.book_search import BookResult, get_audnexus_book
from app.util.prowlarr import get_indexers, query_prowlarr
from app.db import engine
from app.util.prowlarr import prowlarr_config

querying: set[str] = set()


@contextmanager
def manage_queried(asin: str):
    querying.add(asin)
    try:
        yield
    finally:
        querying.remove(asin)


@contextmanager
def optional_session(session: Optional[Session] = None):
    if session:
        yield session
    else:
        with Session(engine) as session:
            yield session


@asynccontextmanager
async def optional_client_session(session: Optional[ClientSession] = None):
    if session:
        yield session
    else:
        async with ClientSession() as session:
            yield session


class QueryResult(pydantic.BaseModel):
    sources: list[ProwlarrSource]
    book: BookResult
    indexers: dict[int, Indexer]


async def query_sources(
    asin: str,
    force_refresh: bool = False,
    session: Optional[Session] = None,
    client_session: Optional[ClientSession] = None,
) -> QueryResult:
    with manage_queried(asin), optional_session(session) as session:
        async with optional_client_session(client_session) as client_session:
            prowlarr_config.raise_if_invalid(session)

            book = session.exec(
                select(BookRequest).where(BookRequest.asin == asin)
            ).first()
            if not book:
                raise HTTPException(status_code=404, detail="Book not found")

            book = await get_audnexus_book(client_session, asin)
            if not book:
                raise HTTPException(status_code=500, detail="Book asin error")

            query = book.title + " " + " ".join(book.authors)

            sources = await query_prowlarr(
                session,
                client_session,
                query,
                force_refresh=force_refresh,
            )

            if len(sources) > 0:
                indexers = session.exec(select(Indexer)).all()
                indexers = {indexer.id: indexer for indexer in indexers if indexer.id}
                if len(indexers) == 0:
                    indexers = await get_indexers(session, client_session)
                    for indexer in indexers.values():
                        session.add(indexer)
                    session.commit()
            else:
                indexers = {}

            sources = sorted(
                [s for s in sources if s.indexer_id in indexers],
                key=lambda x: x.seeders,
                reverse=True,
            )

            return QueryResult(
                sources=sources,
                book=book,
                indexers=indexers,
            )
