"""AppleScript bridge to Apple Numbers.

All public functions run synchronously via osascript.  They raise NumbersError
on any AppleScript error (Numbers not running, document not found, etc.).
"""
import os
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
# Formatting helpers
# ---------------------------------------------------------------------------

# Maps user-facing format names to AppleScript constants.
# "date" is excluded: the "date and time" enum value collides with AppleScript's
# built-in date type and cannot be set reliably via plain-text osascript.
_NUMBER_FORMAT_MAP: dict[str, str] = {
    "currency":   "currency",
    "number":     "number",
    "percentage": "percent",
    "text":       "text",
}

_ALIGNMENT_MAP: dict[str, str] = {
    "left":   "left",
    "center": "center",
    "right":  "right",
}

# Substrings in PostScript font-name style suffixes that indicate bold/italic.
_BOLD_TOKENS   = ("bold", "heavy", "black", "demibold", "semibold")
_ITALIC_TOKENS = ("italic", "oblique")


def _apply_bold_italic(font_name: str, bold: bool | None, italic: bool | None) -> str:
    """Return a PostScript font name with the requested bold/italic state applied.

    Parses the current style from the hyphen-delimited suffix (e.g.
    "HelveticaNeue-BoldItalic" → family="HelveticaNeue", style="BoldItalic")
    and merges in the requested changes, leaving unspecified axes unchanged.
    Returns the original name unchanged when both bold and italic are None.
    """
    if bold is None and italic is None:
        return font_name

    family, style = (font_name.rsplit("-", 1) if "-" in font_name
                     else (font_name, ""))

    style_lc  = style.lower()
    is_bold   = any(t in style_lc for t in _BOLD_TOKENS)
    is_italic = any(t in style_lc for t in _ITALIC_TOKENS)

    new_bold   = is_bold   if bold   is None else bold
    new_italic = is_italic if italic is None else italic

    if new_bold and new_italic:
        suffix = "BoldItalic"
    elif new_bold:
        suffix = "Bold"
    elif new_italic:
        suffix = "Italic"
    else:
        suffix = ""

    return f"{family}-{suffix}" if suffix else family


def _fmt_stmts(
    addr: str,
    number_format: str | None,
    alignment: str | None,
    new_font: str | None,
    font_size: float | None = None,
) -> list[str]:
    """Return AppleScript statements for the requested format changes on *addr*."""
    stmts: list[str] = []
    if number_format is not None:
        stmts.append(f'set format of cell "{addr}" to {_NUMBER_FORMAT_MAP[number_format]}')
    if alignment is not None:
        stmts.append(f'set alignment of cell "{addr}" to {_ALIGNMENT_MAP[alignment]}')
    if new_font is not None:
        stmts.append(f'set font name of cell "{addr}" to "{_q(new_font)}"')
    if font_size is not None:
        stmts.append(f'set font size of cell "{addr}" to {font_size}')
    return stmts


# ---------------------------------------------------------------------------
# Numbers operations
# ---------------------------------------------------------------------------

def create_document(name: str | None = None) -> str:
    """Create a new blank Numbers document and return its name.

    If *name* is provided the document is created with that title.
    If omitted, Numbers assigns the next available "Untitled N" name.
    The document is unsaved (in-memory only) until the user saves it.
    """
    if name is not None:
        n = _q(name)
        result = _run(
            f'tell application "Numbers"\n'
            f'    set doc to make new document with properties {{name:"{n}"}}\n'
            f'    return name of doc\n'
            f'end tell'
        )
    else:
        result = _run(
            'tell application "Numbers"\n'
            '    set doc to make new document\n'
            '    return name of doc\n'
            'end tell'
        )
    return result


def open_document(path: str) -> str:
    """Open a Numbers document from *path* and return its name.

    *path* must be an absolute POSIX path to a .numbers file.
    Raises ValueError if the file does not exist.
    """
    if not os.path.exists(path):
        raise ValueError(f"File not found: {path!r}")
    p = _q(path)
    return _run(
        f'tell application "Numbers"\n'
        f'    set doc to open POSIX file "{p}"\n'
        f'    return name of doc\n'
        f'end tell'
    )


