"""Gemini client singleton using the google-genai SDK.

Usage::

    from app.core.gemini_client import get_gemini_client

    client = get_gemini_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Hello",
    )
"""

from google import genai

from app.config import get_settings

_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    """Return a lazily-initialised Gemini client (singleton).

    The client is created once on first call and reused thereafter.
    Thread-safe because Python's GIL guarantees atomic assignment of
    module-level variables, and the worst case of a race is a harmless
    double-init that overwrites the same value.
    """
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(api_key=settings.google_api_key)
    return _client
