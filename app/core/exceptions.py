"""Application exception hierarchy and global FastAPI exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class AppError(Exception):
    """Base application error. All custom exceptions inherit from this."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        detail: Any = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str = "Resource", message: str | None = None):
        super().__init__("NOT_FOUND", message or f"{resource} not found", 404)


class ValidationError(AppError):
    def __init__(self, message: str = "Validation failed", field: str | None = None):
        super().__init__("VALIDATION_ERROR", message, 422, {"field": field})


class AuthError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__("UNAUTHORIZED", message, 401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Access denied"):
        super().__init__("FORBIDDEN", message, 403)


class ConflictError(AppError):
    def __init__(self, message: str = "Resource already exists"):
        super().__init__("CONFLICT", message, 409)


class RateLimitError(AppError):
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__("RATE_LIMITED", message, 429, {"retry_after": retry_after})


class DatabaseError(AppError):
    def __init__(self, message: str = "Database error", code: str = "DB_ERROR", detail: Any = None):
        super().__init__(code, message, 500, detail)


class ExternalServiceError(AppError):
    def __init__(self, service: str, message: str = "External service error"):
        super().__init__("EXTERNAL_ERROR", f"{service}: {message}", 502, {"service": service})


# ---------------------------------------------------------------------------
# Global FastAPI exception handlers — register via register_exception_handlers()
# ---------------------------------------------------------------------------

async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle AppError and subclasses → standard envelope."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "data": None,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "detail": exc.detail,
            },
            "meta": None,
        },
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic/FastAPI validation errors → standard envelope."""
    errors = exc.errors()
    # Sanitise errors: remove non-serialisable objects (e.g. ValueError in ctx)
    safe_errors = []
    for err in errors:
        cleaned = {k: v for k, v in err.items() if k != "ctx"}
        if "ctx" in err and isinstance(err["ctx"], dict):
            cleaned["ctx"] = {
                k: str(v) if not isinstance(v, (str, int, float, bool, list, dict, type(None))) else v
                for k, v in err["ctx"].items()
            }
        safe_errors.append(cleaned)
    first = errors[0] if errors else {}
    return JSONResponse(
        status_code=422,
        content={
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": first.get("msg", "Validation failed"),
                "field": ".".join(str(x) for x in first.get("loc", [])),
                "detail": safe_errors,
            },
            "meta": None,
        },
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions."""
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
            "meta": None,
        },
    )


def register_exception_handlers(app) -> None:
    """Register all exception handlers on a FastAPI app instance."""
    app.exception_handler(AppError)(app_error_handler)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    app.exception_handler(Exception)(generic_error_handler)
