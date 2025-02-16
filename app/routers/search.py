from sqlite3 import IntegrityError
from typing import Annotated, Optional
from aiohttp import ClientSession
from fastapi import APIRouter, Depends, HTTPException, Request

from jinja2_fragments.fastapi import Jinja2Blocks
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import BookRequest, User
from app.util.auth import get_authenticated_user
from app.util.book_search import (
    list_audible_books,
    audible_regions,
    audible_region_type,
)
from app.util.connection import get_connection


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
        search_results = await list_audible_books(
            session=client_session,
            query=q,
            num_results=num_results,
            page=page,
            audible_region=region,
        )
    else:
        search_results = []

    # check what books are already requested by the user
    asins = [book.asin for book in search_results]
    requested_books = set(
        session.exec(
            select(BookRequest.asin).where(
                col(BookRequest.asin).in_(asins),
                BookRequest.user_username == user.username,
            )
        ).all()
    )
    for book in search_results:
        if book.asin in requested_books:
            book.already_requested = True

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "search_term": q or "",
            "search_results": search_results,
            "regions": list(audible_regions.keys()),
            "selected_region": region,
            "page": page,
            "num_results": num_results,
        },
    )


@router.post("/request", status_code=201)
async def add_request(
    asin: str,
    user: Annotated[User, Depends(get_authenticated_user())],
    session: Annotated[Session, Depends(get_session)],
):
    req = BookRequest(
        asin=asin,
        user_username=user.username,
    )
    try:
        session.add(req)
        session.commit()
    except IntegrityError:
        pass


@router.delete("/request", status_code=204)
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