def close_document(document: str, save: bool = False) -> str:
    """Close an open Numbers document.

    *save=False* (default) discards unsaved changes.
    *save=True* saves to the document's existing file before closing;
    raises NumbersError for unsaved (Untitled) documents with no file path.
    Raises ValueError if *document* is not currently open.
    """
    doc = _q(document)
    saving = "yes" if save else "no"
    # Existence check is a separate loop from the close — same pattern as
    # delete_sheet to avoid mutating the collection mid-iteration.
    result = _run(
        f'tell application "Numbers"\n'
        f'    set found to false\n'
        f'    repeat with d in documents\n'
        f'        if name of d is "{doc}" then\n'
        f'            set found to true\n'
        f'            exit repeat\n'
        f'        end if\n'
        f'    end repeat\n'
        f'    if not found then return "NOT_FOUND"\n'
        f'    close document "{doc}" saving {saving}\n'
        f'    return "OK"\n'
        f'end tell'
    )
    if result == "NOT_FOUND":
        raise ValueError(f"Document {document!r} is not open")
    return f"Document {document!r} closed"


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


def add_sheet(document: str, sheet_name: str) -> str:
    """Add a new blank sheet to *document*.

    Raises ValueError if a sheet with that name already exists.
    Numbers inserts the new sheet after the currently active sheet.
    """
    doc = _q(document)
    name = _q(sheet_name)
    result = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        repeat with s in sheets\n'
        f'            if name of s is "{name}" then return "EXISTS"\n'
        f'        end repeat\n'
        f'        make new sheet with properties {{name:"{name}"}}\n'
        f'        return "OK"\n'
        f'    end tell\n'
        f'end tell'
    )
    if result == "EXISTS":
        raise ValueError(f"Sheet {sheet_name!r} already exists in {document!r}")
    return f"Sheet {sheet_name!r} added to {document!r}"


def delete_sheet(document: str, sheet_name: str) -> str:
    """Delete a sheet from *document*.

    Raises ValueError if the sheet does not exist.
    """
    doc = _q(document)
    name = _q(sheet_name)
    # Existence check is a separate loop from the delete — deleting `s` while
    # iterating `repeat with s in sheets` triggers AppleScript's -1728
    # ("Can't get item N of every sheet") mutation-while-iterating error.
    result = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        set found to false\n'
        f'        repeat with s in sheets\n'
        f'            if name of s is "{name}" then\n'
        f'                set found to true\n'
        f'                exit repeat\n'
        f'            end if\n'
        f'        end repeat\n'
        f'        if not found then return "NOT_FOUND"\n'
        f'        delete sheet "{name}"\n'
        f'        return "OK"\n'
        f'    end tell\n'
        f'end tell'
    )
    if result == "NOT_FOUND":
        raise ValueError(f"Sheet {sheet_name!r} not found in {document!r}")
    return f"Sheet {sheet_name!r} deleted from {document!r}"


