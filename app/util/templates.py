from typing import Any, Mapping, overload
from urllib.parse import quote_plus

from fastapi import Request, Response
from jinja2_fragments.fastapi import Jinja2Blocks
from starlette.background import BackgroundTask

from app.util.auth import DetailedUser

templates = Jinja2Blocks(directory="templates")
templates.env.filters["quote_plus"] = lambda u: quote_plus(u)  # pyright: ignore[reportUnknownLambdaType,reportUnknownMemberType,reportUnknownArgumentType]


@overload
def template_response(
    name: str,
    request: Request,
    user: DetailedUser,
    context: dict[str, Any],
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
    media_type: str | None = None,
    background: BackgroundTask | None = None,
    *,
    block_names: list[str] = [],
) -> Response: ...


@overload
def template_response(
    name: str,
    request: Request,
    user: DetailedUser,
    context: dict[str, Any],
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
    media_type: str | None = None,
    background: BackgroundTask | None = None,
    *,
    block_name: str | None = None,
) -> Response: ...


def template_response(
    name: str,
    request: Request,
    user: DetailedUser,
    context: dict[str, Any],
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
    media_type: str | None = None,
    background: BackgroundTask | None = None,
    **kwargs: Any,
) -> Response:
    """Template response wrapper to make sure required arguments are passed everywhere"""
    copy = context.copy()
    copy.update({"request": request, "user": user})

    return templates.TemplateResponse(
        name=name,
        context=copy,
        status_code=status_code,
        headers=headers,
        media_type=media_type,
        background=background,
        **kwargs,
    )
