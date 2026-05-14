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
def open_document(path: str) -> str:
    """Open a Numbers document from a file path and return its name.

    Args:
        path: Absolute POSIX path to a .numbers file (e.g. "/Users/you/Documents/Budget.numbers").
    """
    return numbers_bridge.open_document(path)


@mcp.tool()
def close_document(document: str, save: bool = False) -> str:
    """Close an open Numbers document.

    Args:
        document: Exact name of the open Numbers document.
        save: If True, save to the document's existing file before closing.
              Defaults to False (discard unsaved changes). Raises an error
              for Untitled documents that have never been saved to a file.
    """
    return numbers_bridge.close_document(document, save)


@mcp.tool()
def create_document(name: str | None = None) -> str:
    """Create a new blank Numbers document and return its name.

    The document is created in-memory and unsaved — Numbers will prompt
    the user to save when they close it or you can save it via the UI.

    Args:
        name: Optional title for the new document. If omitted, Numbers
              assigns the next available "Untitled N" name.
    """
    return numbers_bridge.create_document(name)


@mcp.tool()
def list_documents() -> str:
    """Return the names of all currently open Numbers documents, one per line.

    Numbers must be running; returns an empty string if no documents are open.
    """
    return "\n".join(numbers_bridge.list_documents())


@mcp.tool()
def list_sheets(document: str) -> str:
    """Return the names of all sheets in a Numbers document, one per line.

    Args:
        document: Exact name of the open Numbers document (e.g. "Budget 2025").
    """
    return "\n".join(numbers_bridge.list_sheets(document))


@mcp.tool()
def add_sheet(document: str, sheet_name: str) -> str:
    """Add a new blank sheet to a Numbers document.

    Numbers inserts the new sheet after the currently active sheet.

    Args:
        document: Exact name of the open Numbers document.
        sheet_name: Name for the new sheet. Must not already exist in the document.
    """
    return numbers_bridge.add_sheet(document, sheet_name)


@mcp.tool()
def delete_sheet(document: str, sheet_name: str) -> str:
    """Delete a sheet from a Numbers document.

    Args:
        document: Exact name of the open Numbers document.
        sheet_name: Exact name of the sheet to delete. Must exist in the document.
    """
    return numbers_bridge.delete_sheet(document, sheet_name)


@mcp.tool()
def rename_sheet(document: str, old_name: str, new_name: str) -> str:
    """Rename a sheet in a Numbers document.

    Args:
        document: Exact name of the open Numbers document.
        old_name: Current name of the sheet to rename. Must exist.
        new_name: New name for the sheet. Must not already be used by another sheet.
    """
    return numbers_bridge.rename_sheet(document, old_name, new_name)


@mcp.tool()
def list_tables(document: str, sheet: str) -> str:
    """Return the names of all tables in a sheet, one per line.

    Numbers sheets can contain multiple tables. Use the returned names when
    calling get_cell, get_range, set_cell, set_range, or get_sheet_as_table
    to target a specific table.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
    """
    return "\n".join(numbers_bridge.list_tables(document, sheet))


@mcp.tool()
def add_table(
    document: str,
    sheet: str,
    name: str,
    num_rows: int = 4,
    num_columns: int = 4,
) -> str:
    """Add a new blank table to a sheet in a Numbers document.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet to add the table to.
        name: Name for the new table. Must not already exist in the sheet.
        num_rows: Initial row count (default 4, minimum 1).
        num_columns: Initial column count (default 4, minimum 1).
    """
    return numbers_bridge.add_table(document, sheet, name, num_rows, num_columns)


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
    number_format: str | None = None,
    currency_symbol: str | None = None,
    decimal_places: int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    font_size: float | None = None,
    text_color: list[int] | None = None,
    background_color: list[int] | None = None,
    text_wrap: bool | None = None,
    vertical_alignment: str | None = None,
) -> None:
    """Write a value to a single cell with optional formatting.

    Pass a number (int or float) to store a numeric cell, a string for text,
    or null / "" to clear the cell.  Indices are 1-based (row=1, column=1 is A1).
    All formatting parameters are optional — omit to leave existing format unchanged.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        column: 1-indexed column number (1 = A, 2 = B, …).
        value: Value to write. Pass null or "" to clear the cell.
        number_format: "currency", "number", "percentage", or "text".
        currency_symbol: Accepted but has no effect (not exposed by Numbers scripting API).
        decimal_places: Accepted but has no effect (not exposed by Numbers scripting API).
        bold: True to make the cell bold, False to remove bold.
        italic: True to make the cell italic, False to remove italic.
        alignment: "left", "center", or "right".
        font_size: Point size (e.g. 14.0).
        text_color: [r, g, b] foreground colour with each component 0–255.
        background_color: [r, g, b] fill colour with each component 0–255.
        text_wrap: True to wrap text within the cell, False to clip.
        vertical_alignment: "top", "center", or "bottom".
    """
    numbers_bridge.set_cell(
        document, sheet, table, row, column, value,
        number_format=number_format,
        currency_symbol=currency_symbol,
        decimal_places=decimal_places,
        bold=bold,
        italic=italic,
        alignment=alignment,
        font_size=font_size,
        text_color=text_color,
        background_color=background_color,
        text_wrap=text_wrap,
        vertical_alignment=vertical_alignment,
    )


