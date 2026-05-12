# NumBridge

NumBridge lets Claude read, write, and manage Apple Numbers spreadsheets. It runs as a menu-bar app that keeps a local MCP server alive in the background, so Claude Desktop and Claude Code can interact with Numbers documents — opening, creating, reading, writing, formatting, sorting, and managing sheets.

## Requirements

- macOS 13 (Ventura) or later
- Apple Numbers (any recent version)
- [uv](https://docs.astral.sh/uv/) — Python package manager used to run the server
- Xcode Command Line Tools (`xcode-select --install`) to build the launcher

## Installation

```bash
git clone <repo>
cd numbridge/Launcher
make install   # builds, copies to /Applications, and launches
```

NumBridge registers itself as a login item, so it starts automatically on next login. The menu-bar icon (⊞) shows the server status.

## Connecting to Claude

### Claude Code

```bash
claude mcp add --transport http --scope user numbridge http://127.0.0.1:8765/mcp
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "numbridge": {
      "command": "/Users/YOUR_USERNAME/.local/bin/uv",
      "args": ["run", "--directory", "/path/to/numbridge/server", "python", "-m", "numbridge", "--stdio"]
    }
  }
}
```

Replace `/Users/YOUR_USERNAME/.local/bin/uv` with the output of `which uv`, and `/path/to/numbridge/server` with the absolute path to the `server/` directory in this repo. Then quit and relaunch Claude Desktop.

## Tools

Claude navigates Numbers documents through a four-level hierarchy: **document → sheet → table → cells**. All row and column indices are 1-based.

### Document management

| Tool | Description |
|------|-------------|
| `list_documents` | Names of all currently open Numbers documents |
| `open_document` | Open a `.numbers` file by absolute POSIX path; returns the document name |
| `close_document` | Close an open document (optionally save before closing) |
| `create_document` | Create a new blank in-memory document; returns the assigned name |

### Sheet management

| Tool | Description |
|------|-------------|
| `list_sheets` | Sheet names in a document |
| `add_sheet` | Add a new blank sheet to a document |
| `delete_sheet` | Delete a sheet (errors if the sheet doesn't exist) |
| `rename_sheet` | Rename a sheet (errors if the old name doesn't exist or new name is taken) |

### Table management

| Tool | Description |
|------|-------------|
| `list_tables` | Table names in a sheet |
| `add_table` | Add a new blank table to a sheet (errors if the name is already taken) |
| `remove_table` | Delete a table from a sheet (errors if the table doesn't exist) |
| `rename_table` | Rename a table within a sheet |
| `get_table_info` | Row/column counts and header/footer counts for a table |
| `set_table_headers` | Set the number of header rows, header columns, and footer rows |
| `get_table_layout` | Position (x, y) and size (width, height) of a table on the canvas |
| `set_table_layout` | Move or resize a table on the canvas |
| `set_table_locked` | Lock or unlock a table (locked tables can't be moved or resized) |
| `resize_table` | Set a table's row and column count (call before writing beyond the default 4-column boundary) |
| `insert_row` | Insert a blank row before the specified row |
| `insert_column` | Insert a blank column before the specified column |
| `remove_row` | Remove a row from a table |
| `remove_column` | Remove a column from a table |
| `sort_table` | Sort table rows by a column (ascending or descending) |
| `transpose_table` | Transpose the entire table (swap all rows and columns) |

### Reading data

| Tool | Description |
|------|-------------|
| `get_cell` | Read one cell (returns the displayed value) |
| `get_range` | Read a rectangular block of cells (max 1 000) |
| `get_sheet_as_table` | Read the entire used range of a table (max 2 000 cells) |
| `get_cell_formula` | Read the formula string for a cell (null if no formula) |

### Reading formats

| Tool | Description |
|------|-------------|
| `get_cell_format` | Query font, size, bold, italic, alignment, number format, text colour, background colour, text wrap, and vertical alignment |
| `get_column_width` | Column width in points |
| `get_row_height` | Row height in points |

### Writing data

| Tool | Description |
|------|-------------|
| `set_cell` | Write one cell — pass a number, string, or null to clear; supports all formatting options |
| `set_range` | Write a block of cells in one call (max 1 000); same formatting options as `set_cell` |
| `merge_cells` | Merge a rectangular cell region into a single cell |
| `unmerge_cells` | Unmerge a merged cell region |
| `clear_range` | Clear content and formatting in a cell range (equivalent to Delete key) |
| `export_document` | Export to `.numbers`, PDF, Excel (`.xlsx`), or CSV |

### Writing formats

| Tool | Description |
|------|-------------|
| `set_column_format` | Apply bold, italic, alignment, font size, number format, colours, text wrap, or vertical alignment to every cell in a column |
| `set_row_format` | Apply bold, italic, alignment, font size, number format, colours, text wrap, or vertical alignment to every cell in a row |
| `set_column_width` | Set column width in points |
| `set_row_height` | Set row height in points |

## Usage

Once connected, just ask Claude naturally:

> "What sheets are in my Budget 2025 document?"

> "Read the Q1 summary table from the Sales sheet."

> "Set cell B3 to 42 in the Expenses table."

> "Fill in the monthly totals column based on the rows above."

## Menu-bar controls

Click the NumBridge icon in the menu bar to:

- **Stop / Start** the server manually
- See the MCP endpoint URL and server PID
- Open the server log (`~/Library/Logs/NumBridge/server.log`)

The server restarts automatically if it exits unexpectedly.

## Configuration

| Environment variable | Default | Effect |
|---------------------|---------|--------|
| `NUMBRIDGE_PORT` | `8765` | Port the MCP server listens on |
| `NUMBRIDGE_SERVER_DIR` | auto-detected | Override the Python server directory |

Set these in `~/.zshenv` (or equivalent) before launching the app, or export them in a launchd plist if you need them system-wide.

## Running the server without the launcher

```bash
cd server
uv run python -m numbridge
```

Useful for development or when running on a headless machine via SSH.

## Building from source

```bash
cd Launcher
make run      # build + launch (leaves app in dist/)
make install  # build + copy to /Applications + launch
make bundle   # build only
```

The Makefile produces a proper `.app` bundle with an ad-hoc codesign. For distribution outside your own machine, replace `codesign --sign -` with a Developer ID certificate and run `xcrun notarytool` before shipping.