def rename_sheet(document: str, old_name: str, new_name: str) -> str:
    """Rename a sheet in *document* from *old_name* to *new_name*.

    Raises ValueError if *old_name* does not exist or *new_name* is already taken.
    """
    if old_name == new_name:
        return f"Sheet {old_name!r} already has that name"
    doc = _q(document)
    old = _q(old_name)
    new = _q(new_name)
    result = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        repeat with s in sheets\n'
        f'            if name of s is "{new}" then return "NEW_EXISTS"\n'
        f'        end repeat\n'
        f'        repeat with s in sheets\n'
        f'            if name of s is "{old}" then\n'
        f'                set name of s to "{new}"\n'
        f'                return "OK"\n'
        f'            end if\n'
        f'        end repeat\n'
        f'        return "NOT_FOUND"\n'
        f'    end tell\n'
        f'end tell'
    )
    if result == "NEW_EXISTS":
        raise ValueError(f"Sheet {new_name!r} already exists in {document!r}")
    if result == "NOT_FOUND":
        raise ValueError(f"Sheet {old_name!r} not found in {document!r}")
    return f"Sheet {old_name!r} renamed to {new_name!r} in {document!r}"


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
    *,
    number_format: str | None = None,
    currency_symbol: str | None = None,  # noqa: ARG001 — not exposed by Numbers scripting API
    decimal_places: int | None = None,   # noqa: ARG001 — not exposed by Numbers scripting API
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    font_size: float | None = None,
) -> None:
    """Write a single cell value with optional formatting.

    Pass a number (int/float) to store a numeric cell, a string for text,
    or None / "" to clear the cell.  Row and column are 1-indexed.

    Formatting parameters (all optional — omit to leave existing format unchanged):
      number_format   "currency" | "number" | "percentage" | "text"
      bold            True / False
      italic          True / False
      alignment       "left" | "center" | "right"
      font_size       point size (e.g. 12.0)

    Note: decimal_places and currency_symbol are accepted for API compatibility
    but have no effect — Numbers' scripting API does not expose these properties.
    """
    if number_format is not None and number_format not in _NUMBER_FORMAT_MAP:
        raise ValueError(
            f"number_format must be one of {list(_NUMBER_FORMAT_MAP)}; got {number_format!r}"
        )
    if alignment is not None and alignment not in _ALIGNMENT_MAP:
        raise ValueError(
            f"alignment must be one of {list(_ALIGNMENT_MAP)}; got {alignment!r}"
        )

    doc  = _q(document)
    sht  = _q(sheet)
    tbl  = _q(table)
    addr = f"{_col_letter(column)}{row}"

    # When bold/italic is requested we need the current font name to preserve
    # the other axis and keep the base font family.
    new_font: str | None = None
    if bold is not None or italic is not None:
        current_font = _run(
            f'tell application "Numbers"\n'
            f'    tell document "{doc}"\n'
            f'        tell sheet "{sht}"\n'
            f'            tell table "{tbl}"\n'
            f'                return font name of cell "{addr}"\n'
            f"            end tell\n"
            f"        end tell\n"
            f"    end tell\n"
            f"end tell"
        )
        new_font = _apply_bold_italic(current_font, bold, italic)

    stmts = (
        [f'set value of cell "{addr}" to {_as_value(value)}']
        + _fmt_stmts(addr, number_format, alignment, new_font, font_size)
    )
    body = "\n                ".join(stmts)
    _run(
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


def set_range(
    document: str,
    sheet: str,
    table: str,
    start_row: int,
    start_col: int,
    values: list[list[str | int | float | None]],
    *,
    number_format: str | None = None,
    currency_symbol: str | None = None,  # noqa: ARG001 — not exposed by Numbers scripting API
    decimal_places: int | None = None,   # noqa: ARG001 — not exposed by Numbers scripting API
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    font_size: float | None = None,
) -> None:
    """Write a rectangular block of cells with optional formatting.

    *values* is a list of rows; each row is a list of cell values.
    The top-left corner of the written block is (start_row, start_col).
    Rows may be jagged — each is written independently.
    Pass None or "" for individual cells to clear them.
    Limited to 1 000 cells total.

    Formatting parameters apply uniformly to every written cell (all optional):
      number_format   "currency" | "number" | "percentage" | "text"
      bold            True / False
      italic          True / False
      alignment       "left" | "center" | "right"
      font_size       point size (e.g. 12.0)

    Note: decimal_places and currency_symbol are accepted for API compatibility
    but have no effect — Numbers' scripting API does not expose these properties.
    """
    if number_format is not None and number_format not in _NUMBER_FORMAT_MAP:
        raise ValueError(
            f"number_format must be one of {list(_NUMBER_FORMAT_MAP)}; got {number_format!r}"
        )
    if alignment is not None and alignment not in _ALIGNMENT_MAP:
        raise ValueError(
            f"alignment must be one of {list(_ALIGNMENT_MAP)}; got {alignment!r}"
        )

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

    # When bold/italic is requested, read current font names for the written
    # cells first so we can preserve the other axis and the base font family.
    font_grid: list[list[str]] | None = None
    if bold is not None or italic is not None:
        max_cols = max(len(row) for row in values)
        end_row  = start_row + len(values) - 1
        end_col  = start_col + max_cols - 1
        font_script = f"""tell application "Numbers"
    tell document "{doc}"
        tell sheet "{sht}"
            tell table "{tbl}"
                set all_rows to {{}}
                repeat with r from {start_row} to {end_row}
                    set row_fonts to {{}}
                    repeat with c from {start_col} to {end_col}
                        set end of row_fonts to font name of cell c of row r
                    end repeat
                    set end of all_rows to row_fonts
                end repeat
                set AppleScript's text item delimiters to tab
                set result to ""
                repeat with row_fonts in all_rows
                    set result to result & (row_fonts as text) & linefeed
                end repeat
                return result
            end tell
        end tell
    end tell
end tell"""
        raw = subprocess.run(
            ["osascript", "-e", font_script],
            capture_output=True, text=True, timeout=_RANGE_TIMEOUT,
        )
        if raw.returncode != 0:
            msg = raw.stderr.strip()
            raise NumbersError(msg or f"osascript exited with code {raw.returncode}")
        font_grid = _parse_grid(raw.stdout.rstrip("\r\n"))

    # Build one set-statement per cell; execute as a single osascript call
    # so the entire write is atomic from Numbers' perspective.
    stmts: list[str] = []
    for r_idx, row in enumerate(values):
        for c_idx, val in enumerate(row):
            addr = f"{_col_letter(start_col + c_idx)}{start_row + r_idx}"
            stmts.append(f'set value of cell "{addr}" to {_as_value(val)}')
            new_font: str | None = None
            if font_grid is not None:
                current_font = font_grid[r_idx][c_idx] if (
                    r_idx < len(font_grid) and c_idx < len(font_grid[r_idx])
                ) else ""
                if current_font:
                    new_font = _apply_bold_italic(current_font, bold, italic)
            stmts.extend(_fmt_stmts(addr, number_format, alignment, new_font, font_size))

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


def resize_table(
    document: str,
    sheet: str,
    table: str,
    num_rows: int,
    num_columns: int,
) -> str:
    """Resize a Numbers table to exactly *num_rows* rows and *num_columns* columns.

    Use this before writing data that exceeds the table's current dimensions —
    Numbers raises -10006 when a set_cell / set_range call targets a cell outside
    the table boundary.  Both row and column counts include any header row/column.

    Raises ValueError if either dimension is less than 1.
    """
    if num_rows < 1:
        raise ValueError(f"num_rows must be >= 1; got {num_rows}")
    if num_columns < 1:
        raise ValueError(f"num_columns must be >= 1; got {num_columns}")
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)
    _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                set row count to {num_rows}\n'
        f'                set column count to {num_columns}\n'
        f'            end tell\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    )
    return f"Table {table!r} resized to {num_rows} rows × {num_columns} columns"


