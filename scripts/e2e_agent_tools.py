#!/usr/bin/env python3
"""E2E test for all PelvibizAiAgent tools.

Calls each tool via the production chat/stream endpoint using the internal
service bypass (no JWT needed). Reports PASS/FAIL for every tool.

Usage:
    python3 scripts/e2e_agent_tools.py
"""

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

API_BASE = "https://agent-api.pelvibiz.live"
USER_ID = "3c8a1290-ff32-4ae8-9815-797d5a535dd4"
AGENT_TYPE = "pelvibiz-ai"

SUPABASE_URL = "https://lxuqjhbiumwjlbmuesmh.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imx4dXFqaGJpdW13amxibXVlc21oIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTYyNzQ0NSwiZXhwIjoyMDg3MjAzNDQ1fQ.AT1hxgdX0luR8WUNgDphvzd8j0gonzNg2UWXrs7tgUQ"
SUPABASE_EMAIL = "asepulvedadev@gmail.com"
SUPABASE_PASSWORD = "B0lsjatkvi"


def get_jwt() -> str:
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    result = client.auth.sign_in_with_password({"email": SUPABASE_EMAIL, "password": SUPABASE_PASSWORD})
    return result.session.access_token


HEADERS: dict = {}  # populated in main() after auth

# Public test image (1080x1350 Unsplash)
TEST_IMAGE_URL = "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1080&q=80"
# Public test video (short mp4)
TEST_VIDEO_URL = "https://www.w3schools.com/html/mov_bbb.mp4"


@dataclass
class ToolResult:
    tool_name: str
    trigger_message: str
    called: bool = False
    error: Optional[str] = None
    result_preview: str = ""
    duration_ms: int = 0
    raw_tool_result: dict = field(default_factory=dict)


def parse_sse_chunks(raw: str) -> list[dict]:
    """Parse Vercel AI SDK SSE format into structured chunks."""
    chunks = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        prefix, _, payload = line.partition(":")
        payload = payload.strip()
        try:
            data = json.loads(payload)
            chunks.append({"type": prefix, "data": data})
        except json.JSONDecodeError:
            pass
    return chunks


async def call_tool(client: httpx.AsyncClient, message: str, timeout: int = 60) -> tuple[list[dict], str]:
    """Send message to agent, return parsed chunks + raw response."""
    body = {"agent_type": AGENT_TYPE, "message": message}
    raw_parts = []

    async with client.stream(
        "POST",
        f"{API_BASE}/api/v1/chat/stream",
        json=body,
        headers=HEADERS,
        timeout=timeout,
    ) as resp:
        if resp.status_code != 200:
            text = await resp.aread()
            return [], text.decode()
        async for line in resp.aiter_lines():
            raw_parts.append(line)

    raw = "\n".join(raw_parts)
    return parse_sse_chunks(raw), raw


def find_tool_call(chunks: list[dict], expected_tool: str) -> Optional[dict]:
    """Find the first tool_call chunk for a specific tool."""
    for chunk in chunks:
        if chunk["type"] == "9":  # tool_call
            data = chunk["data"]
            if data.get("toolName") == expected_tool:
                return data
    return None


def find_tool_result(chunks: list[dict], tool_call_id: str) -> Optional[dict]:
    """Find the tool_result for a given tool_call_id."""
    for chunk in chunks:
        if chunk["type"] == "a":  # tool_result
            data = chunk["data"]
            if data.get("toolCallId") == tool_call_id:
                return data.get("result", {})
    return None


def has_error_event(chunks: list[dict]) -> Optional[str]:
    for chunk in chunks:
        if chunk["type"] == "3":  # error
            return str(chunk["data"])
    return None


