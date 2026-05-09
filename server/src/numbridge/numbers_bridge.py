"""AppleScript bridge to Apple Numbers.

All public functions run synchronously via osascript.  They raise NumbersError
on any AppleScript error (Numbers not running, document not found, etc.).
"""
import subprocess

_TIMEOUT = 10  # seconds per osascript call


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


def _q(s: str) -> str:
    """Escape a Python string for safe embedding inside an AppleScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


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


def get_cell(document: str, sheet: str, row: int, column: int) -> str:
    """Return the displayed value of a cell as a string.

    Uses ``formatted value`` so numbers, dates, and currency appear exactly
    as they do in the Numbers UI.  Empty cells return an empty string.
    Row and column are 1-indexed.
    """
    doc = _q(document)
    sht = _q(sheet)
    addr = f"{_col_letter(column)}{row}"
    raw = _run(
        f'tell application "Numbers"\n'
        f'    tell document "{doc}"\n'
        f'        tell sheet "{sht}"\n'
        f"            tell table 1\n"
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
