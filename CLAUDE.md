# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

NumBridge is a macOS MCP server that lets Claude interact with Apple Numbers via AppleScript. Three layers:

1. **`Launcher/`** — SwiftUI/AppKit menu-bar app (macOS 13+). Registers as a login item, spawns the Python server, monitors/restarts it, and shows status in the menu bar.
2. **`server/`** — Python MCP server (`uv`-managed). Exposes Numbers operations as MCP tools. Entry point: `python -m numbridge`.
3. **AppleScript bridge** (`server/src/numbridge/numbers_bridge.py`) — runs `osascript` subprocesses to read and write Numbers documents.

## Building and running

### Launcher (Swift)

```bash
cd Launcher

# Build .app bundle into dist/ and run it
make run

# Install to /Applications and launch
make install

# Compile only (no bundle)
swift build -c release
```

The Makefile assembles a proper `.app` bundle, applies an ad-hoc codesign, and symlinks `../server` into `dist/server` so `ServerManager` can find the Python code at runtime. Replace `codesign --sign -` with a Developer ID cert for notarisation/distribution.

`SMAppService` (login-item registration) requires a signed app bundle — it silently no-ops during `swift run` / raw binary invocations.

### Python server

```bash
cd server

# Install deps and run directly (no launcher)
uv run python -m numbridge

# Run tests
uv run pytest
```

`uv` resolves dependencies from `pyproject.toml` automatically. No virtualenv activation needed.

## Architecture details

### ServerManager (Swift)

`Launcher/Sources/NumBridgeLauncher/ServerManager.swift`

- `@MainActor` `ObservableObject`; all state mutations happen on the main actor.
- Calls `uv run python -m numbridge` with `currentDirectoryURL` set to the server dir.
- Server directory lookup order: `NUMBRIDGE_SERVER_DIR` env var → `<Bundle>/Resources/server/` → sibling `dist/server/` symlink.
- `uv` search order: `~/.local/bin` → `~/.cargo/bin` → `/opt/homebrew/bin` → `/usr/local/bin` → `which uv` fallback. GUI apps don't inherit shell PATH, so explicit paths are required.
- After process launch, polls `GET http://127.0.0.1:PORT/mcp` every 400 ms (15 s timeout). Status stays `.starting` until any HTTP response arrives, then transitions to `.running(pid:port:)`.
- On unexpected exit, restarts after 3 s. `stop()` sends SIGTERM, then SIGKILL after 2 s grace. `shouldAutoRestart` flag prevents restarts during intentional shutdown.
- Server stdout/stderr → `~/Library/Logs/NumBridge/server.log`.

### StatusBarController (Swift)

`Launcher/Sources/NumBridgeLauncher/StatusBarController.swift`

- Subscribes to `ServerManager.$status` via Combine, rebuilds `NSMenu` on every change.
- SF Symbols used: `tablecells` (stopped/starting), `tablecells.fill` (running), `exclamationmark.triangle.fill` (error). All marked `.isTemplate = true` for light/dark menu bar compatibility.

### Python MCP server

`server/src/numbridge/server.py`