@mcp.tool()
def set_range(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    values: list[list[str | int | float | None]],
    number_format: str | None = None,
    currency_symbol: str | None = None,
    decimal_places: int | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    font_size: float | None = None,
    text_color: list[int] | None = None,
    background_color: list[int] | None = None,
    text_wrap: bool | None = None,
    vertical_alignment: str | None = None,
) -> None:
    """Write a rectangular block of cells with optional formatting.

    The top-left corner of the written block is (start_row, start_col).
    Each inner list is one row; rows may differ in length (jagged ranges are fine).
    Use null or "" for individual cells to clear them.
    Limited to 1 000 cells total across all rows.
    Formatting parameters apply uniformly to every written cell.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        start_row: 1-indexed row of the top-left corner.
        start_col: 1-indexed column of the top-left corner.
        values: List of rows, each row a list of cell values.
        number_format: "currency", "number", "percentage", or "text".
        currency_symbol: Accepted but has no effect (not exposed by Numbers scripting API).
        decimal_places: Accepted but has no effect (not exposed by Numbers scripting API).
        bold: True to make cells bold, False to remove bold.
        italic: True to make cells italic, False to remove italic.
        alignment: "left", "center", or "right".
        font_size: Point size (e.g. 14.0).
        text_color: [r, g, b] foreground colour with each component 0–255.
        background_color: [r, g, b] fill colour with each component 0–255.
        text_wrap: True to wrap text within cells, False to clip.
        vertical_alignment: "top", "center", or "bottom".
    """
    numbers_bridge.set_range(
        document, sheet, table, start_row, start_col, values,
        number_format=number_format,
        currency_symbol=currency_symbol,
        decimal_places=decimal_places,
        bold=bold,
        italic=italic,
        alignment=alignment,
        font_size=font_size,
        text_color=text_color,
        background_color=background_color,
        text_wrap=text_wrap,
        vertical_alignment=vertical_alignment,
    )


@mcp.tool()
def resize_table(
    document: str,
    sheet: str,
    table: str,
    num_rows: int,
    num_columns: int,
) -> str:
    """Resize a Numbers table to the given number of rows and columns.

    Call this before writing data that would exceed the current table boundary
    — Numbers raises an error (-10006) when set_cell or set_range targets a
    cell outside the table dimensions.  New documents default to 4 columns and
    a handful of rows, so resize first when building wide or tall tables.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        num_rows: Desired total number of rows (including any header row).
        num_columns: Desired total number of columns (including any header column).
    """
    return numbers_bridge.resize_table(document, sheet, table, num_rows, num_columns)


@mcp.tool()
def get_column_width(document: str, sheet: str, table: str, column: int) -> float:
    """Return the width of a column in points.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        column: 1-indexed column number.
    """
    return numbers_bridge.get_column_width(document, sheet, table, column)


@mcp.tool()
def set_column_width(
    document: str, sheet: str, table: str, column: int, width: float
) -> str:
    """Set the width of a column in points.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        column: 1-indexed column number.
        width: Desired column width in points (must be > 0).
    """
    return numbers_bridge.set_column_width(document, sheet, table, column, width)


@mcp.tool()
def get_row_height(document: str, sheet: str, table: str, row: int) -> float:
    """Return the height of a row in points.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
    """
    return numbers_bridge.get_row_height(document, sheet, table, row)


@mcp.tool()
def set_row_height(
    document: str, sheet: str, table: str, row: int, height: float
) -> str:
    """Set the height of a row in points.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        height: Desired row height in points (must be > 0).
    """
    return numbers_bridge.set_row_height(document, sheet, table, row, height)


@mcp.tool()
def get_cell_format(
    document: str, sheet: str, table: str, row: int, column: int
) -> dict:
    """Return the formatting properties of a single cell.

    Returns a dict with keys: font_name, font_size, bold, italic, alignment,
    number_format, text_color ([r,g,b] or null), background_color ([r,g,b]
    or null), text_wrap (bool), vertical_alignment.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        column: 1-indexed column number.
    """
    return numbers_bridge.get_cell_format(document, sheet, table, row, column)


