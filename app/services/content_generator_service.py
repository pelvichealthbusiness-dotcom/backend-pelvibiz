"""Generic CRUD service for content generator tables — Batch 2d."""

from __future__ import annotations

import logging
from typing import Any

from app.core.supabase_client import get_service_client
from app.core.pagination import PaginationParams

logger = logging.getLogger(__name__)

# Allowed tables and their owner column (user_id or via run join)
ALLOWED_TABLES: dict[str, str] = {
    "runns": "user_id",
    "seo_output": "run_id",
    "blog_output": "run_id",
    "podcast_output": "run_id",
    "yt_longform": "run_id",
    "ig_carousels": "run_id",
    "ig_reels": "run_id",
    "linkedin_output": "run_id",
    "keywords": "run_id",
}

# Tables that have a direct user_id column
DIRECT_USER_TABLES = {"runns"}


class ContentGeneratorService:
    """Generic CRUD for content generator tables."""

    def __init__(self):
        self.supabase = get_service_client()

    def _validate_table(self, table: str) -> None:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Table {table} is not allowed. Valid: {sorted(ALLOWED_TABLES.keys())}")

    async def _get_user_run_ids(self, user_id: str) -> list[str]:
        """Get all run_ids belonging to a user from the runns table."""
        result = (
            self.supabase.table("runns")
            .select("run_id")
            .eq("user_id", user_id)
            .execute()
        )
        return [r["run_id"] for r in (result.data or []) if r.get("run_id")]

    async def list_items(
        self,
        table: str,
        user_id: str,
        pagination: PaginationParams,
    ) -> tuple[list[dict], int]:
        """List items from a content generator table, scoped to user."""
        self._validate_table(table)

        if table in DIRECT_USER_TABLES:
            # Direct user_id filter
            query = (
                self.supabase.table(table)
                .select("*", count="exact")
                .eq("user_id", user_id)
            )
        else:
            # Filter by run_ids belonging to user
            run_ids = await self._get_user_run_ids(user_id)
            if not run_ids:
                return [], 0
            query = (
                self.supabase.table(table)
                .select("*", count="exact")
                .in_("run_id", run_ids)
            )

        # Apply sorting
        query = query.order(pagination.sort_by, desc=(pagination.order == "desc"))

        # Apply pagination
        query = query.range(pagination.offset, pagination.offset + pagination.limit - 1)

        result = query.execute()
        total = result.count if result.count is not None else len(result.data or [])
        return result.data or [], total

    async def create_item(self, table: str, user_id: str, data: dict) -> dict:
        """Create an item in a content generator table."""
        self._validate_table(table)

        # For runns, set user_id directly
        if table in DIRECT_USER_TABLES:
            data["user_id"] = user_id
        else:
            # For output tables, verify the run_id belongs to the user
            run_id = data.get("run_id")
            if not run_id:
                raise ValueError("run_id is required for output tables")
            run_ids = await self._get_user_run_ids(user_id)
            if run_id not in run_ids:
                raise PermissionError("run_id does not belong to the current user")

        # Remove id if present (auto-generated)
        data.pop("id", None)

        result = self.supabase.table(table).insert(data).execute()
        return result.data[0] if result.data else data

    async def delete_item(self, table: str, user_id: str, item_id: str) -> bool:
        """Delete an item, verifying ownership."""
        self._validate_table(table)

        if table in DIRECT_USER_TABLES:
            # Direct ownership check
            result = (
                self.supabase.table(table)
                .delete()
                .eq("id", item_id)
                .eq("user_id", user_id)
                .execute()
            )
        else:
            # Verify via run_id ownership
            run_ids = await self._get_user_run_ids(user_id)
            if not run_ids:
                return False
            result = (
                self.supabase.table(table)
                .delete()
                .eq("id", item_id)
                .in_("run_id", run_ids)
                .execute()
            )

        return bool(result.data)
