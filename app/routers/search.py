from typing import Optional
from fastapi import APIRouter, Request

from jinja2_fragments.fastapi import Jinja2Blocks

from app.util.prowlarr import query_prowlarr


router = APIRouter(prefix="/search")

templates = Jinja2Blocks(directory="templates")


@router.get("")
async def read_search(
    request: Request,
    q: Optional[str] = None,
):
    search_results = await query_prowlarr(q)

    return templates.TemplateResponse(
        "search.html",
        {"request": request, "search_term": q or "", "search_results": search_results},
    )


@router.post("/request")
async def add_request(request: Request, guid: str): ...


@router.delete("/request")
async def delete_request(request: Request, guid: str): ...
