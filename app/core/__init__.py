"""Core infrastructure module — shared by all routers and services."""

from app.core.responses import ApiResponse, PaginatedResponse, PaginatedMeta, success, paginated, error_response
from app.core.exceptions import (
    AppError, NotFoundError, ValidationError, AuthError, ForbiddenError,
    ConflictError, RateLimitError, DatabaseError, ExternalServiceError,
)
from app.core.auth import UserContext, get_current_user, require_admin
from app.core.pagination import PaginationParams, pagination_params
from app.core.supabase_client import get_service_client, get_user_client

__all__ = [
    # Responses
    "ApiResponse", "PaginatedResponse", "PaginatedMeta",
    "success", "paginated", "error_response",
    # Exceptions
    "AppError", "NotFoundError", "ValidationError", "AuthError",
    "ForbiddenError", "ConflictError", "RateLimitError",
    "DatabaseError", "ExternalServiceError",
    # Auth
    "UserContext", "get_current_user", "require_admin",
    # Pagination
    "PaginationParams", "pagination_params",
    # Supabase
    "get_service_client", "get_user_client",
]
