"""Unit tests for numbers_bridge.py.

Covers pure helpers (no I/O), ValueError guards, NumbersError propagation,
and the subprocess interactions for get_range / set_range / get_sheet_as_table
via mocked subprocess.run.
"""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from numbridge.numbers_bridge import (
    NumbersError,
    _as_list,
    _as_value,
    _col_letter,
    _parse_grid,
    _q,
    _run,
    add_sheet,
    create_document,
    delete_sheet,
    get_range,
    get_sheet_as_table,
    rename_sheet,
    set_range,
    sort_table,
)


# ---------------------------------------------------------------------------
# Helpers — pure functions, no I/O
# ---------------------------------------------------------------------------

class TestQ:
    def test_plain_string(self):
        assert _q("hello") == "hello"

    def test_escapes_double_quote(self):
        assert _q('say "hi"') == 'say \\"hi\\"'

    def test_escapes_backslash(self):
        assert _q("a\\b") == "a\\\\b"

    def test_escapes_both(self):
        assert _q('"\\') == '\\"\\\\'


class TestAsValue:
    def test_none_returns_empty_string_literal(self):
        assert _as_value(None) == '""'

    def test_empty_string_returns_empty_string_literal(self):
        assert _as_value("") == '""'

    def test_bool_true_before_int_check(self):
        # bool is a subclass of int; True must not become repr(True) = "True"
        assert _as_value(True) == "1"

    def test_bool_false(self):
        assert _as_value(False) == "0"

    def test_int(self):
        assert _as_value(42) == "42"

    def test_negative_int(self):
        assert _as_value(-7) == "-7"

    def test_float(self):
        assert _as_value(3.14) == "3.14"

    def test_string(self):
        assert _as_value("hello") == '"hello"'

    def test_string_with_quotes(self):
        assert _as_value('say "hi"') == '"say \\"hi\\""'


class TestColLetter:
    def test_first_column(self):
        assert _col_letter(1) == "A"

    def test_last_single_letter(self):
        assert _col_letter(26) == "Z"

    def test_first_double_letter(self):
        assert _col_letter(27) == "AA"

    def test_second_double_letter(self):
        assert _col_letter(28) == "AB"

    def test_triple_letter(self):
        assert _col_letter(703) == "AAA"


class TestAsList:
    def test_basic_split(self):
        assert _as_list("a\nb\nc") == ["a", "b", "c"]

    def test_filters_empty_lines(self):
        assert _as_list("a\n\nb") == ["a", "b"]

    def test_empty_string(self):
        assert _as_list("") == []

    def test_single_item(self):
        assert _as_list("doc") == ["doc"]


class TestParseGrid:
    def test_single_row(self):
        assert _parse_grid("a\tb\tc") == [["a", "b", "c"]]

    def test_multiple_rows(self):
        assert _parse_grid("a\tb\n1\t2") == [["a", "b"], ["1", "2"]]

    def test_preserves_empty_cells(self):
        # Empty trailing cell must survive (not be stripped)
        assert _parse_grid("a\t\t") == [["a", "", ""]]

    def test_filters_empty_lines(self):
        assert _parse_grid("a\tb\n") == [["a", "b"]]


# ---------------------------------------------------------------------------
# create_document
# ---------------------------------------------------------------------------

class TestCreateDocument:
    def test_returns_document_name_with_explicit_name(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="My Sheet")) as mock:
            result = create_document("My Sheet")
        assert result == "My Sheet"
        script = mock.call_args[0][0][2]
        assert "My Sheet" in script

    def test_returns_document_name_without_name(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="Untitled")) as mock:
            result = create_document()
        assert result == "Untitled"
        script = mock.call_args[0][0][2]
        assert "properties" not in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="Numbers not running", returncode=1)):
            with pytest.raises(NumbersError):
                create_document("Test")


# ---------------------------------------------------------------------------
# _run — subprocess interaction
# ---------------------------------------------------------------------------

