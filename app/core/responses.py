"""Standard API response envelope models and helpers."""

from pydantic import BaseModel
from typing import Generic, TypeVar, Optional, Any

from fastapi.responses import JSONResponse

T = TypeVar("T")


class PaginatedMeta(BaseModel):
    """Pagination metadata included in paginated responses."""
    page: int
    limit: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ErrorDetail(BaseModel):
    """Structured error information."""
    code: str
    message: str
    field: str | None = None
    detail: Any = None


class ApiResponse(BaseModel, Generic[T]):
    """Standard response envelope for single items."""
    data: T | None = None
    error: ErrorDetail | None = None
    meta: dict | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard response envelope for paginated lists."""
    data: list[T]
    error: ErrorDetail | None = None
    meta: PaginatedMeta


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def success(data: Any, meta: dict | None = None) -> dict:
    """Wrap data in standard success response."""
    return {"data": data, "error": None, "meta": meta}


def paginated(data: list, total: int, page: int, limit: int) -> dict:
    """Wrap paginated list in standard response."""
    total_pages = (total + limit - 1) // limit if limit > 0 else 0
    return {
        "data": data,
        "error": None,
        "meta": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }


def error_response(code: str, message: str, status_code: int = 400, detail: Any = None) -> JSONResponse:
    """Return error as JSONResponse with correct HTTP status."""
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {"code": code, "message": message, "detail": detail},
            "meta": None,
        },
    )
