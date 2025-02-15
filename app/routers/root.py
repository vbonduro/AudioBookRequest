from typing import Annotated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from jinja2_fragments.fastapi import Jinja2Blocks

from app.util.auth import get_username

router = APIRouter()

templates = Jinja2Blocks(directory="templates")


@router.get("/globals.css")
def read_globals_css():
    return FileResponse("static/globals.css", media_type="text/css")


@router.get("/")
def read_root(request: Request, username: Annotated[str, Depends(get_username)]):
    return templates.TemplateResponse(
        "root.html", {"request": request, "username": username}
    )


@router.get("/init")
def read_init(request: Request):
    return templates.TemplateResponse("init.html", {"request": request})
