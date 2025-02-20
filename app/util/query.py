# what is currently being queried
from contextlib import contextmanager
from aiohttp import ClientSession
from fastapi import HTTPException
import pydantic
from sqlmodel import Session, select

from app.models import BookRequest, Indexer, ProwlarrSource
from app.util.ranking.download_ranking import rank_sources
from app.util.prowlarr import get_indexers, query_prowlarr, start_download
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

        ranked = await rank_sources(session, client_session, sources, book)

        # start download if requested
        if (
            start_auto_download
            and not book.downloaded
            and len(ranked) > 0
            and ranked[0].download_score > 0
        ):
            resp = await start_download(
                session, client_session, ranked[0].guid, ranked[0].indexer_id
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
            indexers=indexers,
        )
