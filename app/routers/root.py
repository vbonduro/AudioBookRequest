import re
from typing import Annotated
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse
from jinja2_fragments.fastapi import Jinja2Blocks
from sqlmodel import Session

from app.db import get_session

from app.models import User
from app.util.auth import create_user, get_authenticated_user

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


validate_password_regex = re.compile(
    r"^(?=[^A-Z]*[A-Z])(?=[^a-z]*[a-z])(?=\D*\d).{8,}$"
)


@router.post("/init", status_code=201)
def create_init(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirm_password: Annotated[str, Form()],
    session: Annotated[Session, Depends(get_session)],
):
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if not validate_password_regex.match(password):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, and one number",
        )

    user = create_user(username, password, "admin")
    session.add(user)
    session.commit()