def _make_completed(stdout="", stderr="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


class TestRun:
    def test_returns_stripped_stdout(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="  result  ")) as mock:
            assert _run("script") == "result"
            mock.assert_called_once()

    def test_raises_numbers_error_on_nonzero(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="bad thing", returncode=1)):
            with pytest.raises(NumbersError, match="bad thing"):
                _run("script")

    def test_error_message_falls_back_to_exit_code(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="", returncode=2)):
            with pytest.raises(NumbersError, match="code 2"):
                _run("script")


# ---------------------------------------------------------------------------
# get_range — validation guards
# ---------------------------------------------------------------------------

class TestGetRange:
    def test_raises_for_inverted_rows(self):
        with pytest.raises(ValueError, match="inverted"):
            get_range("doc", "sheet", "table", 5, 1, 2, 3)

    def test_raises_for_inverted_cols(self):
        with pytest.raises(ValueError, match="inverted"):
            get_range("doc", "sheet", "table", 1, 5, 3, 2)

    def test_raises_when_over_cell_limit(self):
        with pytest.raises(ValueError, match="1000"):
            get_range("doc", "sheet", "table", 1, 1, 50, 25)  # 1250 cells

    def test_returns_parsed_grid(self):
        raw = "a\tb\n1\t2\n"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=raw)):
            result = get_range("doc", "sheet", "table", 1, 1, 2, 2)
        assert result == [["a", "b"], ["1", "2"]]

    def test_preserves_trailing_empty_cell(self):
        # rstrip("\r\n") not strip() — trailing tab must survive
        raw = "a\tb\t\n"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=raw)):
            result = get_range("doc", "sheet", "table", 1, 1, 1, 3)
        assert result == [["a", "b", ""]]

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="Numbers not running", returncode=1)):
            with pytest.raises(NumbersError):
                get_range("doc", "sheet", "table", 1, 1, 2, 2)


# ---------------------------------------------------------------------------
# set_range — validation guards
# ---------------------------------------------------------------------------

class TestSetRange:
    def test_noop_on_empty_values(self):
        with patch("numbridge.numbers_bridge.subprocess.run") as mock:
            set_range("doc", "sheet", "table", 1, 1, [])
            mock.assert_not_called()

    def test_raises_when_over_cell_limit(self):
        values = [["x"] * 100 for _ in range(11)]  # 1100 cells
        with pytest.raises(ValueError, match="1000"):
            set_range("doc", "sheet", "table", 1, 1, values)

    def test_calls_subprocess_on_success(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            set_range("doc", "sheet", "table", 1, 1, [["a", 1], ["b", 2]])
            mock.assert_called_once()

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="oops", returncode=1)):
            with pytest.raises(NumbersError):
                set_range("doc", "sheet", "table", 1, 1, [["x"]])


# ---------------------------------------------------------------------------
# get_sheet_as_table — empty / overlimit / success
# ---------------------------------------------------------------------------

class TestGetSheetAsTable:
    def test_returns_empty_list_for_empty_sheet(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="")):
            assert get_sheet_as_table("doc", "sheet", "table") == []

    def test_raises_value_error_on_overlimit(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OVERLIMIT:50:50")):
            with pytest.raises(ValueError, match="2000"):
                get_sheet_as_table("doc", "sheet", "table")

    def test_overlimit_message_includes_dimensions(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OVERLIMIT:50:50")):
            with pytest.raises(ValueError, match="50×50"):
                get_sheet_as_table("doc", "sheet", "table")

    def test_returns_parsed_grid(self):
        raw = "Name\tScore\nAlice\t95\n"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=raw)):
            result = get_sheet_as_table("doc", "sheet", "table")
        assert result == [["Name", "Score"], ["Alice", "95"]]

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="Numbers not running", returncode=1)):
            with pytest.raises(NumbersError):
                get_sheet_as_table("doc", "sheet", "table")


# ---------------------------------------------------------------------------
# sort_table — validation guards and subprocess interactions
# ---------------------------------------------------------------------------

