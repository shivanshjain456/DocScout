#!/usr/bin/env python
"""Setup tooling (NOT feature code): probe an MCP server and dump its full tool list.

Purpose: guardrail §1.1 requires reading EVERY tool description before approving a server.
This performs a real MCP handshake (initialize -> tools/list) and prints server info plus
each tool's name and full description, so the descriptions can be audited for injected
imperatives ("ignore previous instructions", "send to <url>", "read ~/.ssh", ...).

Usage:
  uv run --with mcp scripts/mcp_probe.py stdio  <name> -- <command> [args...]
  uv run --with mcp scripts/mcp_probe.py http   <name> <url>

Tool-call mode (§6.2 requires one real call per server); CALLS is a JSON list of
{"tool": ..., "args": {...}} executed in order:
  MCP_CALLS='[{"tool":"read_graph","args":{}}]' uv run ... scripts/mcp_probe.py stdio <name> -- <cmd>
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any

# Heuristic red flags for tool-poisoning (Invariant Labs, Apr 2025).
SUSPICIOUS = [
    r"ignore (all )?previous",
    r"\bdo not (tell|mention|inform)\b",
    r"\bexfiltrat",
    r"~/\.ssh",
    r"id_rsa",
    r"\.env\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bbase64\b",
    r"send (it|this|the) .{0,30}(to|via)",
    r"<IMPORTANT>",
    r"\bsidenote\b",
    r"\bapi[_ -]?key\b",
    r"\bsecret\b",
    r"\btoken\b",
]


def audit(text: str) -> list[str]:
    return [p for p in SUSPICIOUS if re.search(p, text or "", re.IGNORECASE)]


async def probe(mode: str, name: str, target: list[str]) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    if mode == "stdio":
        params = StdioServerParameters(command=target[0], args=target[1:])
        ctx = stdio_client(params)
    else:
        # SDK >=2.x renamed this from `streamablehttp_client` to `streamable_http_client`.
        from mcp.client.streamable_http import streamable_http_client

        ctx = streamable_http_client(target[0])

    async with ctx as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"=== MCP server: {name} ===")
            print(f"serverInfo : {init.server_info.name} v{init.server_info.version}")
            print(f"protocol   : {init.protocol_version}")
            print(f"capabilities: {init.capabilities.model_dump(exclude_none=True)}")
            print()

            tools = (await session.list_tools()).tools
            print(f"--- tools/list : {len(tools)} tools ---")
            flagged: dict[str, Any] = {}
            for t in tools:
                desc = (t.description or "").strip()
                hits = audit(desc)
                if hits:
                    flagged[t.name] = hits
                print(f"\n* {t.name}")
                print(f"  {desc}")
                if hits:
                    print(f"  !! RED-FLAG PATTERNS: {hits}")

            print("\n--- guardrail §1.1 audit summary ---")
            print(f"tools scanned      : {len(tools)}")
            print(f"tools with flags   : {len(flagged)}")
            print(f"flag detail        : {json.dumps(flagged, indent=2) if flagged else 'none'}")

            calls = json.loads(os.environ.get("MCP_CALLS", "[]"))
            for spec in calls:
                tool, args = spec["tool"], spec.get("args", {})
                print(f"\n--- tools/call: {tool}({json.dumps(args)[:120]}) ---")
                res = await session.call_tool(tool, args, read_timeout_seconds=120.0)
                print(f"is_error: {res.is_error}")
                for block in res.content:
                    text = getattr(block, "text", None)
                    if text is not None:
                        print(text[:1500])
                    else:
                        print(f"[{block.type} block] {str(block)[:200]}")
            return 0


def main() -> int:
    mode, name, *rest = sys.argv[1:]
    target = rest[1:] if rest and rest[0] == "--" else rest
    try:
        return asyncio.run(asyncio.wait_for(probe(mode, name, target), timeout=180))
    except Exception as exc:  # noqa: BLE001 - this is a probe; report, never crash silently
        import traceback

        print(f"PROBE FAILED for {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        if isinstance(exc, BaseExceptionGroup):
            for i, sub in enumerate(exc.exceptions):
                print(f"--- sub-exception {i}: {type(sub).__name__}: {sub}")
                traceback.print_exception(type(sub), sub, sub.__traceback__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
