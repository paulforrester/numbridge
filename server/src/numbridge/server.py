"""NumBridge MCP server — streamable-http daemon on 127.0.0.1:PORT.

Claude Desktop / Claude Code connects via:
  http://127.0.0.1:8765/mcp   (or whatever NUMBRIDGE_PORT is set to)
"""
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from numbridge import numbers_bridge
from numbridge.numbers_bridge import NumbersError

PORT = int(os.environ.get("NUMBRIDGE_PORT", "8765"))

mcp = FastMCP(
    "numbridge",
    host="127.0.0.1",
    port=PORT,
    # Override auto-configured settings to also permit null origins (file:// pages).
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "null"],
    ),
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
def list_tables(document: str, sheet: str) -> list[str]:
    """Return the names of all tables in a sheet.

    Numbers sheets can contain multiple tables. Use the returned names when
    calling get_cell, get_range, set_cell, set_range, or get_sheet_as_table
    to target a specific table.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
    """
    return numbers_bridge.list_tables(document, sheet)


@mcp.tool()
def get_range(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> list[list[str]]:
    """Read a rectangular block of cells in one call.

    Returns a list of rows, each row a list of displayed cell values.
    Empty cells are "". Indices are 1-based (start_row=1, start_col=1 is A1).
    Limited to 1 000 cells per call; use multiple calls for larger ranges.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        start_row: First row to include (1-indexed).
        start_col: First column to include (1-indexed).
        end_row: Last row to include (inclusive).
        end_col: Last column to include (inclusive).
    """
    return numbers_bridge.get_range(
        document, sheet, table, start_row, start_col, end_row, end_col
    )


@mcp.tool()
def get_cell(document: str, sheet: str, table: str, row: int, column: int) -> str:
    """Read the value of a single cell from a Numbers spreadsheet.

    Returns the value exactly as displayed in Numbers (respecting number
    formatting, currency symbols, date formats, etc.).  Empty cells return
    an empty string.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet within that document.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        column: 1-indexed column number (1 = A, 2 = B, …).
    """
    return numbers_bridge.get_cell(document, sheet, table, row, column)


@mcp.tool()
def set_cell(
    document: str,
    sheet: str,
    table: str,
    row: int,
    column: int,
    value: str | int | float | None,
) -> None:
    """Write a value to a single cell.

    Pass a number (int or float) to store a numeric cell, a string for text,
    or null / "" to clear the cell.  Indices are 1-based (row=1, column=1 is A1).

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        column: 1-indexed column number (1 = A, 2 = B, …).
        value: Value to write. Pass null or "" to clear the cell.
    """
    numbers_bridge.set_cell(document, sheet, table, row, column, value)


@mcp.tool()
def set_range(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    values: list[list[str | int | float | None]],
) -> None:
    """Write a rectangular block of cells in one call.

    The top-left corner of the written block is (start_row, start_col).
    Each inner list is one row; rows may differ in length (jagged ranges are fine).
    Use null or "" for individual cells to clear them.
    Limited to 1 000 cells total across all rows.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        start_row: 1-indexed row of the top-left corner.
        start_col: 1-indexed column of the top-left corner.
        values: List of rows, each row a list of cell values.
    """
    numbers_bridge.set_range(document, sheet, table, start_row, start_col, values)


@mcp.tool()
def get_sheet_as_table(document: str, sheet: str, table: str) -> list[list[str]]:
    """Read all used cells in a table and return them as a list of rows.

    Automatically detects the used range by backward-scanning the table, then
    reads the entire block in one call.  Returns an empty list if the table is
    empty.  Limited to 2 000 cells; use get_range for targeted reads of large
    tables.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
    """
    return numbers_bridge.get_sheet_as_table(document, sheet, table)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import sys
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
        return

    import uvicorn
    from starlette.middleware.cors import CORSMiddleware

    app = CORSMiddleware(
        app=mcp.streamable_http_app(),
        # "null" covers file:// origins; the regex covers localhost on any port
        allow_origins=["null"],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
        # Expose mcp-session-id so browser JS can read it and echo it back
        expose_headers=["mcp-session-id"],
    )
    uvicorn.run(app, host="127.0.0.1", port=PORT)