def get_column_width(document: str, sheet: str, table: str, column: int) -> float:
    """Return the width of *column* in points.

    Column is 1-indexed.  Raises ValueError for non-positive column numbers.
    """
    if column < 1:
        raise ValueError(f"column must be >= 1; got {column}")
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)
    return float(_run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                return width of column {column}\n'
        f'            end tell\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    ))


def set_column_width(document: str, sheet: str, table: str, column: int, width: float) -> str:
    """Set the width of *column* to *width* points.

    Column is 1-indexed.  Raises ValueError for non-positive column or width.
    """
    if column < 1:
        raise ValueError(f"column must be >= 1; got {column}")
    if width <= 0:
        raise ValueError(f"width must be > 0; got {width}")
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)
    _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                set width of column {column} to {width}\n'
        f'            end tell\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    )
    return f"Column {column} width set to {width} pt in table {table!r}"


def get_row_height(document: str, sheet: str, table: str, row: int) -> float:
    """Return the height of *row* in points.

    Row is 1-indexed.  Raises ValueError for non-positive row numbers.
    """
    if row < 1:
        raise ValueError(f"row must be >= 1; got {row}")
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)
    return float(_run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                return height of row {row}\n'
        f'            end tell\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    ))


def set_row_height(document: str, sheet: str, table: str, row: int, height: float) -> str:
    """Set the height of *row* to *height* points.

    Row is 1-indexed.  Raises ValueError for non-positive row or height.
    """
    if row < 1:
        raise ValueError(f"row must be >= 1; got {row}")
    if height <= 0:
        raise ValueError(f"height must be > 0; got {height}")
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)
    _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                set height of row {row} to {height}\n'
        f'            end tell\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    )
    return f"Row {row} height set to {height} pt in table {table!r}"