@mcp.tool()
def set_row_format(
    document: str,
    sheet: str,
    table: str,
    row: int,
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    number_format: str | None = None,
    font_size: float | None = None,
    text_color: list[int] | None = None,
    background_color: list[int] | None = None,
    text_wrap: bool | None = None,
    vertical_alignment: str | None = None,
) -> str:
    """Apply formatting to every cell in a row.

    All formatting parameters are optional. Applies to the full width of the table.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        bold: True to bold, False to remove bold.
        italic: True to italicise, False to remove italic.
        alignment: "left", "center", or "right".
        number_format: "currency", "number", "percentage", or "text".
        font_size: Point size (e.g. 14.0).
        text_color: [r, g, b] foreground colour with each component 0–255.
        background_color: [r, g, b] fill colour with each component 0–255.
        text_wrap: True to wrap text within cells, False to clip.
        vertical_alignment: "top", "center", or "bottom".
    """
    return numbers_bridge.set_row_format(
        document, sheet, table, row,
        bold=bold, italic=italic, alignment=alignment,
        number_format=number_format, font_size=font_size,
        text_color=text_color, background_color=background_color,
        text_wrap=text_wrap, vertical_alignment=vertical_alignment,
    )


@mcp.tool()
def set_column_format(
    document: str,
    sheet: str,
    table: str,
    column: int,
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    number_format: str | None = None,
    font_size: float | None = None,
    text_color: list[int] | None = None,
    background_color: list[int] | None = None,
    text_wrap: bool | None = None,
    vertical_alignment: str | None = None,
) -> str:
    """Apply formatting to every cell in a column.

    All formatting parameters are optional. Applies to the full height of the table.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        column: 1-indexed column number.
        bold: True to bold, False to remove bold.
        italic: True to italicise, False to remove italic.
        alignment: "left", "center", or "right".
        number_format: "currency", "number", "percentage", or "text".
        font_size: Point size (e.g. 14.0).
        text_color: [r, g, b] foreground colour with each component 0–255.
        background_color: [r, g, b] fill colour with each component 0–255.
        text_wrap: True to wrap text within cells, False to clip.
        vertical_alignment: "top", "center", or "bottom".
    """
    return numbers_bridge.set_column_format(
        document, sheet, table, column,
        bold=bold, italic=italic, alignment=alignment,
        number_format=number_format, font_size=font_size,
        text_color=text_color, background_color=background_color,
        text_wrap=text_wrap, vertical_alignment=vertical_alignment,
    )


@mcp.tool()
def sort_table(
    document: str,
    sheet: str,
    table: str,
    sort_column: int,
    ascending: bool = True,
) -> None:
    """Sort the rows of a Numbers table by a single column.

    Uses Numbers' native sort, which correctly handles formulas, cell
    formatting, and header rows (headers are never moved).

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        sort_column: 1-indexed column number to sort by.
        ascending: True (default) for A→Z / smallest-first; False for Z→A / largest-first.
    """
    numbers_bridge.sort_table(document, sheet, table, sort_column, ascending)


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


@mcp.tool()
def get_cell_formula(
    document: str, sheet: str, table: str, row: int, column: int
) -> str | None:
    """Return the formula string for a cell, or null if the cell has no formula.

    Read-only — the Numbers scripting API does not support writing formulas.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        column: 1-indexed column number.
    """
    return numbers_bridge.get_cell_formula(document, sheet, table, row, column)


@mcp.tool()
def remove_table(document: str, sheet: str, table: str) -> str:
    """Delete a table from a sheet in a Numbers document.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet containing the table.
        table: Exact name of the table to delete. Must exist in the sheet.
    """
    return numbers_bridge.remove_table(document, sheet, table)


@mcp.tool()
def rename_table(document: str, sheet: str, old_name: str, new_name: str) -> str:
    """Rename a table within a sheet.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet containing the table.
        old_name: Current name of the table to rename. Must exist.
        new_name: New name for the table. Must not already be in use.
    """
    return numbers_bridge.rename_table(document, sheet, old_name, new_name)


@mcp.tool()
def get_table_info(document: str, sheet: str, table: str) -> dict:
    """Return structural metadata about a table.

    Returns a dict with keys: name, row_count, column_count,
    header_row_count, header_column_count, footer_row_count.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
    """
    return numbers_bridge.get_table_info(document, sheet, table)


@mcp.tool()
def set_table_headers(
    document: str,
    sheet: str,
    table: str,
    header_rows: int | None = None,
    header_columns: int | None = None,
    footer_rows: int | None = None,
) -> str:
    """Set the number of header/footer rows and columns on a table.

    All parameters are optional — omit to leave that count unchanged.
    Numbers allows 0–5 header rows, 0–1 header columns, and 0–5 footer rows.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        header_rows: Number of header rows (0–5).
        header_columns: Number of header columns (0–1).
        footer_rows: Number of footer rows (0–5).
    """
    return numbers_bridge.set_table_headers(
        document, sheet, table,
        header_rows=header_rows,
        header_columns=header_columns,
        footer_rows=footer_rows,
    )


