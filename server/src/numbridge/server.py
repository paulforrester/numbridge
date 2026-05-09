"""NumBridge MCP server — HTTP daemon (streamable-http transport).

Runs on 127.0.0.1:PORT (default 8765, override with NUMBRIDGE_PORT).
Claude Desktop / Claude Code connects via http://127.0.0.1:PORT/mcp
"""
import os

from mcp.server.fastmcp import FastMCP

PORT = int(os.environ.get("NUMBRIDGE_PORT", "8765"))

mcp = FastMCP(
    "numbridge",
    host="127.0.0.1",
    port=PORT,
)


# ---------------------------------------------------------------------------
# Numbers tools — to be implemented in numbers_bridge.py
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run(transport="streamable-http")