def get_cell_format(
    document: str, sheet: str, table: str, row: int, column: int
) -> dict:
    """Return formatting properties of a single cell.

    Returns a dict with keys:
      font_name     PostScript font name (e.g. "HelveticaNeue-Bold")
      font_size     point size as a float
      bold          True / False (derived from font name)
      italic        True / False (derived from font name)
      alignment     string as reported by Numbers (e.g. "left", "center", "right")
      number_format string as reported by Numbers (e.g. "automatic", "number", "currency")
    """
    doc  = _q(document)
    sht  = _q(sheet)
    tbl  = _q(table)
    addr = f"{_col_letter(column)}{row}"
    raw = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                set fn to font name of cell "{addr}"\n'
        f'                set fs to font size of cell "{addr}"\n'
        f'                set al to alignment of cell "{addr}" as text\n'
        f'                set fmt to format of cell "{addr}" as text\n'
        f'                return fn & "||" & (fs as text) & "||" & al & "||" & fmt\n'
        f'            end tell\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    )
    parts = raw.split("||")
    font_name     = parts[0] if len(parts) > 0 else ""
    font_size     = float(parts[1]) if len(parts) > 1 else 0.0
    alignment     = parts[2] if len(parts) > 2 else ""
    number_format = parts[3] if len(parts) > 3 else ""
    style_lc = (font_name.rsplit("-", 1)[1] if "-" in font_name else "").lower()
    return {
        "font_name":     font_name,
        "font_size":     font_size,
        "bold":          any(t in style_lc for t in _BOLD_TOKENS),
        "italic":        any(t in style_lc for t in _ITALIC_TOKENS),
        "alignment":     alignment,
        "number_format": number_format,
    }


def _get_count_and_fonts(
    doc: str, sht: str, tbl: str, row: int | None, column: int | None
) -> tuple[int, list[str]]:
    """Return (count, font_names) for a whole row or column.

    Pass *row* (row number, 1-based) to iterate over columns in that row.
    Pass *column* (column number, 1-based) to iterate over rows in that column.
    Exactly one of row/column must be non-None.
    """
    if row is not None:
        script = f"""tell application "Numbers"
    tell document "{doc}"
        tell sheet "{sht}"
            tell table "{tbl}"
                set cc to column count
                set fonts to {{}}
                repeat with c from 1 to cc
                    set end of fonts to (font name of cell c of row {row})
                end repeat
                set AppleScript's text item delimiters to tab
                return (cc as text) & linefeed & (fonts as text)
            end tell
        end tell
    end tell
end tell"""
    else:
        script = f"""tell application "Numbers"
    tell document "{doc}"
        tell sheet "{sht}"
            tell table "{tbl}"
                set rc to row count
                set fonts to {{}}
                repeat with r from 1 to rc
                    set end of fonts to (font name of cell {column} of row r)
                end repeat
                set AppleScript's text item delimiters to tab
                return (rc as text) & linefeed & (fonts as text)
            end tell
        end tell
    end tell
end tell"""

    raw = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=_RANGE_TIMEOUT,
    )
    if raw.returncode != 0:
        raise NumbersError(raw.stderr.strip() or f"osascript exited with code {raw.returncode}")
    lines = raw.stdout.strip().split("\n")
    count      = int(lines[0])
    font_names = lines[1].split("\t") if len(lines) > 1 and lines[1] else []
    return count, font_names


