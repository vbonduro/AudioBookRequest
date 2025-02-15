

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from jinja2_fragments.fastapi import Jinja2Blocks

router = APIRouter()

templates = Jinja2Blocks(directory="templates")

@router.get("/globals.css")
def read_globals_css():
    return FileResponse("static/globals.css")

@router.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("root.html", {"request": request, "magic_number": 30})