- Uses `FastMCP` (high-level API from the `mcp` SDK).
- Transport: **streamable-http** — listens on `127.0.0.1:8765` (override with `NUMBRIDGE_PORT`). Pass `--stdio` to run in stdio mode for Claude Desktop.
- MCP endpoint: `http://127.0.0.1:8765/mcp` — configure this URL in Claude Code. Claude Desktop uses stdio transport (`uv run … python -m numbridge --stdio`).
- `mcp.streamable_http_app()` is wrapped in Starlette `CORSMiddleware` to allow `null` origins (file:// pages) and localhost. `TransportSecuritySettings` is also overridden to permit `null` origins — FastMCP's default denies them.
- Tools are registered with `@mcp.tool()` decorators; all Numbers I/O goes through `numbers_bridge.py` via `subprocess` + `osascript`.
- 406 on a plain `GET /mcp` is expected (correct rejection of non-MCP requests); use it as a liveness probe.
- MCP streamable-HTTP requires a 3-step handshake before any tool call: (1) POST `initialize` → get `mcp-session-id` header, (2) POST `notifications/initialized` with that header (no response body), (3) POST the actual request. Omitting step 2 causes `-32602 Invalid request parameters`.

**Implemented tools**

| Tool | Signature | Notes |
|------|-----------|-------|
| `open_document` | `(path) → str` | Open a .numbers file by absolute POSIX path; returns document name |
| `close_document` | `(document, save=False) → str` | Close an open document; save=True saves before closing |
| `create_document` | `(name=None) → str` | Create a new blank document; returns its actual name |
| `list_documents` | `() → list[str]` | Names of all open Numbers documents |
| `list_sheets` | `(document) → list[str]` | Sheet names in a document |
| `add_sheet` | `(document, sheet_name) → str` | Add a new blank sheet; errors if name already exists |
| `delete_sheet` | `(document, sheet_name) → str` | Delete a sheet; errors if not found |
| `rename_sheet` | `(document, old_name, new_name) → str` | Rename a sheet; no-op if names identical; errors if old missing or new taken |
| `list_tables` | `(document, sheet) → list[str]` | Table names in a sheet |
| `add_table` | `(document, sheet, name, num_rows=4, num_columns=4) → str` | Add a new blank table to a sheet; errors if name already exists in the sheet |
| `remove_table` | `(document, sheet, table) → str` | Delete a table from a sheet; errors if not found |
| `rename_table` | `(document, sheet, old_name, new_name) → str` | Rename a table within a sheet |
| `get_table_info` | `(document, sheet, table) → dict` | Returns name, row_count, column_count, header_row_count, header_column_count, footer_row_count |
| `set_table_headers` | `(document, sheet, table, *, header_rows, header_columns, footer_rows) → str` | Set number of header/footer rows and columns (all optional) |
| `get_table_layout` | `(document, sheet, table) → dict` | Returns x, y (position in points), width, height on the canvas |
| `set_table_layout` | `(document, sheet, table, *, x, y, width, height) → str` | Set position and/or size of the table on its canvas (all optional) |
| `set_table_locked` | `(document, sheet, table, locked) → str` | Lock or unlock a table (locked tables can't be moved/resized) |
| `resize_table` | `(document, sheet, table, num_rows, num_columns) → str` | Set row and column count; call before writing beyond the default 4-column boundary (-10006) |
| `insert_row` | `(document, sheet, table, before_row) → str` | Insert a blank row before the given row; all rows below shift down |
| `insert_column` | `(document, sheet, table, before_column) → str` | Insert a blank column before the given column |
| `remove_row` | `(document, sheet, table, row) → str` | Remove a row; all rows below shift up |
| `remove_column` | `(document, sheet, table, column) → str` | Remove a column; all columns to the right shift left |
| `sort_table` | `(document, sheet, table, sort_column, ascending=True) → None` | Sort rows by column using Numbers' native sort |
| `transpose_table` | `(document, sheet, table) → str` | Transpose the entire table (swap all rows and columns) |
| `get_cell` | `(document, sheet, table, row, column) → str` | Single cell; `formatted value` so numbers/dates match the UI |
| `get_range` | `(document, sheet, table, start_row, start_col, end_row, end_col) → list[list[str]]` | Rectangular block; max 1 000 cells |
| `get_sheet_as_table` | `(document, sheet, table) → list[list[str]]` | Entire used range; auto-detects bounds; max 2 000 cells |
| `get_cell_formula` | `(document, sheet, table, row, column) → str \| None` | Formula string (e.g. `"=SUM(A1:A5)"`), or None if no formula. Read-only |
| `get_cell_format` | `(document, sheet, table, row, column) → dict` | Returns font_name, font_size, bold, italic, alignment, number_format, text_color ([r,g,b] or None), background_color ([r,g,b] or None), text_wrap, vertical_alignment |
| `get_column_width` | `(document, sheet, table, column) → float` | Column width in points |
| `get_row_height` | `(document, sheet, table, row) → float` | Row height in points |
| `set_cell` | `(document, sheet, table, row, column, value, *, number_format, bold, italic, alignment, font_size, text_color, background_color, text_wrap, vertical_alignment, currency_symbol, decimal_places) → None` | Write one cell; `None`/`""` clears; all formatting params optional |
| `set_range` | `(document, sheet, table, start_row, start_col, values, *, number_format, bold, italic, alignment, font_size, text_color, background_color, text_wrap, vertical_alignment, currency_symbol, decimal_places) → None` | Write a block; formatting applies to all cells; max 1 000 cells |
| `merge_cells` | `(document, sheet, table, start_row, start_col, end_row, end_col) → str` | Merge a rectangular cell region; non-top-left content discarded |
| `unmerge_cells` | `(document, sheet, table, start_row, start_col, end_row, end_col) → str` | Unmerge a merged region |
| `clear_range` | `(document, sheet, table, start_row, start_col, end_row, end_col) → str` | Clear content AND formatting in a range (equivalent to Delete key) |
| `export_document` | `(document, path, format="numbers") → str` | Export to `"numbers"` (.numbers), `"pdf"`, `"xlsx"`, or `"csv"` |
| `set_row_format` | `(document, sheet, table, row, *, bold, italic, alignment, number_format, font_size, text_color, background_color, text_wrap, vertical_alignment) → str` | Apply formatting to all cells in a row |
| `set_column_format` | `(document, sheet, table, column, *, bold, italic, alignment, number_format, font_size, text_color, background_color, text_wrap, vertical_alignment) → str` | Apply formatting to all cells in a column |
| `set_column_width` | `(document, sheet, table, column, width) → str` | Set column width in points |
| `set_row_height` | `(document, sheet, table, row, height) → str` | Set row height in points |

All row/column indices are **1-based**. `set_range` generates one multi-statement AppleScript script so the entire write is a single `osascript` call.

### AppleScript bridge

`server/src/numbridge/numbers_bridge.py`

- `open_document` uses `open POSIX file "path"` — path is validated with `os.path.exists` before the AppleScript call to give a clean `ValueError` rather than a raw AppleScript error.
- `close_document` uses `close document "name" saving yes/no`. Existence check is a separate loop from the close (same mutation-safety pattern as `delete_sheet`). `save=True` on an unsaved Untitled document will raise `NumbersError` — Numbers requires a file path to save to.
- `create_document` uses `make new document with properties {name:"…"}` (or without properties when no name is given). Numbers assigns "Untitled N" automatically. The document is in-memory only until saved.
- `_run(script, timeout=_TIMEOUT)` — executes via `osascript -e`, raises `NumbersError` on non-zero exit. `timeout` is optional; `export_document` passes `_SHEET_TIMEOUT` (60 s).
- `_as_value(v)` — converts a Python value to an AppleScript literal: `int`/`float` → bare number (numeric cell), `str` → quoted string (text cell), `None`/`""` → `""` (clears cell). `bool` is checked before `int` to avoid Python's bool-is-int subclass coercion.
- `_color_to_as([r,g,b])` — converts 0–255 per channel to AppleScript `{r,g,b}` (0–65535 per channel, multiply by 257). `_parse_color(s)` reverses the conversion (divide by 257, round). Colors read back from Numbers may differ slightly from the values written due to Numbers' internal rounding.
- `get_range` uses `formatted value` and a **collect-then-serialize** pattern: all rows are gathered into an AppleScript list-of-lists first, then serialized with tab+linefeed delimiters in a single pass *after* the loop. Setting `text item delimiters` inside the row loop corrupts the outer string accumulator (only the last row survives).
- `get_range` uses `.rstrip("\r\n")` — not `.strip()` — on raw output. `.strip()` eats the trailing `\t` on the last row, silently dropping trailing empty cells.
- Separate timeouts: `_TIMEOUT = 10 s` (single-cell/list calls), `_RANGE_TIMEOUT = 30 s` (grid reads/writes), `_SHEET_TIMEOUT = 60 s` (whole-sheet scan+read, export).
- `set_cell` / `set_range` optional formatting: `number_format` ("currency" | "number" | "percentage" | "text") maps to AppleScript constants `currency` / `number` / `percent` / `text` — note `percentage` → `percent`. The `date` format is excluded because `date and time` collides with AppleScript's built-in date type and cannot be set in plain-text osascript. `bold` / `italic` are not direct cell properties — implemented by reading the current PostScript font name (`font name of cell`), parsing the hyphen-delimited style suffix (e.g. `HelveticaNeue-BoldItalic`), and rewriting it. `currency_symbol` and `decimal_places` are accepted but silently ignored — not in the Numbers scripting dictionary. For `set_range` with bold/italic, the entire font grid is read first in one AppleScript call before the batch write.
- `get_cell_format` reads 8 properties (`font name`, `font size`, `alignment`, `format`, `text color`, `background color`, `text wrap`, `vertical alignment`) in a single osascript call, serialized with `"||"` delimiter. Colors are serialized as `"r,g,b"` (0–65535) or `""` for missing value. Bold/italic are derived by parsing the PostScript font-name suffix.
- `set_cell` / `set_range` / `set_row_format` / `set_column_format` accept `text_color`, `background_color` (as `[r,g,b]` lists, 0–255), `text_wrap` (bool), and `vertical_alignment` ("top"|"center"|"bottom"). These are passed through `_fmt_stmts` for single-cell writes, and added inline for row/column-wide writes.
- `get_cell_formula` reads the `formula` property (read-only in the scripting dictionary); returns `None` when `formula is missing value`.
- `get_sheet_as_table` backward-scans `row count`/`column count` to find the last non-empty row and column, then reads the block with the same collect-then-serialize pattern. Returns `""` from AppleScript for empty sheets; returns `"OVERLIMIT:R:C"` sentinel when the used range exceeds 2 000 cells (Python raises `ValueError`).
- `sort_table` / `transpose_table` are issued from within `tell sheet` (not `tell table`) — both take the table as their direct parameter. For `sort_table`: the column reference must be scoped as `column N of table "…"` and the direction keyword is `direction`, not `in direction`.
- `rename_table` uses the same two-loop sentinel pattern as `rename_sheet`: first scan for name conflicts, then rename.
- `insert_row` / `remove_row` use `add row above row N` / `remove row N` within `tell table`. Similarly `insert_column` / `remove_column` use `add column before column N` / `remove column N`.
- `merge_cells` / `unmerge_cells` / `clear_range` use `merge range "A1:C3"` / `unmerge range "A1:C3"` / `clear range "A1:C3"` within `tell table`. The `clear` command removes **both content and formatting**. Range addresses are built from `_col_letter(col) + str(row)`.
- `transpose_table` uses `transpose table "…"` from within `tell sheet`. The SDEF `transpose` command takes a `table` as its direct parameter — it transposes the entire table, not a sub-range. Sub-range transpose is not supported by the scripting API.
- `export_document` uses `export to POSIX file "…" as <format>` within `tell document`. SDEF format enum values: `Numbers 09` (.numbers), `PDF`, `Microsoft Excel` (.xlsx), `CSV`. The parent directory must exist; the file is overwritten if it exists.
- `get_table_info` / `set_table_headers` read/write `header row count`, `header column count`, `footer row count` on the table object. Numbers allows 0–5 header rows, 0–1 header columns, 0–5 footer rows.
- `get_table_layout` / `set_table_layout` read/write `position` (a 2-element list), `width`, and `height` on the table (iWork item properties). When only one of `x`/`y` is supplied to `set_table_layout`, the other coordinate is read first to avoid partial updates.
- `set_table_locked` writes `locked` on the table object.
- `remove_table` uses the same two-loop sentinel pattern as `delete_sheet`: existence check in one loop, then `delete table "…"` outside it. Deleting inside the iteration loop triggers AppleScript -1728.
- `add_table` checks for name collisions with a sentinel loop inside `tell sheet`, then calls `make new table with properties {name:"…"}` in the same `tell sheet` block (Numbers respects the `tell sheet` scope for placement). `row count` / `column count` cannot be passed as properties in the `make` record literal — AppleScript parses them as keywords — so dimensions are set via `set row count to N` / `set column count to N` inside a `tell newTable` block immediately after creation. Returns sentinel `"EXISTS"` when the name is taken.
- `add_sheet` / `delete_sheet` / `rename_sheet` use standard AppleScript `make` / `delete` / `set name of` on sheet objects. Each does an existence check inside the same osascript call (returning sentinel strings `"OK"` / `"EXISTS"` / `"NOT_FOUND"` / `"NEW_EXISTS"`) to avoid a separate round-trip. Numbers inserts new sheets after the currently active sheet regardless of the `at end of sheets` location specifier.
- `delete_sheet` separates the existence-check loop from the `delete` call — using `delete sheet "name"` **after** the loop rather than `delete s` **inside** it. Deleting `s` while iterating `repeat with s in sheets` triggers AppleScript `-1728` ("Can't get item N of every sheet of document"). This applies to any destructive mutation of a collection mid-iteration in AppleScript.
- `resize_table` sets `row count` and `column count` directly on the table object (`set row count to N`). New documents default to 4 columns — writing beyond the current boundary raises AppleScript `-10006`. Always call `resize_table` before `set_cell` / `set_range` when targeting columns 5+.
- `get_column_width` / `set_column_width` use `width of column N` inside `tell table`. Similarly `get_row_height` / `set_row_height` use `height of row N`.
- `set_row_format` / `set_column_format` — use `cell N of row R` (index-based, not address-based) for the inner loop. Both short-circuit immediately (no subprocess call) when all formatting params are None. Bold/italic uses the same two-step pattern as `set_range`. `_get_count_and_fonts` is a shared internal helper that returns `(count, [font_names])` in one round-trip.

**Not implementable via Numbers' AppleScript scripting dictionary:**
- `duplicate_sheet` — Numbers returns `"Sheets can not be copied" (-1717)` for any `duplicate`/`copy` on sheets, in both AppleScript and JXA.
- `decimal_places` / `currency_symbol` — not properties of the `range`/`cell` class in the scripting dictionary; accepted but silently ignored.
- `date` number format — the `date and time` enum value collides with AppleScript's built-in `date` type and cannot be set via plain-text osascript.
- Writing formulas via the `formula` property — it is read-only in the SDEF. **Workaround:** pass the formula string as the cell value (e.g. `"=SUM(A1:A5)"`); Numbers interprets any value string starting with `=` as a formula, identical to typing in the UI.
- Sub-range transpose — `transpose` takes a table, not a range; the range object returns `-1708` for this verb.
- Password management — `set password` / `remove password` are in the SDEF but excluded for security; there is no interactive confirmation mechanism.
- Canvas objects (images, shapes, text boxes) — the iWork canvas model is out of scope for tabular data access.
- Selection-based operations — `selection` is a UI-state property; it is unreliable in background automation and intentionally not exposed.

## Key constraints

- **macOS 13+ only** — `SMAppService` (login items) and the SF Symbols used require Ventura or later.
- **No Xcode project file** — the Swift side uses SPM (`Package.swift`) + a `Makefile` to produce the `.app` bundle. Open `Launcher/Package.swift` in Xcode for IDE support.
- **`uv` required** — the launcher hard-fails with a menu-bar error if `uv` is not installed.