def _get_count(doc: str, sht: str, tbl: str, dimension: str) -> int:
    """Return row count or column count for the table."""
    return int(_run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            tell table "{tbl}"\n'
        f'                return {dimension} count\n'
        f'            end tell\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    ))


def set_row_format(
    document: str,
    sheet: str,
    table: str,
    row: int,
    *,
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    number_format: str | None = None,
    font_size: float | None = None,
) -> str:
    """Apply formatting to every cell in *row*.

    All formatting parameters are optional — omit to leave that property unchanged.
    Applies to the full width of the table (all columns).

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        row: 1-indexed row number.
        bold: True / False.
        italic: True / False.
        alignment: "left" | "center" | "right".
        number_format: "currency" | "number" | "percentage" | "text".
        font_size: Point size (e.g. 14.0).
    """
    if row < 1:
        raise ValueError(f"row must be >= 1; got {row}")
    if bold is None and italic is None and alignment is None and number_format is None and font_size is None:
        return f"Row {row} — nothing to format"
    if number_format is not None and number_format not in _NUMBER_FORMAT_MAP:
        raise ValueError(
            f"number_format must be one of {list(_NUMBER_FORMAT_MAP)}; got {number_format!r}"
        )
    if alignment is not None and alignment not in _ALIGNMENT_MAP:
        raise ValueError(
            f"alignment must be one of {list(_ALIGNMENT_MAP)}; got {alignment!r}"
        )

    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)

    if bold is not None or italic is not None:
        col_count, font_names = _get_count_and_fonts(doc, sht, tbl, row=row, column=None)
    else:
        col_count  = _get_count(doc, sht, tbl, "column")
        font_names = []

    stmts: list[str] = []
    for c in range(1, col_count + 1):
        ref = f"cell {c} of row {row}"
        new_font: str | None = None
        if bold is not None or italic is not None:
            current = font_names[c - 1] if c - 1 < len(font_names) else ""
            if current:
                new_font = _apply_bold_italic(current, bold, italic)
        if new_font is not None:
            stmts.append(f'set font name of {ref} to "{_q(new_font)}"')
        if number_format is not None:
            stmts.append(f'set format of {ref} to {_NUMBER_FORMAT_MAP[number_format]}')
        if alignment is not None:
            stmts.append(f'set alignment of {ref} to {_ALIGNMENT_MAP[alignment]}')
        if font_size is not None:
            stmts.append(f'set font size of {ref} to {font_size}')

    body = "\n                ".join(stmts)
    result = subprocess.run(
        ["osascript", "-e",
         f'tell application "Numbers"\n'
         f'    tell document "{doc}"\n'
         f'        tell sheet "{sht}"\n'
         f'            tell table "{tbl}"\n'
         f'                {body}\n'
         f'            end tell\n'
         f'        end tell\n'
         f'    end tell\n'
         f'end tell'],
        capture_output=True, text=True, timeout=_RANGE_TIMEOUT,
    )
    if result.returncode != 0:
        raise NumbersError(result.stderr.strip() or f"osascript exited with code {result.returncode}")
    return f"Row {row} formatted in table {table!r}"


