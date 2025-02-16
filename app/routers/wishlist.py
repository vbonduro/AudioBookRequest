import asyncio
from typing import Annotated
from aiohttp import ClientSession
from fastapi import APIRouter, Depends, HTTPException, Request

from jinja2_fragments.fastapi import Jinja2Blocks
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import BookRequest, Indexer, User
from app.util.auth import get_authenticated_user
from app.util.book_search import get_audnexus_book
from app.util.connection import get_connection
from app.util.prowlarr import get_indexers, query_prowlarr, start_download


router = APIRouter(prefix="/wishlist")

templates = Jinja2Blocks(directory="templates")


@router.get("")
async def wishlist(
    request: Request,
    user: Annotated[User, Depends(get_authenticated_user())],
    session: Annotated[Session, Depends(get_session)],
    client_session: Annotated[ClientSession, Depends(get_connection)],
):
    book_requests = session.exec(
        select(
            BookRequest.asin, func.count(col(BookRequest.user_username)).label("count")
        )
        .select_from(BookRequest)
        .group_by(BookRequest.asin)
    ).all()

    async def get_book(asin: str, count: int):
        book = await get_audnexus_book(client_session, asin)
        if book:
            book.amount_requested = count
        return book

    coros = [get_book(asin, count) for (asin, count) in book_requests]
    books = [b for b in await asyncio.gather(*coros) if b]

    return templates.TemplateResponse(
        "wishlist.html",
        {"request": request, "books": books, "is_admin": user.is_admin()},
    )


@router.post("")
async def refresh_request(
    user: Annotated[User, Depends(get_authenticated_user("trusted"))],
    session: Annotated[Session, Depends(get_session)],
    client_session: Annotated[ClientSession, Depends(get_connection)],
):
    return {"message": "Refreshed"}


@router.get("/sources/{asin}")
async def list_sources(
    request: Request,
    asin: str,
    admin_user: Annotated[User, Depends(get_authenticated_user("admin"))],
    session: Annotated[Session, Depends(get_session)],
    client_session: Annotated[ClientSession, Depends(get_connection)],
):
    book = session.exec(select(BookRequest).where(BookRequest.asin == asin)).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    book = await get_audnexus_book(client_session, asin)
    if not book:
        raise HTTPException(status_code=500, detail="Book asin error")

    query = book.title + " " + " ".join(book.authors)
    sources = await query_prowlarr(query)

    if len(sources) > 0:
        indexers = session.exec(select(Indexer)).all()
        indexers = {indexer.id: indexer for indexer in indexers}
        if len(indexers) == 0:
            indexers = await get_indexers(client_session)
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

    return templates.TemplateResponse(
        "sources.html",
        {
            "request": request,
            "book": book,
            "sources": sources,
            "indexers": indexers,
        },
    )


@router.post("/sources/{asin}")
async def download_book(
    asin: str,
    guid: str,
    indexer_id: int,
    admin_user: Annotated[User, Depends(get_authenticated_user("admin"))],
    session: Annotated[Session, Depends(get_session)],
    client_session: Annotated[ClientSession, Depends(get_connection)],
):
    resp = await start_download(client_session, guid, indexer_id)
    if not resp.ok:
        raise HTTPException(status_code=500, detail="Failed to start download")

    book = session.exec(select(BookRequest).where(BookRequest.asin == asin)).all()
    for b in book:
        session.delete(b)

    session.commit()
