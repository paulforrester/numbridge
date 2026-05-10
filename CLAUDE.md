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
- Transport: **streamable-http** — listens on `127.0.0.1:8765` (override with `NUMBRIDGE_PORT`).
- MCP endpoint: `http://127.0.0.1:8765/mcp` — configure this URL in Claude Desktop / Claude Code.
- Tools are registered with `@mcp.tool()` decorators; all Numbers I/O goes through `numbers_bridge.py` via `subprocess` + `osascript`.
- 406 on a plain `GET /mcp` is expected (correct rejection of non-MCP requests); use it as a liveness probe.

**Implemented tools**

| Tool | Signature | Notes |
|------|-----------|-------|
| `list_documents` | `() → list[str]` | Names of all open Numbers documents |
| `list_sheets` | `(document) → list[str]` | Sheet names in a document |
| `list_tables` | `(document, sheet) → list[str]` | Table names in a sheet |
| `get_cell` | `(document, sheet, table, row, column) → str` | Single cell; `formatted value` so numbers/dates match the UI |
| `get_range` | `(document, sheet, table, start_row, start_col, end_row, end_col) → list[list[str]]` | Rectangular block; max 1 000 cells |
| `set_cell` | `(document, sheet, table, row, column, value) → None` | Write one cell; `None`/`""` clears |
| `set_range` | `(document, sheet, table, start_row, start_col, values) → None` | Write a block; rows may be jagged; max 1 000 cells |
| `sort_table` | `(document, sheet, table, sort_column, ascending=True) → None` | Sort rows by column using Numbers' native sort |
| `add_sheet` | `(document, sheet_name) → str` | Add a new blank sheet; errors if name already exists |
| `delete_sheet` | `(document, sheet_name) → str` | Delete a sheet; errors if not found |
| `rename_sheet` | `(document, old_name, new_name) → str` | Rename a sheet; no-op if names identical; errors if old missing or new taken |
| `get_sheet_as_table` | `(document, sheet, table) → list[list[str]]` | Entire used range; auto-detects bounds; max 2 000 cells |

All row/column indices are **1-based**. `set_range` generates one multi-statement AppleScript script so the entire write is a single `osascript` call.

### AppleScript bridge

`server/src/numbridge/numbers_bridge.py`

- `_run(script)` — executes via `osascript -e`, raises `NumbersError` on non-zero exit.
- `_as_value(v)` — converts a Python value to an AppleScript literal: `int`/`float` → bare number (numeric cell), `str` → quoted string (text cell), `None`/`""` → `""` (clears cell). `bool` is checked before `int` to avoid Python's bool-is-int subclass coercion.
- `get_range` uses `formatted value` and a **collect-then-serialize** pattern: all rows are gathered into an AppleScript list-of-lists first, then serialized with tab+linefeed delimiters in a single pass *after* the loop. Setting `text item delimiters` inside the row loop corrupts the outer string accumulator (only the last row survives).
- `get_range` uses `.rstrip("\r\n")` — not `.strip()` — on raw output. `.strip()` eats the trailing `\t` on the last row, silently dropping trailing empty cells.
- Separate timeouts: `_TIMEOUT = 10 s` (single-cell/list calls), `_RANGE_TIMEOUT = 30 s` (grid reads/writes), `_SHEET_TIMEOUT = 60 s` (whole-sheet scan+read).
- `get_sheet_as_table` backward-scans `row count`/`column count` to find the last non-empty row and column, then reads the block with the same collect-then-serialize pattern. Returns `""` from AppleScript for empty sheets; returns `"OVERLIMIT:R:C"` sentinel when the used range exceeds 2 000 cells (Python raises `ValueError`).
- `sort_table` issues `sort table "…" by column N of table "…" direction ascending/descending` from within `tell sheet` — **not** inside `tell table`. Two non-obvious constraints: (1) the column reference must be scoped to the table (`column N of table "…"`) — bare `column N` in a `tell sheet` context is ambiguous; (2) the direction keyword is plain `direction`, not `in direction` — `in` would be parsed as the start of the `in rows` parameter name, causing a syntax error.
- `add_sheet` / `delete_sheet` / `rename_sheet` use standard AppleScript `make` / `delete` / `set name of` on sheet objects. Each does an existence check inside the same osascript call (returning sentinel strings `"OK"` / `"EXISTS"` / `"NOT_FOUND"` / `"NEW_EXISTS"`) to avoid a separate round-trip. Numbers inserts new sheets after the currently active sheet regardless of the `at end of sheets` location specifier.
- `duplicate_sheet` is **not implementable** — Numbers returns `"Sheets can not be copied" (-1717)` for any `duplicate`/`copy` operation on sheets, in both AppleScript and JXA.

## Key constraints

- **macOS 13+ only** — `SMAppService` (login items) and the SF Symbols used require Ventura or later.
- **No Xcode project file** — the Swift side uses SPM (`Package.swift`) + a `Makefile` to produce the `.app` bundle. Open `Launcher/Package.swift` in Xcode for IDE support.
- **`uv` required** — the launcher hard-fails with a menu-bar error if `uv` is not installed.
