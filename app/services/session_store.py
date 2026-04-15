"""Session storage backends for Instagram Instaloader sessions."""

from __future__ import annotations

import asyncio
import base64
import os
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

_loop_executor = None


def _get_executor():
    return None  # Use default ThreadPoolExecutor


class SessionStore(ABC):
    """Abstract base for Instagram session storage."""

    @abstractmethod
    async def save(self, user_id: str, data: bytes) -> None:
        ...

    @abstractmethod
    async def load(self, user_id: str) -> bytes | None:
        ...

    @abstractmethod
    async def delete(self, user_id: str) -> None:
        ...

    @abstractmethod
    async def exists(self, user_id: str) -> bool:
        ...


class FileSessionStore(SessionStore):
    """File-system session store. One file per user."""

    def __init__(self, session_dir: str) -> None:
        self._session_dir = session_dir
        os.makedirs(session_dir, mode=0o700, exist_ok=True)

    def _path(self, user_id: str) -> str:
        return os.path.join(self._session_dir, f"{user_id}.session")

    async def save(self, user_id: str, data: bytes) -> None:
        path = self._path(user_id)
        loop = asyncio.get_event_loop()

        def _write():
            os.makedirs(self._session_dir, mode=0o700, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, 0o600)

        await loop.run_in_executor(None, _write)
        logger.debug("Session saved to %s", path)

    async def load(self, user_id: str) -> bytes | None:
        path = self._path(user_id)
        loop = asyncio.get_event_loop()

        def _read():
            if not os.path.exists(path):
                return None
            with open(path, "rb") as f:
                return f.read()

        data = await loop.run_in_executor(None, _read)
        return data

    async def delete(self, user_id: str) -> None:
        path = self._path(user_id)
        loop = asyncio.get_event_loop()

        def _remove():
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

        await loop.run_in_executor(None, _remove)

    async def exists(self, user_id: str) -> bool:
        path = self._path(user_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, os.path.exists, path)


class DbSessionStore(SessionStore):
    """Supabase-backed session store with AES-256-GCM encryption."""

    def __init__(self, supabase_client: "Client", encryption_key: str) -> None:
        if not encryption_key:
            raise ValueError("IG_ENCRYPTION_KEY not configured")
        self._supabase = supabase_client
        self._key = bytes.fromhex(encryption_key)  # 32 bytes

    def _encrypt(self, data: bytes) -> bytes:
        aesgcm = AESGCM(self._key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext  # prepend nonce

    def _decrypt(self, stored: bytes) -> bytes:
        nonce = stored[:12]
        ciphertext = stored[12:]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    async def save(self, user_id: str, data: bytes) -> None:
        loop = asyncio.get_event_loop()

        def _upsert():
            encrypted = self._encrypt(data)
            blob = base64.b64encode(encrypted).decode()
            self._supabase.table("profiles").upsert(
                {"id": user_id, "ig_session_blob": blob},
                on_conflict="id",
            ).execute()

        await loop.run_in_executor(None, _upsert)
        logger.debug("Session saved to DB for user %s", user_id)

    async def load(self, user_id: str) -> bytes | None:
        loop = asyncio.get_event_loop()

        def _select():
            result = (
                self._supabase.table("profiles")
                .select("ig_session_blob")
                .eq("id", user_id)
                .maybe_single()
                .execute()
            )
            return result.data

        row = await loop.run_in_executor(None, _select)
        if not row or not row.get("ig_session_blob"):
            return None

        stored = base64.b64decode(row["ig_session_blob"])
        return self._decrypt(stored)

    async def delete(self, user_id: str) -> None:
        loop = asyncio.get_event_loop()

        def _nullify():
            self._supabase.table("profiles").update(
                {"ig_session_blob": None}
            ).eq("id", user_id).execute()

        await loop.run_in_executor(None, _nullify)

    async def exists(self, user_id: str) -> bool:
        loop = asyncio.get_event_loop()

        def _check():
            result = (
                self._supabase.table("profiles")
                .select("ig_session_blob")
                .eq("id", user_id)
                .maybe_single()
                .execute()
            )
            return bool(result.data and result.data.get("ig_session_blob") is not None)

        return await loop.run_in_executor(None, _check)


def create_session_store(settings) -> SessionStore:
    """Factory: returns the right SessionStore implementation based on settings."""
    backend = getattr(settings, "ig_session_backend", "file")

    if backend == "db":
        from app.core.supabase_client import get_service_client
        client = get_service_client()
        return DbSessionStore(
            supabase_client=client,
            encryption_key=settings.ig_encryption_key,
        )

    # Default: file
    session_dir = getattr(settings, "ig_session_dir", "/tmp/pelvibiz_ig_sessions")
    return FileSessionStore(session_dir=session_dir)
