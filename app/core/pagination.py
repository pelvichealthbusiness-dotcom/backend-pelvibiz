"""Reusable pagination dependency for FastAPI routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query


@dataclass
class PaginationParams:
    """Parsed pagination parameters."""
    page: int
    limit: int
    offset: int
    sort_by: str
    order: str  # "asc" | "desc"


def pagination_params(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("created_at", description="Field to sort by"),
    order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order"),
) -> PaginationParams:
    """Reusable FastAPI dependency for pagination query params."""
    return PaginationParams(
        page=page,
        limit=limit,
        offset=(page - 1) * limit,
        sort_by=sort_by,
        order=order,
    )
