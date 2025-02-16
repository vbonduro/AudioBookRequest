from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import select
from app.db import get_session
from app.models import User
from app.routers import root, search, settings, wishlist

app = FastAPI()

app.include_router(root.router)
app.include_router(search.router)
app.include_router(wishlist.router)
app.include_router(settings.router)

user_exists = False


@app.middleware("http")
async def redirect_to_init(request: Request, call_next: Any):
    """
    Initial redirect if no user exists. We force the user to create a new login
    """
    global user_exists
    if (
        not user_exists
        and request.url.path not in ["/init", "/globals.css"]
        and request.method == "GET"
    ):
        session = next(get_session())
        user_count = session.exec(select(func.count()).select_from(User)).one()
        if user_count == 0:
            return RedirectResponse("/init")
        else:
            user_exists = True
    elif user_exists and request.url.path.startswith("/init"):
        return RedirectResponse("/")
    response = await call_next(request)
    return response
