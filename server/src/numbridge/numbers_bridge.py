"""AppleScript bridge to Apple Numbers.

All public functions run synchronously via osascript.  They raise NumbersError
on any AppleScript error (Numbers not running, document not found, etc.).
"""
import subprocess

_TIMEOUT = 10        # seconds — single-cell / list calls
_RANGE_TIMEOUT = 30  # seconds — grid reads (budget ~10 ms/cell)
_RANGE_CELL_LIMIT = 1000
_SHEET_TIMEOUT = 60  # seconds — whole-sheet read (scan + grid)
_SHEET_CELL_LIMIT = 2000


class NumbersError(RuntimeError):
    """Raised when osascript exits with a non-zero code."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(script: str) -> str:
    """Execute *script* via ``osascript -e`` and return stripped stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
    )
    if result.returncode != 0:
        msg = result.stderr.strip()
        raise NumbersError(msg or f"osascript exited with code {result.returncode}")
    return result.stdout.strip()


def _as_list(raw: str) -> list[str]:
    """Split linefeed-delimited AppleScript list output into a Python list."""
    return [item for item in raw.split("\n") if item]


def _parse_grid(raw: str) -> list[list[str]]:
    """Parse tab+newline-delimited grid output into a list-of-rows."""
    return [line.split("\t") for line in raw.split("\n") if line]


def _q(s: str) -> str:
    """Escape a Python string for safe embedding inside an AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _as_value(v: str | int | float | None) -> str:
    """Return an AppleScript literal for *v*.

    - int/float  → bare number  (stored as a Number cell)
    - str        → quoted string (stored as text; empty string clears the cell)
    - None       → empty string  (clears the cell)
    Note: bool is a subclass of int in Python, so True/False become 1/0.
    """
    if v is None:
        return '""'
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return f'"{_q(str(v))}"'


def _col_letter(n: int) -> str:
    """Convert a 1-based column index to a spreadsheet column letter (1→A, 27→AA)."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


# ---------------------------------------------------------------------------
# Numbers operations
# ---------------------------------------------------------------------------

def list_documents() -> list[str]:
    """Return the names of all currently open Numbers documents."""
    raw = _run(
        'tell application "Numbers"\n'
        "    set out to {}\n"
        "    repeat with d in documents\n"
        "        set end of out to (name of d)\n"
        "    end repeat\n"
        "    set AppleScript's text item delimiters to linefeed\n"
        "    return out as text\n"
        "end tell"
    )
    return _as_list(raw)


def list_sheets(document: str) -> list[str]:
    """Return the names of all sheets in *document*."""
    doc = _q(document)
    raw = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f"        set out to {{}}\n"
        f"        repeat with s in sheets\n"
        f"            set end of out to (name of s)\n"
        f"        end repeat\n"
        f"        set AppleScript's text item delimiters to linefeed\n"
        f"        return out as text\n"
        f"    end tell\n"
        f"end tell"
    )
    return _as_list(raw)


def list_tables(document: str, sheet: str) -> list[str]:
    """Return the names of all tables in *sheet*."""
    doc = _q(document)
    sht = _q(sheet)
    raw = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f"            set out to {{}}\n"
        f"            repeat with t in tables\n"
        f"                set end of out to (name of t)\n"
        f"            end repeat\n"
        f"            set AppleScript's text item delimiters to linefeed\n"
        f"            return out as text\n"
        f"        end tell\n"
        f"    end tell\n"
        f"end tell"
    )
    return _as_list(raw)


def get_cell(document: str, sheet: str, table: str, row: int, column: int) -> str:
    """Return the displayed value of a cell as a string.

    Uses ``formatted value`` so numbers, dates, and currency appear exactly
    as they do in the Numbers UI.  Empty cells return an empty string.
    Row and column are 1-indexed.
    """
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)
    addr = f"{_col_letter(column)}{row}"
    raw = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                set fv to formatted value of cell "{addr}"\n'
        f"                if fv is missing value then\n"
        f'                    return ""\n'
        f"                end if\n"
        f"                return fv\n"
        f"            end tell\n"
        f"        end tell\n"
        f"    end tell\n"
        f"end tell"
    )
    return raw


def get_range(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> list[list[str]]:
    """Return a rectangular block of cells as a list-of-rows.

    Each row is a list of displayed cell values (same format as get_cell).
    Empty cells are represented as empty strings.  Row and column indices
    are 1-indexed.

    Raises ValueError if the range is inverted or exceeds 1 000 cells.
    """
    if start_row > end_row or start_col > end_col:
        raise ValueError(
            f"Range bounds inverted: rows {start_row}–{end_row}, cols {start_col}–{end_col}"
        )
    n_cells = (end_row - start_row + 1) * (end_col - start_col + 1)
    if n_cells > _RANGE_CELL_LIMIT:
        raise ValueError(
            f"Range covers {n_cells} cells; limit is {_RANGE_CELL_LIMIT}. "
            "Use multiple smaller calls."
        )

    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)

    # Critical: collect all rows into a list-of-lists first, THEN join with
    # text item delimiters.  Setting the delimiter inside the row loop corrupts
    # string accumulation in the outer loop (AppleScript scoping quirk).
    script = f"""tell application "Numbers"
    tell document "{doc}"
        tell sheet "{sht}"
            tell table "{tbl}"
                set all_rows to {{}}
                repeat with r from {start_row} to {end_row}
                    set row_vals to {{}}
                    repeat with c from {start_col} to {end_col}
                        set fv to formatted value of cell c of row r
                        if fv is missing value then
                            set end of row_vals to ""
                        else
                            set end of row_vals to fv
                        end if
                    end repeat
                    set end of all_rows to row_vals
                end repeat
                set AppleScript's text item delimiters to tab
                set result to ""
                repeat with row_vals in all_rows
                    set result to result & (row_vals as text) & linefeed
                end repeat
                return result
            end tell
        end tell
    end tell
end tell"""

    raw = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=_RANGE_TIMEOUT,
    )
    if raw.returncode != 0:
        msg = raw.stderr.strip()
        raise NumbersError(msg or f"osascript exited with code {raw.returncode}")
    # rstrip only newlines — not tabs.  .strip() would eat the trailing tab
    # on the last row, silently dropping any trailing empty cell in that row.
    return _parse_grid(raw.stdout.rstrip("\r\n"))


