from app.models.brand import REGENERABLE_FIELDS


class AgentAPIError(Exception):
    """Base exception for all API errors."""
    def __init__(self, message: str, code: str, status_code: int = 500, details: dict | None = None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class AuthError(AgentAPIError):
    def __init__(self, message: str = "Authentication failed", code: str = "UNAUTHORIZED"):
        super().__init__(message=message, code=code, status_code=401)


class TokenExpiredError(AuthError):
    def __init__(self):
        super().__init__(message="Token expired or invalid", code="TOKEN_EXPIRED")


class CreditsExhaustedError(AgentAPIError):
    def __init__(self, credits_used: int, credits_limit: int):
        super().__init__(
            message=f"Credits exhausted: {credits_used}/{credits_limit}",
            code="CREDITS_EXHAUSTED",
            status_code=403,
            details={"credits_used": credits_used, "credits_limit": credits_limit},
        )


class GeminiError(AgentAPIError):
    def __init__(self, message: str = "Gemini API error", details: dict | None = None):
        super().__init__(message=message, code="GEMINI_ERROR", status_code=502, details=details)


class ImageDownloadError(AgentAPIError):
    def __init__(self, url: str, reason: str = "timeout"):
        super().__init__(
            message=f"Failed to download image: {reason}",
            code="IMAGE_DOWNLOAD_FAILED",
            status_code=408,
            details={"url": url, "reason": reason},
        )


class StorageUploadError(AgentAPIError):
    def __init__(self, path: str, reason: str):
        super().__init__(
            message=f"Storage upload failed: {reason}",
            code="STORAGE_UPLOAD_FAILED",
            status_code=500,
            details={"path": path, "reason": reason},
        )


class LLMError(AgentAPIError):
    def __init__(self, message: str = "LLM service unavailable"):
        super().__init__(message=message, code="LLM_UNAVAILABLE", status_code=502)


class ProfileGenerationError(AgentAPIError):
    def __init__(self, message: str = "Profile generation failed", details: dict | None = None):
        super().__init__(message=message, code="PROFILE_GENERATION_FAILED", status_code=502, details=details)


class InvalidFieldError(AgentAPIError):
    def __init__(self, field_name: str):
        super().__init__(
            message=f"Invalid field for regeneration: {field_name}",
            code="INVALID_FIELD",
            status_code=400,
            details={"field_name": field_name, "allowed_fields": list(REGENERABLE_FIELDS)},
        )


class IdeasGenerationError(AgentAPIError):
    def __init__(self, message: str = "Ideas generation failed", details: dict | None = None):
        super().__init__(message=message, code="IDEAS_GENERATION_FAILED", status_code=502, details=details)
