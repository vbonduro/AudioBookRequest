from typing import Annotated
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse
from jinja2_fragments.fastapi import Jinja2Blocks
from sqlmodel import Session

from app.db import get_session

from app.models import User, GroupEnum
from app.util.auth import (
    create_user,
    get_authenticated_user,
    raise_for_invalid_password,
)

router = APIRouter()

templates = Jinja2Blocks(directory="templates")


@router.get("/globals.css")
def read_globals_css():
    return FileResponse("static/globals.css", media_type="text/css")


@router.get("/")
def read_root(
    request: Request,
    user: Annotated[User, Depends(get_authenticated_user())],
):
    return templates.TemplateResponse(
        "root.html", {"request": request, "username": user.username}
    )


@router.get("/init")
def read_init(request: Request):
    return templates.TemplateResponse("init.html", {"request": request})


@router.post("/init")
def create_init(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
):
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    raise_for_invalid_password(password)

    user = create_user(username, password, GroupEnum.admin)
    session.add(user)
    session.commit()

    return Response(status_code=201, headers={"HX-Redirect": "/"})
