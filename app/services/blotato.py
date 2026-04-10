from __future__ import annotations


def build_blotato_connections(profile: dict | None = None) -> dict | None:
    """Return structured Blotato connections, falling back to legacy IDs."""
    p = profile or {}
    connections = p.get("blotato_connections") or {}
    if connections:
        return connections

    legacy: dict[str, dict[str, str]] = {}
    if p.get("blotato_ig_id"):
        legacy["instagram"] = {"accountId": p.get("blotato_ig_id")}
    if p.get("blotato_fb_account_id") or p.get("blotato_fb_id"):
        legacy["facebook"] = {
            **({"accountId": p.get("blotato_fb_account_id")} if p.get("blotato_fb_account_id") else {}),
            **({"pageId": p.get("blotato_fb_id")} if p.get("blotato_fb_id") else {}),
        }
    return legacy or None
