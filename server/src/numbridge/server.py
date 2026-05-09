"""NumBridge MCP server — streamable-http daemon on 127.0.0.1:PORT.

Claude Desktop / Claude Code connects via:
  http://127.0.0.1:8765/mcp   (or whatever NUMBRIDGE_PORT is set to)
"""
import os

from mcp.server.fastmcp import FastMCP

from numbridge import numbers_bridge
from numbridge.numbers_bridge import NumbersError

PORT = int(os.environ.get("NUMBRIDGE_PORT", "8765"))

mcp = FastMCP(
    "numbridge",
    host="127.0.0.1",
    port=PORT,
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_documents() -> list[str]:
    """Return the names of all currently open Numbers documents.

    Numbers must be running; returns an empty list if no documents are open.
    """
    return numbers_bridge.list_documents()


@mcp.tool()
def list_sheets(document: str) -> list[str]:
    """Return the names of all sheets in a Numbers document.

    Args:
        document: Exact name of the open Numbers document (e.g. "Budget 2025").
    """
    return numbers_bridge.list_sheets(document)


@mcp.tool()
def get_cell(document: str, sheet: str, row: int, column: int) -> str:
    """Read the value of a single cell from a Numbers spreadsheet.

    Returns the value exactly as displayed in Numbers (respecting number
    formatting, currency symbols, date formats, etc.).  Empty cells return
    an empty string.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet within that document.
        row: 1-indexed row number.
        column: 1-indexed column number (1 = A, 2 = B, …).
    """
    return numbers_bridge.get_cell(document, sheet, row, column)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    mcp.run(transport="streamable-http")
