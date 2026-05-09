"""NumBridge MCP server — stub.  AppleScript tools added in the next layer."""
import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server

app = Server("numbridge")


@app.list_tools()
async def list_tools():
    return []


def main() -> None:
    asyncio.run(_run())


async def _run() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())
