from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware import Middleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import select

from app.internal.auth.login import RequiresLoginException, auth_config
from app.internal.auth.session_middleware import (
    DynamicSessionMiddleware,
    middleware_linker,
)
from app.internal.env_settings import Settings
from app.internal.models import User
from app.routers import auth, login, root, search, settings, wishlist
from app.util.db import open_session

with open_session() as session:
    auth_secret = auth_config.get_auth_secret(session)

app = FastAPI(
    title="AudioBookRequest",
    debug=Settings().app.debug,
    openapi_url="/openapi.json" if Settings().app.openapi_enabled else None,
    middleware=[
        Middleware(DynamicSessionMiddleware, auth_secret, middleware_linker),
        Middleware(GZipMiddleware),
    ],
)

app.include_router(auth.router)
app.include_router(login.router)
app.include_router(root.router)
app.include_router(search.router)
app.include_router(settings.router)
app.include_router(wishlist.router)

user_exists = False


@app.exception_handler(RequiresLoginException)
async def redirect_to_login(request: Request, exc: RequiresLoginException):
    if request.method == "GET":
        params: dict[str, str] = {}
        if exc.detail:
            params["error"] = exc.detail
        path = request.url.path
        if path != "/" and not path.startswith("/login"):
            params["redirect_uri"] = path
        return RedirectResponse("/login?" + urlencode(params))
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
        with open_session() as session:
            user_count = session.exec(select(func.count()).select_from(User)).one()
            if user_count == 0:
                return RedirectResponse("/init")
            else:
                user_exists = True
    elif user_exists and request.url.path.startswith("/init"):
        return RedirectResponse("/")
    response = await call_next(request)
    return response
