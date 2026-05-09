# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

NumBridge is a macOS MCP server that lets Claude interact with Apple Numbers via AppleScript. Three layers:

1. **`Launcher/`** — SwiftUI/AppKit menu-bar app (macOS 13+). Registers as a login item, spawns the Python server, monitors/restarts it, and shows status in the menu bar.
2. **`server/`** — Python MCP server (`uv`-managed). Exposes Numbers operations as MCP tools. Entry point: `python -m numbridge`.
3. **AppleScript bridge** — to be added inside `server/src/numbridge/` as the Numbers tools are implemented.

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

# Run tests (once added)
uv run pytest
```

`uv` resolves dependencies from `pyproject.toml` automatically. No virtualenv activation needed.

## Architecture details

### ServerManager (Swift)

`Launcher/Sources/NumBridgeLauncher/ServerManager.swift`

- `@MainActor` `ObservableObject`; all state mutations happen on the main actor.
- Calls `uv run python -m numbridge` with `currentDirectoryURL` set to the server dir.
- Server directory lookup order: `NUMBRIDGE_SERVER_DIR` env var → `<Bundle>/Resources/server/` → sibling `dist/server/` symlink.
- `uv` is searched in `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin` — PATH enrichment covers Homebrew on both Apple Silicon and Intel.
- On unexpected exit, restarts after 3 s. `stop()` sends SIGTERM, then SIGKILL after 2 s grace if still alive. `shouldAutoRestart` flag prevents restarts during intentional shutdown.
- Server stdout/stderr → `~/Library/Logs/NumBridge/server.log`.

### StatusBarController (Swift)

`Launcher/Sources/NumBridgeLauncher/StatusBarController.swift`

- Subscribes to `ServerManager.$status` via Combine, rebuilds `NSMenu` on every change.
- SF Symbols used: `tablecells` (stopped/starting), `tablecells.fill` (running), `exclamationmark.triangle.fill` (error). All marked `.isTemplate = true` for light/dark menu bar compatibility.

### Python MCP server

`server/src/numbridge/server.py`

- Uses the `mcp` SDK. Tools are registered with `@app.list_tools()` / `@app.call_tool()`.
- Communicates over stdio (MCP standard). The launcher owns the process and does not open any sockets.
- AppleScript calls will live in a separate `numbers_bridge.py` module and be invoked via `subprocess` + `osascript`.

## Key constraints

- **macOS 13+ only** — `SMAppService` (login items) and the SF Symbols used require Ventura or later.
- **No Xcode project file** — the Swift side uses SPM (`Package.swift`) + a `Makefile` to produce the `.app` bundle. Open `Launcher/Package.swift` in Xcode for IDE support.
- **`uv` required** — the launcher hard-fails with a menu-bar error if `uv` is not installed.