def set_cell(
    document: str,
    sheet: str,
    table: str,
    row: int,
    column: int,
    value: str | int | float | None,
) -> None:
    """Write a single cell value.

    Pass a number (int/float) to store a numeric cell, a string for text,
    or None / "" to clear the cell.  Row and column are 1-indexed.
    """
    doc  = _q(document)
    sht  = _q(sheet)
    tbl  = _q(table)
    addr = f"{_col_letter(column)}{row}"
    _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                set value of cell "{addr}" to {_as_value(value)}\n'
        f"            end tell\n"
        f"        end tell\n"
        f"    end tell\n"
        f"end tell"
    )


def set_range(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    values: list[list[str | int | float | None]],
) -> None:
    """Write a rectangular block of cells in one AppleScript call.

    *values* is a list of rows; each row is a list of cell values.
    The top-left corner of the written block is (start_row, start_col).
    Rows may be jagged — each is written independently.
    Pass None or "" for individual cells to clear them.
    Limited to 1 000 cells total.
    """
    n_cells = sum(len(row) for row in values)
    if n_cells == 0:
        return
    if n_cells > _RANGE_CELL_LIMIT:
        raise ValueError(
            f"Range covers {n_cells} cells; limit is {_RANGE_CELL_LIMIT}. "
            "Use multiple smaller calls."
        )

    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)

    # Build one set-statement per cell; execute as a single osascript call
    # so the entire write is atomic from Numbers' perspective.
    stmts: list[str] = []
    for r_idx, row in enumerate(values):
        for c_idx, val in enumerate(row):
            addr = f"{_col_letter(start_col + c_idx)}{start_row + r_idx}"
            stmts.append(f'set value of cell "{addr}" to {_as_value(val)}')

    body = "\n                ".join(stmts)
    script = (
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f"                {body}\n"
        f"            end tell\n"
        f"        end tell\n"
        f"    end tell\n"
        f"end tell"
    )

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=_RANGE_TIMEOUT,
    )
    if result.returncode != 0:
        msg = result.stderr.strip()
        raise NumbersError(msg or f"osascript exited with code {result.returncode}")


def get_sheet_as_table(document: str, sheet: str, table: str) -> list[list[str]]:
    """Return all used cells in *table* as a list-of-rows.

    Backward-scans the table dimensions to find the used range, then reads
    the entire block in one AppleScript call.  Returns an empty list for an
    empty table.

    Raises ValueError if the used range exceeds 2 000 cells (use get_range
    for targeted reads of large tables).
    """
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)

    script = f"""tell application "Numbers"
    tell document "{doc}"
        tell sheet "{sht}"
            tell table "{tbl}"
                set rc to row count
                set cc to column count
                set last_row to 0
                repeat with r from rc to 1 by -1
                    repeat with c from 1 to cc
                        if value of cell c of row r is not missing value then
                            set last_row to r
                            exit repeat
                        end if
                    end repeat
                    if last_row > 0 then exit repeat
                end repeat
                if last_row = 0 then return ""
                set last_col to 0
                repeat with c from cc to 1 by -1
                    repeat with r from 1 to last_row
                        if value of cell c of row r is not missing value then
                            set last_col to c
                            exit repeat
                        end if
                    end repeat
                    if last_col > 0 then exit repeat
                end repeat
                if last_col = 0 then return ""
                if (last_row * last_col) > {_SHEET_CELL_LIMIT} then
                    return "OVERLIMIT:" & last_row & ":" & last_col
                end if
                set all_rows to {{}}
                repeat with r from 1 to last_row
                    set row_vals to {{}}
                    repeat with c from 1 to last_col
                        set fv to formatted value of cell c of row r
                        if fv is missing value then
                            set end of row_vals to ""
                        else
                            set end of row_vals to fv
                        end if
                    end repeat
                    set end of all_rows to row_vals
                end repeat
                set AppleScript's text item delimiters to tab
                set result to ""
                repeat with row_vals in all_rows
                    set result to result & (row_vals as text) & linefeed
                end repeat
                return result
            end tell
        end tell
    end tell
end tell"""

    raw = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=_SHEET_TIMEOUT,
    )
    if raw.returncode != 0:
        msg = raw.stderr.strip()
        raise NumbersError(msg or f"osascript exited with code {raw.returncode}")

    out = raw.stdout.strip()
    if not out:
        return []
    if out.startswith("OVERLIMIT:"):
        _, nrows, ncols = out.split(":")
        n_cells = int(nrows) * int(ncols)
        raise ValueError(
            f"Sheet used range is {nrows}×{ncols} = {n_cells} cells; "
            f"limit is {_SHEET_CELL_LIMIT}. Use get_range for targeted reads."
        )
    return _parse_grid(out.rstrip("\r\n"))
