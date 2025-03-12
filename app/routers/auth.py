from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session

from app.internal.auth.login import (
    DetailedUser,
    authenticate_user,
    get_authenticated_user,
)
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
