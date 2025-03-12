from typing import Annotated, Optional

from aiohttp import ClientSession
from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from app.internal.auth.login import (
    DetailedUser,
    authenticate_user,
    get_authenticated_user,
)
from app.internal.env_settings import Settings
from app.util.connection import get_connection
from app.util.db import get_session
from app.util.templates import templates

router = APIRouter(prefix="/auth")


@router.post("/logout")
def logout(
    request: Request, user: Annotated[DetailedUser, Depends(get_authenticated_user())]
):
    request.session["sub"] = ""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT, headers={"HX-Redirect": "/login"}
    )


@router.post("/token")
def login_access_token(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    redirect_uri: str = Form("/"),
):
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "hide_navbar": True, "error": "Invalid login"},
            block_name="error_toast",
        )

    request.session["sub"] = form_data.username
    return Response(
        status_code=status.HTTP_200_OK, headers={"HX-Redirect": redirect_uri}
    )


@router.get("/oidc")
async def login_oidc(
    request: Request,
    client_session: Annotated[ClientSession, Depends(get_connection)],
    code: str,
    state: Optional[str] = None,
):
    endpoint = Settings().oidc.endpoint.rstrip("/")
    client_id = Settings().oidc.client_id
    client_secret = Settings().oidc.client_secret
    username_claim = Settings().oidc.username_claim

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": f"{Settings().app.public_host}/auth/oidc",  # TODO: is this even required?
    }
    # TODO: get endpoint from .well-known
    async with client_session.post(
        endpoint + "/token/",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ) as response:
        body = await response.json()
        print(body)

    # TODO: validate the token and extract username and group claims
    access_token = body["access_token"]
    id_token = body["id_token"]
    # return RedirectResponse(state or "/")
