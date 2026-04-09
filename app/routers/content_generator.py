"""Content generator CRUD endpoints — Batch 2d.

Generic router that serves multiple content generator tables
(runns, seo_output, blog_output, podcast_output, yt_longform,
ig_carousels, ig_reels, linkedin_output, keywords).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from app.core.auth import get_current_user, UserContext
from app.core.pagination import PaginationParams, pagination_params
from app.core.responses import success, paginated, error_response
from app.services.content_generator_service import (
    ContentGeneratorService,
    ALLOWED_TABLES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content-generator", tags=["content-generator"])

_VALID_TABLES_STR = ", ".join(sorted(ALLOWED_TABLES.keys()))


def _validate_table_param(table: str) -> str:
    """Validate the table path parameter."""
    if table not in ALLOWED_TABLES:
        raise ValueError(table)
    return table


@router.get("/{table}")
async def list_items(
    table: str = Path(..., description=f"Table name. Valid: {_VALID_TABLES_STR}"),
    user: UserContext = Depends(get_current_user),
    pagination: PaginationParams = Depends(pagination_params),
):
    """List items from a content generator table (paginated, user-scoped)."""
    if table not in ALLOWED_TABLES:
        return error_response(
            "INVALID_TABLE",
            f"Table {table} is not valid. Allowed: {_VALID_TABLES_STR}",
            status_code=400,
        )

    service = ContentGeneratorService()
    try:
        items, total = await service.list_items(table, user.user_id, pagination)
    except Exception as exc:
        logger.error("Error listing %s: %s", table, exc)
        return error_response("LIST_ERROR", str(exc), status_code=500)

    return paginated(data=items, total=total, page=pagination.page, limit=pagination.limit)


@router.post("/{table}")
async def create_item(
    body: dict,
    table: str = Path(..., description=f"Table name. Valid: {_VALID_TABLES_STR}"),
    user: UserContext = Depends(get_current_user),
):
    """Create an item in a content generator table."""
    if table not in ALLOWED_TABLES:
        return error_response(
            "INVALID_TABLE",
            f"Table {table} is not valid. Allowed: {_VALID_TABLES_STR}",
            status_code=400,
        )

    service = ContentGeneratorService()
    try:
        item = await service.create_item(table, user.user_id, body)
    except ValueError as exc:
        return error_response("VALIDATION_ERROR", str(exc), status_code=400)
    except PermissionError as exc:
        return error_response("FORBIDDEN", str(exc), status_code=403)
    except Exception as exc:
        logger.error("Error creating in %s: %s", table, exc)
        return error_response("CREATE_ERROR", str(exc), status_code=500)

    return success(data=item)


@router.delete("/{table}/{item_id}")
async def delete_item(
    table: str = Path(..., description=f"Table name. Valid: {_VALID_TABLES_STR}"),
    item_id: str = Path(..., description="Item UUID"),
    user: UserContext = Depends(get_current_user),
):
    """Delete an item from a content generator table (ownership verified)."""
    if table not in ALLOWED_TABLES:
        return error_response(
            "INVALID_TABLE",
            f"Table {table} is not valid. Allowed: {_VALID_TABLES_STR}",
            status_code=400,
        )

    service = ContentGeneratorService()
    try:
        deleted = await service.delete_item(table, user.user_id, item_id)
    except Exception as exc:
        logger.error("Error deleting from %s: %s", table, exc)
        return error_response("DELETE_ERROR", str(exc), status_code=500)

    if not deleted:
        return error_response("NOT_FOUND", "Item not found or not owned by you", status_code=404)

    return success(data={"deleted": True, "id": item_id})
