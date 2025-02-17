# what is currently being queried
from contextlib import contextmanager
from aiohttp import ClientSession
from fastapi import HTTPException
import pydantic
from sqlmodel import Session, select

from app.models import BookRequest, Indexer, ProwlarrSource
from app.util.prowlarr import get_indexers, query_prowlarr
from app.util.prowlarr import prowlarr_config

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
    indexers: dict[int, Indexer]


async def query_sources(
    asin: str,
    session: Session,
    client_session: ClientSession,
    force_refresh: bool = False,
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
