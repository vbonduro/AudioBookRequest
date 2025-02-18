from typing import Annotated, Optional
from aiohttp import ClientSession
from fastapi import APIRouter, Depends, HTTPException, Request

from jinja2_fragments.fastapi import Jinja2Blocks
from sqlmodel import Session, col, select
import sqlalchemy as sa

from app.db import get_session
from app.models import (
    BookRequest,
    BookSearchResult,
    Config,
    EventEnum,
    GroupEnum,
    Notification,
    User,
)
from app.util.auth import get_authenticated_user
from app.util.book_search import (
    get_audnexus_book,
    list_audible_books,
    audible_regions,
    audible_region_type,
)
from app.util.connection import get_connection
from app.util.notifications import send_notification


router = APIRouter(prefix="/search")

templates = Jinja2Blocks(directory="templates")


@router.get("")
async def read_search(
    request: Request,
    user: Annotated[User, Depends(get_authenticated_user())],
    client_session: Annotated[ClientSession, Depends(get_connection)],
    session: Annotated[Session, Depends(get_session)],
    q: Optional[str] = None,
    num_results: int = 20,
    page: int = 0,
    region: audible_region_type = "us",
):
    if audible_regions.get(region) is None:
        raise HTTPException(status_code=400, detail="Invalid region")
    if q:
        results = await list_audible_books(
            session=session,
            client_session=client_session,
            query=q,
            num_results=num_results,
            page=page,
            audible_region=region,
        )
    else:
        results = []

    books: list[BookSearchResult] = []
    if len(results) > 0:
        # check what books are already requested by the user
        asins = {book.asin for book in results}
        requested_books = set(
            session.exec(
                select(BookRequest.asin).where(
                    col(BookRequest.asin).in_(asins),
                    BookRequest.user_username == user.username,
                )
            ).all()
        )

        for book in results:
            book_search = BookSearchResult.model_validate(book)
            if book.asin in requested_books:
                book_search.already_requested = True
            books.append(book_search)

    auto_start_download = session.exec(
        select(Config.value).where(Config.key == "auto_start_download")
    ).one_or_none()

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "search_term": q or "",
            "search_results": books,
            "regions": list(audible_regions.keys()),
            "selected_region": region,
            "page": page,
            "num_results": num_results,
            "auto_start_download": auto_start_download
            and user.is_above(GroupEnum.trusted),
        },
    )


@router.post("/request/{asin}", status_code=201)
async def add_request(
    asin: str,
    user: Annotated[User, Depends(get_authenticated_user())],
    session: Annotated[Session, Depends(get_session)],
    client_session: Annotated[ClientSession, Depends(get_connection)],
):
    book = await get_audnexus_book(client_session, asin)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    book.user_username = user.username
    try:
        session.add(book)
        session.commit()
    except sa.exc.IntegrityError:
        pass  # ignore if already exists

    notifications = session.exec(
        select(Notification).where(Notification.event == EventEnum.on_new_request)
    ).all()
    for notif in notifications:
        await send_notification(
            session=session,
            client_session=client_session,
            notification=notif,
            requester_username=user.username,
            book_asin=asin,
        )


@router.delete("/request/{asin}", status_code=204)
async def delete_request(
    asin: str,
    user: Annotated[User, Depends(get_authenticated_user())],
    session: Annotated[Session, Depends(get_session)],
):
    book = session.exec(
        select(BookRequest).where(
            BookRequest.asin == asin, BookRequest.user_username == user.username
        )
    ).one_or_none()

    if book:
        session.delete(book)
        session.commit()