async def test_tool(
    client: httpx.AsyncClient,
    tool_name: str,
    message: str,
    timeout: int = 45,
) -> ToolResult:
    result = ToolResult(tool_name=tool_name, trigger_message=message)
    t0 = time.monotonic()

    try:
        chunks, raw = await call_tool(client, message, timeout=timeout)
        result.duration_ms = int((time.monotonic() - t0) * 1000)

        error = has_error_event(chunks)
        if error:
            result.error = f"Agent error: {error}"
            return result

        tc = find_tool_call(chunks, tool_name)
        if tc:
            result.called = True
            tr = find_tool_result(chunks, tc.get("toolCallId", ""))
            if tr:
                result.raw_tool_result = tr
                if "error" in tr:
                    result.error = tr["error"]
                else:
                    # Summarize result
                    keys = list(tr.keys())[:4]
                    result.result_preview = ", ".join(f"{k}={repr(tr[k])[:40]}" for k in keys)
        else:
            result.error = "Tool was NOT called — agent responded without using this tool"
            # Show text response for debugging
            for chunk in chunks:
                if chunk["type"] == "0":
                    result.result_preview = str(chunk["data"])[:120]
                    break

    except httpx.TimeoutException:
        result.duration_ms = int((time.monotonic() - t0) * 1000)
        result.error = f"Timeout after {timeout}s"
    except Exception as exc:
        result.duration_ms = int((time.monotonic() - t0) * 1000)
        result.error = f"Exception: {exc}"

    return result


def print_result(r: ToolResult, idx: int, total: int):
    status = "✅ PASS" if (r.called and not r.error) else ("⚠️  CALLED+ERR" if r.called else "❌ FAIL")
    print(f"\n[{idx}/{total}] {status} — {r.tool_name} ({r.duration_ms}ms)")
    if r.result_preview:
        print(f"     → {r.result_preview}")
    if r.error:
        print(f"     ✗ {r.error}")


async def main():
    global HEADERS
    print("🔧 PelviBiz AI Agent — E2E Tool Test")
    print(f"   API: {API_BASE}")
    print(f"   User: {USER_ID}")
    print("   Authenticating...", end="", flush=True)
    token = get_jwt()
    HEADERS = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    print(" ✅")
    print("=" * 60)

    # Each entry: (tool_name, trigger_message, optional_timeout)
    tests = [
        # ── Previously failing ──────────────────────────────────────
        ("list_analyzed_accounts",   "Show me accounts I've analyzed before", 30),
        ("social_generate_ideas",    "Use social_generate_ideas tool with topic pelvic floor therapy and 4 variations", 45),
        ("social_generate_script",   "Call social_generate_script for topic: pelvic floor exercises with hook: Did you know your core and pelvic floor are connected?", 60),
        ("get_competitor_gaps",      "What content gaps do I have vs drjengunter?", 45),
        ("analyze_account_style",    "Analyze the Instagram style of @natgeo as competitor account", 90),
        ("creatomate_list_templates", "Use the creatomate_list_templates tool right now to fetch and show me every available video template", 30),
    ]

    results: list[ToolResult] = []

    async with httpx.AsyncClient(timeout=120) as client:
        for idx, (tool_name, message, timeout) in enumerate(tests, 1):
            print(f"\n[{idx}/{len(tests)}] Testing {tool_name}...", end="", flush=True)
            r = await test_tool(client, tool_name, message, timeout=timeout)
            results.append(r)
            print_result(r, idx, len(tests))
            # Small delay to avoid rate limits
            await asyncio.sleep(1)

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r.called and not r.error)
    called_with_err = sum(1 for r in results if r.called and r.error)
    not_called = sum(1 for r in results if not r.called)

    print(f"\n📊 RESULTS: {passed}/{len(results)} fully passed")
    print(f"   ✅ Pass (called + no error): {passed}")
    print(f"   ⚠️  Called but tool error:   {called_with_err}")
    print(f"   ❌ Tool not called:          {not_called}")

    if called_with_err or not_called:
        print("\n🔎 Issues:")
        for r in results:
            if r.error or not r.called:
                status = "NOT CALLED" if not r.called else "ERROR"
                print(f"   [{status}] {r.tool_name}: {r.error or 'agent did not use this tool'}")

    return 0 if (called_with_err + not_called) == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