def set_column_format(
    document: str,
    sheet: str,
    table: str,
    column: int,
    *,
    bold: bool | None = None,
    italic: bool | None = None,
    alignment: str | None = None,
    number_format: str | None = None,
    font_size: float | None = None,
) -> str:
    """Apply formatting to every cell in *column*.

    All formatting parameters are optional — omit to leave that property unchanged.
    Applies to the full height of the table (all rows).

    Args:
        document: Exact name of the open Numbers document.
        sheet: Exact name of the sheet.
        table: Exact name of the table within the sheet.
        column: 1-indexed column number.
        bold: True / False.
        italic: True / False.
        alignment: "left" | "center" | "right".
        number_format: "currency" | "number" | "percentage" | "text".
        font_size: Point size (e.g. 14.0).
    """
    if column < 1:
        raise ValueError(f"column must be >= 1; got {column}")
    if bold is None and italic is None and alignment is None and number_format is None and font_size is None:
        return f"Column {column} — nothing to format"
    if number_format is not None and number_format not in _NUMBER_FORMAT_MAP:
        raise ValueError(
            f"number_format must be one of {list(_NUMBER_FORMAT_MAP)}; got {number_format!r}"
        )
    if alignment is not None and alignment not in _ALIGNMENT_MAP:
        raise ValueError(
            f"alignment must be one of {list(_ALIGNMENT_MAP)}; got {alignment!r}"
        )

    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)

    if bold is not None or italic is not None:
        row_count, font_names = _get_count_and_fonts(doc, sht, tbl, row=None, column=column)
    else:
        row_count  = _get_count(doc, sht, tbl, "row")
        font_names = []

    stmts: list[str] = []
    for r in range(1, row_count + 1):
        ref = f"cell {column} of row {r}"
        new_font: str | None = None
        if bold is not None or italic is not None:
            current = font_names[r - 1] if r - 1 < len(font_names) else ""
            if current:
                new_font = _apply_bold_italic(current, bold, italic)
        if new_font is not None:
            stmts.append(f'set font name of {ref} to "{_q(new_font)}"')
        if number_format is not None:
            stmts.append(f'set format of {ref} to {_NUMBER_FORMAT_MAP[number_format]}')
        if alignment is not None:
            stmts.append(f'set alignment of {ref} to {_ALIGNMENT_MAP[alignment]}')
        if font_size is not None:
            stmts.append(f'set font size of {ref} to {font_size}')

    body = "\n                ".join(stmts)
    result = subprocess.run(
        ["osascript", "-e",
         f'tell application "Numbers"\n'
         f'    tell document "{doc}"\n'
         f'        tell sheet "{sht}"\n'
         f'            tell table "{tbl}"\n'
         f'                {body}\n'
         f'            end tell\n'
         f'        end tell\n'
         f'    end tell\n'
         f'end tell'],
        capture_output=True, text=True, timeout=_RANGE_TIMEOUT,
    )
    if result.returncode != 0:
        raise NumbersError(result.stderr.strip() or f"osascript exited with code {result.returncode}")
    return f"Column {column} formatted in table {table!r}"


def sort_table(
    document: str,
    sheet: str,
    table: str,
    sort_column: int,
    ascending: bool = True,
) -> None:
    """Sort *table* rows by *sort_column* using Numbers' native sort.

    Numbers' built-in sort preserves formulas, formatting, and header rows.
    sort_column is 1-indexed. Raises ValueError for non-positive column numbers.
    """
    if sort_column < 1:
        raise ValueError(f"sort_column must be >= 1; got {sort_column}")
    direction = "ascending" if ascending else "descending"
    doc = _q(document)
    sht = _q(sheet)
    tbl = _q(table)
    # sort takes the table as its direct parameter, so it is called from
    # within tell sheet — not inside tell table.
    # "column N" must be scoped to the table explicitly; bare "column N" in a
    # tell-sheet context is ambiguous.  The direction keyword is plain
    # "direction", NOT "in direction" — "in" would be parsed as the "in rows"
    # parameter name and cause a syntax error.
    _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f'            sort table "{tbl}" by column {sort_column} of table "{tbl}" direction {direction}\n'
        f'        end tell\n'
        f'    end tell\n'
        f'end tell'
    )


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