class TestSortTable:
    def test_raises_for_zero_column(self):
        with pytest.raises(ValueError, match="sort_column"):
            sort_table("doc", "sheet", "table", 0)

    def test_raises_for_negative_column(self):
        with pytest.raises(ValueError, match="sort_column"):
            sort_table("doc", "sheet", "table", -1)

    def test_calls_subprocess_ascending(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            sort_table("doc", "sheet", "table", 1)
            script = mock.call_args[0][0][2]
            assert "direction ascending" in script
            assert "column 1 of table" in script

    def test_calls_subprocess_descending(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            sort_table("doc", "sheet", "table", 3, ascending=False)
            script = mock.call_args[0][0][2]
            assert "direction descending" in script
            assert "column 3 of table" in script

    def test_default_direction_is_ascending(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            sort_table("doc", "sheet", "table", 2)
            script = mock.call_args[0][0][2]
            assert "ascending" in script

    def test_sort_called_outside_tell_table(self):
        # sort's direct parameter is a table reference, so it must be issued
        # from within tell sheet, not inside tell table.
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            sort_table("doc", "sheet", "table", 1)
            script = mock.call_args[0][0][2]
            assert 'sort table' in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="Numbers not running", returncode=1)):
            with pytest.raises(NumbersError):
                sort_table("doc", "sheet", "table", 1)


# ---------------------------------------------------------------------------
# add_sheet
# ---------------------------------------------------------------------------

class TestAddSheet:
    def test_returns_success_message(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")):
            result = add_sheet("doc", "New Sheet")
        assert "New Sheet" in result

    def test_raises_value_error_when_sheet_exists(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="EXISTS")):
            with pytest.raises(ValueError, match="already exists"):
                add_sheet("doc", "Existing")

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="doc not found", returncode=1)):
            with pytest.raises(NumbersError):
                add_sheet("doc", "Sheet")


# ---------------------------------------------------------------------------
# delete_sheet
# ---------------------------------------------------------------------------

class TestDeleteSheet:
    def test_returns_success_message(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")):
            result = delete_sheet("doc", "Gone")
        assert "Gone" in result

    def test_deletes_by_name_not_by_loop_variable(self):
        # Regression: deleting `s` inside `repeat with s in sheets` raises
        # AppleScript -1728 (mutation while iterating). The script must use
        # `delete sheet "name"` *after* the loop exits.
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")) as mock:
            delete_sheet("doc", "MySheet")
            script = mock.call_args[0][0][2]
        # Must delete by name reference, not by the loop variable `s`
        assert 'delete sheet "MySheet"' in script

    def test_raises_value_error_when_not_found(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="NOT_FOUND")):
            with pytest.raises(ValueError, match="not found"):
                delete_sheet("doc", "Missing")

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="doc not found", returncode=1)):
            with pytest.raises(NumbersError):
                delete_sheet("doc", "Sheet")


# ---------------------------------------------------------------------------
# rename_sheet
# ---------------------------------------------------------------------------

class TestRenameSheet:
    def test_returns_success_message(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")):
            result = rename_sheet("doc", "Old", "New")
        assert "Old" in result and "New" in result

    def test_noop_when_names_identical(self):
        with patch("numbridge.numbers_bridge.subprocess.run") as mock:
            result = rename_sheet("doc", "Same", "Same")
            mock.assert_not_called()
        assert "already has that name" in result

    def test_raises_value_error_when_new_name_taken(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="NEW_EXISTS")):
            with pytest.raises(ValueError, match="already exists"):
                rename_sheet("doc", "Old", "Taken")

    def test_raises_value_error_when_old_name_not_found(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="NOT_FOUND")):
            with pytest.raises(ValueError, match="not found"):
                rename_sheet("doc", "Ghost", "New")

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="doc not found", returncode=1)):
            with pytest.raises(NumbersError):
                rename_sheet("doc", "Old", "New")