@mcp.tool()
def get_table_layout(document: str, sheet: str, table: str) -> dict:
    """Return the position and size of a table on its canvas.

    Returns a dict with keys: x, y (position in points), width, height (in points).

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
    """
    return numbers_bridge.get_table_layout(document, sheet, table)


@mcp.tool()
def set_table_layout(
    document: str,
    sheet: str,
    table: str,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
) -> str:
    """Set the position and/or size of a table on its canvas.

    All parameters are optional — omit to leave that property unchanged.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        x: Horizontal offset in points from the left edge of the canvas.
        y: Vertical offset in points from the top edge of the canvas.
        width: Table width in points.
        height: Table height in points.
    """
    return numbers_bridge.set_table_layout(
        document, sheet, table, x=x, y=y, width=width, height=height
    )


@mcp.tool()
def set_table_locked(document: str, sheet: str, table: str, locked: bool) -> str:
    """Lock or unlock a table on its canvas.

    Locked tables cannot be moved or resized in the Numbers UI.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        locked: True to lock, False to unlock.
    """
    return numbers_bridge.set_table_locked(document, sheet, table, locked)


@mcp.tool()
def insert_row(document: str, sheet: str, table: str, before_row: int) -> str:
    """Insert a blank row before the specified row.

    All rows at or below before_row shift down by one. Row is 1-indexed.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        before_row: 1-indexed row number. The new row is inserted above this row.
    """
    return numbers_bridge.insert_row(document, sheet, table, before_row)


@mcp.tool()
def insert_column(document: str, sheet: str, table: str, before_column: int) -> str:
    """Insert a blank column before the specified column.

    All columns at or to the right of before_column shift right. Column is 1-indexed.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        before_column: 1-indexed column number. The new column is inserted to the left.
    """
    return numbers_bridge.insert_column(document, sheet, table, before_column)


@mcp.tool()
def remove_row(document: str, sheet: str, table: str, row: int) -> str:
    """Remove a row from a table (1-indexed).

    All rows below the removed row shift up by one.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number to remove.
    """
    return numbers_bridge.remove_row(document, sheet, table, row)


@mcp.tool()
def remove_column(document: str, sheet: str, table: str, column: int) -> str:
    """Remove a column from a table (1-indexed).

    All columns to the right of the removed column shift left by one.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        column: 1-indexed column number to remove.
    """
    return numbers_bridge.remove_column(document, sheet, table, column)


@mcp.tool()
def merge_cells(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> str:
    """Merge a rectangular block of cells into a single merged cell.

    Content in all cells except the top-left is discarded. Indices are 1-based.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        start_row: Top row of the merge region (1-indexed).
        start_col: Left column of the merge region (1-indexed).
        end_row: Bottom row of the merge region (inclusive).
        end_col: Right column of the merge region (inclusive).
    """
    return numbers_bridge.merge_cells(
        document, sheet, table, start_row, start_col, end_row, end_col
    )


@mcp.tool()
def unmerge_cells(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> str:
    """Unmerge a previously-merged cell, restoring individual cells in the region.

    Indices are 1-based.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        start_row: Top row of the region (1-indexed).
        start_col: Left column of the region (1-indexed).
        end_row: Bottom row of the region (inclusive).
        end_col: Right column of the region (inclusive).
    """
    return numbers_bridge.unmerge_cells(
        document, sheet, table, start_row, start_col, end_row, end_col
    )


@mcp.tool()
def clear_range(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> str:
    """Clear the content and formatting of cells in a range.

    Equivalent to selecting the cells and pressing Delete in the Numbers UI.
    Both cell values and formatting (colours, number format, etc.) are removed.
    Indices are 1-based.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        start_row: Top row of the range (1-indexed).
        start_col: Left column of the range (1-indexed).
        end_row: Bottom row of the range (inclusive).
        end_col: Right column of the range (inclusive).
    """
    return numbers_bridge.clear_range(
        document, sheet, table, start_row, start_col, end_row, end_col
    )


@mcp.tool()
def transpose_table(document: str, sheet: str, table: str) -> str:
    """Transpose the entire table — swap all rows and columns in place.

    The Numbers scripting API's transpose command operates on a whole table,
    not a sub-range. Use get_range / set_range to transpose a partial selection
    manually.

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
    """
    return numbers_bridge.transpose_table(document, sheet, table)


@mcp.tool()
def export_document(
    document: str,
    path: str,
    format: str = "numbers",
) -> str:
    """Export a Numbers document to a file in the specified format.

    Args:
        document: Exact name of the open Numbers document.
        path: Absolute POSIX path for the output file. The parent directory
              must exist. Any existing file at this path will be overwritten.
        format: One of "numbers" (.numbers), "pdf", "xlsx" (Excel), or "csv".
    """
    return numbers_bridge.export_document(document, path, format)


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
