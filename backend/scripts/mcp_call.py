"""Call one GrowthLoop MCP tool over stdio and print the result as JSON.

Test-only helper for the Playwright suite: Playwright runs in Node and cannot
import the Python MCP SDK, so it shells out to this script to drive the real
MCP server process against the same database as the e2e backend.

Usage:
    python scripts/mcp_call.py <tool> '<json-arguments>'

The ``DATABASE_URL`` environment variable selects the database. On success
the structured tool result is printed to stdout as JSON; tool errors are
printed to stderr and the process exits non-zero.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from mcp import Client, StdioServerParameters  # noqa: E402


async def call_tool(tool: str, arguments: dict) -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server"],
        cwd=str(BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
    )
    async with Client(parameters, read_timeout_seconds=60) as client:
        result = await client.call_tool(tool, arguments)
        if result.is_error:
            text = result.content[0].text if result.content else "MCP tool failed"
            print(text, file=sys.stderr)
            return 1
        print(json.dumps(result.structured_content))
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: mcp_call.py <tool> '<json-arguments>'",
            file=sys.stderr,
        )
        return 2
    try:
        arguments = json.loads(sys.argv[2])
    except json.JSONDecodeError as exc:
        print(f"invalid JSON arguments: {exc}", file=sys.stderr)
        return 2
    if not isinstance(arguments, dict):
        print("arguments must be a JSON object", file=sys.stderr)
        return 2
    return asyncio.run(call_tool(sys.argv[1], arguments))


if __name__ == "__main__":
    raise SystemExit(main())
