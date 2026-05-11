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
    _color_to_as,
    _parse_color,
    _parse_grid,
    _q,
    _run,
    add_sheet,
    clear_range,
    close_document,
    create_document,
    delete_sheet,
    export_document,
    get_cell_format,
    get_cell_formula,
    get_column_width,
    get_range,
    get_row_height,
    get_sheet_as_table,
    get_table_info,
    get_table_layout,
    insert_column,
    insert_row,
    merge_cells,
    open_document,
    remove_column,
    remove_row,
    rename_sheet,
    rename_table,
    resize_table,
    set_column_format,
    set_column_width,
    set_range,
    set_row_format,
    set_row_height,
    set_table_headers,
    set_table_layout,
    set_table_locked,
    sort_table,
    transpose_table,
    unmerge_cells,
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
# open_document
# ---------------------------------------------------------------------------

class TestOpenDocument:
    def test_raises_value_error_for_missing_file(self):
        with pytest.raises(ValueError, match="File not found"):
            open_document("/nonexistent/path/file.numbers")

    def test_returns_document_name_on_success(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="Budget")):
            with patch("numbridge.numbers_bridge.os.path.exists", return_value=True):
                result = open_document("/some/Budget.numbers")
        assert result == "Budget"

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="can't open", returncode=1)):
            with patch("numbridge.numbers_bridge.os.path.exists", return_value=True):
                with pytest.raises(NumbersError):
                    open_document("/some/file.numbers")


# ---------------------------------------------------------------------------
# close_document
# ---------------------------------------------------------------------------

class TestCloseDocument:
    def test_returns_success_message(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")):
            result = close_document("My Doc")
        assert "My Doc" in result

    def test_raises_value_error_when_not_open(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="NOT_FOUND")):
            with pytest.raises(ValueError, match="not open"):
                close_document("Missing Doc")

    def test_default_save_is_false(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")) as mock:
            close_document("My Doc")
            script = mock.call_args[0][0][2]
        assert "saving no" in script

    def test_save_true_uses_saving_yes(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")) as mock:
            close_document("My Doc", save=True)
            script = mock.call_args[0][0][2]
        assert "saving yes" in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="Numbers not running", returncode=1)):
            with pytest.raises(NumbersError):
                close_document("My Doc")


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
# get_column_width / set_column_width
# ---------------------------------------------------------------------------

class TestGetColumnWidth:
    def test_returns_float(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="98.0")):
            assert get_column_width("doc", "Sheet 1", "Table 1", 2) == 98.0

    def test_raises_for_zero_column(self):
        with pytest.raises(ValueError, match="column"):
            get_column_width("doc", "Sheet 1", "Table 1", 0)

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                get_column_width("doc", "Sheet 1", "Table 1", 1)


class TestSetColumnWidth:
    def test_returns_confirmation(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()):
            result = set_column_width("doc", "Sheet 1", "Table 1", 3, 120.0)
        assert "120" in result and "3" in result

    def test_raises_for_zero_column(self):
        with pytest.raises(ValueError, match="column"):
            set_column_width("doc", "Sheet 1", "Table 1", 0, 100)

    def test_raises_for_zero_width(self):
        with pytest.raises(ValueError, match="width"):
            set_column_width("doc", "Sheet 1", "Table 1", 1, 0)

    def test_script_sets_width(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            set_column_width("doc", "Sheet 1", "Table 1", 2, 150.0)
            script = mock.call_args[0][0][2]
        assert "set width of column 2 to 150.0" in script


# ---------------------------------------------------------------------------
# get_row_height / set_row_height
# ---------------------------------------------------------------------------

class TestGetRowHeight:
    def test_returns_float(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="20.0")):
            assert get_row_height("doc", "Sheet 1", "Table 1", 1) == 20.0

    def test_raises_for_zero_row(self):
        with pytest.raises(ValueError, match="row"):
            get_row_height("doc", "Sheet 1", "Table 1", 0)

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                get_row_height("doc", "Sheet 1", "Table 1", 1)


class TestSetRowHeight:
    def test_returns_confirmation(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()):
            result = set_row_height("doc", "Sheet 1", "Table 1", 2, 40.0)
        assert "40" in result and "2" in result

    def test_raises_for_zero_row(self):
        with pytest.raises(ValueError, match="row"):
            set_row_height("doc", "Sheet 1", "Table 1", 0, 30)

    def test_raises_for_zero_height(self):
        with pytest.raises(ValueError, match="height"):
            set_row_height("doc", "Sheet 1", "Table 1", 1, 0)

    def test_script_sets_height(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            set_row_height("doc", "Sheet 1", "Table 1", 3, 30.0)
            script = mock.call_args[0][0][2]
        assert "set height of row 3 to 30.0" in script


# ---------------------------------------------------------------------------
# get_cell_format
# ---------------------------------------------------------------------------

class TestGetCellFormat:
    # Full 8-field payload: font||size||alignment||fmt||text_color||bg_color||wrap||valign
    def test_returns_dict_with_expected_keys(self):
        payload = "HelveticaNeue-Bold||14.0||left||automatic||||||false||top"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=payload)):
            result = get_cell_format("doc", "Sheet 1", "Table 1", 1, 1)
        assert result["font_name"] == "HelveticaNeue-Bold"
        assert result["font_size"] == 14.0
        assert result["bold"] is True
        assert result["italic"] is False
        assert result["alignment"] == "left"
        assert result["number_format"] == "automatic"
        assert result["text_color"] is None
        assert result["background_color"] is None
        assert result["text_wrap"] is False
        assert result["vertical_alignment"] == "top"

    def test_bold_italic_both_detected(self):
        payload = "HelveticaNeue-BoldItalic||12.0||center||number||||||false||center"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=payload)):
            result = get_cell_format("doc", "Sheet 1", "Table 1", 2, 3)
        assert result["bold"] is True
        assert result["italic"] is True

    def test_plain_font_is_not_bold_or_italic(self):
        payload = "HelveticaNeue||12.0||right||text||||||false||bottom"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=payload)):
            result = get_cell_format("doc", "Sheet 1", "Table 1", 1, 2)
        assert result["bold"] is False
        assert result["italic"] is False

    def test_text_color_parsed(self):
        # AppleScript returns 0-65535 per channel; Python gets 0-255
        payload = "Helvetica||12.0||left||automatic||0,0,0||||||false||top"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=payload)):
            result = get_cell_format("doc", "Sheet 1", "Table 1", 1, 1)
        assert result["text_color"] == [0, 0, 0]

    def test_background_color_parsed(self):
        payload = "Helvetica||12.0||left||automatic||||65535,0,0||false||top"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=payload)):
            result = get_cell_format("doc", "Sheet 1", "Table 1", 1, 1)
        assert result["background_color"] == [255, 0, 0]

    def test_text_wrap_true(self):
        payload = "Helvetica||12.0||left||automatic||||||true||top"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=payload)):
            result = get_cell_format("doc", "Sheet 1", "Table 1", 1, 1)
        assert result["text_wrap"] is True

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                get_cell_format("doc", "Sheet 1", "Table 1", 1, 1)


# ---------------------------------------------------------------------------
# set_row_format
# ---------------------------------------------------------------------------

class TestSetRowFormat:
    def test_raises_for_zero_row(self):
        with pytest.raises(ValueError, match="row"):
            set_row_format("doc", "Sheet 1", "Table 1", 0, alignment="left")

    def test_raises_for_invalid_alignment(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="3")):
            with pytest.raises(ValueError, match="alignment"):
                set_row_format("doc", "Sheet 1", "Table 1", 1, alignment="top")

    def test_raises_for_invalid_number_format(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="3")):
            with pytest.raises(ValueError, match="number_format"):
                set_row_format("doc", "Sheet 1", "Table 1", 1, number_format="date")

    def test_alignment_script_uses_cell_of_row_ref(self):
        # First call returns column count; second call applies formatting
        responses = [_make_completed(stdout="3"), _make_completed()]
        with patch("numbridge.numbers_bridge.subprocess.run",
                   side_effect=responses) as mock:
            set_row_format("doc", "Sheet 1", "Table 1", 2, alignment="center")
            apply_script = mock.call_args[0][0][2]
        assert "cell 1 of row 2" in apply_script
        assert "cell 3 of row 2" in apply_script
        assert "alignment" in apply_script

    def test_font_size_included_in_script(self):
        responses = [_make_completed(stdout="2"), _make_completed()]
        with patch("numbridge.numbers_bridge.subprocess.run",
                   side_effect=responses) as mock:
            set_row_format("doc", "Sheet 1", "Table 1", 1, font_size=16.0)
            apply_script = mock.call_args[0][0][2]
        assert "font size" in apply_script
        assert "16.0" in apply_script

    def test_nothing_to_format_returns_early(self):
        with patch("numbridge.numbers_bridge.subprocess.run") as mock:
            result = set_row_format("doc", "Sheet 1", "Table 1", 1)
        assert "nothing" in result.lower()

    def test_propagates_numbers_error_on_apply(self):
        responses = [_make_completed(stdout="2"),
                     _make_completed(stderr="err", returncode=1)]
        with patch("numbridge.numbers_bridge.subprocess.run", side_effect=responses):
            with pytest.raises(NumbersError):
                set_row_format("doc", "Sheet 1", "Table 1", 1, alignment="left")


# ---------------------------------------------------------------------------
# set_column_format
# ---------------------------------------------------------------------------

class TestSetColumnFormat:
    def test_raises_for_zero_column(self):
        with pytest.raises(ValueError, match="column"):
            set_column_format("doc", "Sheet 1", "Table 1", 0, alignment="left")

    def test_alignment_script_uses_cell_of_row_ref(self):
        responses = [_make_completed(stdout="3"), _make_completed()]
        with patch("numbridge.numbers_bridge.subprocess.run",
                   side_effect=responses) as mock:
            set_column_format("doc", "Sheet 1", "Table 1", 2, alignment="right")
            apply_script = mock.call_args[0][0][2]
        assert "cell 2 of row 1" in apply_script
        assert "cell 2 of row 3" in apply_script

    def test_nothing_to_format_returns_early(self):
        with patch("numbridge.numbers_bridge.subprocess.run") as mock:
            result = set_column_format("doc", "Sheet 1", "Table 1", 1)
        assert "nothing" in result.lower()

    def test_propagates_numbers_error(self):
        responses = [_make_completed(stdout="2"),
                     _make_completed(stderr="err", returncode=1)]
        with patch("numbridge.numbers_bridge.subprocess.run", side_effect=responses):
            with pytest.raises(NumbersError):
                set_column_format("doc", "Sheet 1", "Table 1", 1, font_size=12.0)


# ---------------------------------------------------------------------------
# resize_table
# ---------------------------------------------------------------------------

class TestResizeTable:
    def test_returns_confirmation_string(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()):
            result = resize_table("doc", "Sheet 1", "Table 1", 30, 28)
        assert "Table 1" in result
        assert "30" in result
        assert "28" in result

    def test_raises_for_zero_rows(self):
        with pytest.raises(ValueError, match="num_rows"):
            resize_table("doc", "Sheet 1", "Table 1", 0, 10)

    def test_raises_for_negative_rows(self):
        with pytest.raises(ValueError, match="num_rows"):
            resize_table("doc", "Sheet 1", "Table 1", -1, 10)

    def test_raises_for_zero_columns(self):
        with pytest.raises(ValueError, match="num_columns"):
            resize_table("doc", "Sheet 1", "Table 1", 10, 0)

    def test_raises_for_negative_columns(self):
        with pytest.raises(ValueError, match="num_columns"):
            resize_table("doc", "Sheet 1", "Table 1", 10, -5)

    def test_script_sets_row_and_column_count(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            resize_table("doc", "Sheet 1", "Table 1", 5, 10)
            script = mock.call_args[0][0][2]
        assert "set row count to 5" in script
        assert "set column count to 10" in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="Numbers not running", returncode=1)):
            with pytest.raises(NumbersError):
                resize_table("doc", "Sheet 1", "Table 1", 10, 10)


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


# ---------------------------------------------------------------------------
# _color_to_as / _parse_color — pure helpers
# ---------------------------------------------------------------------------

class TestColorToAs:
    def test_black(self):
        assert _color_to_as([0, 0, 0]) == "{0, 0, 0}"

    def test_white(self):
        assert _color_to_as([255, 255, 255]) == "{65535, 65535, 65535}"

    def test_red(self):
        result = _color_to_as([255, 0, 0])
        assert result == "{65535, 0, 0}"

    def test_clamps_above_255(self):
        result = _color_to_as([300, 0, 0])
        assert result == "{65535, 0, 0}"

    def test_clamps_below_zero(self):
        result = _color_to_as([-10, 0, 0])
        assert result == "{0, 0, 0}"


class TestParseColor:
    def test_empty_string_returns_none(self):
        assert _parse_color("") is None

    def test_none_string_returns_none(self):
        assert _parse_color("none") is None

    def test_missing_value_returns_none(self):
        assert _parse_color("missing value") is None

    def test_black_as65535_range(self):
        assert _parse_color("0,0,0") == [0, 0, 0]

    def test_white_as65535_range(self):
        result = _parse_color("65535,65535,65535")
        assert result == [255, 255, 255]

    def test_red_channel(self):
        result = _parse_color("65535,0,0")
        assert result == [255, 0, 0]

    def test_wrong_field_count_returns_none(self):
        assert _parse_color("255,0") is None

    def test_non_numeric_returns_none(self):
        assert _parse_color("a,b,c") is None


# ---------------------------------------------------------------------------
# get_cell_formula
# ---------------------------------------------------------------------------

class TestGetCellFormula:
    def test_returns_formula_string(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="=SUM(A1:A5)")):
            result = get_cell_formula("doc", "Sheet 1", "Table 1", 6, 1)
        assert result == "=SUM(A1:A5)"

    def test_returns_none_for_no_formula(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="")):
            result = get_cell_formula("doc", "Sheet 1", "Table 1", 1, 1)
        assert result is None

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                get_cell_formula("doc", "Sheet 1", "Table 1", 1, 1)


# ---------------------------------------------------------------------------
# rename_table
# ---------------------------------------------------------------------------

class TestRenameTable:
    def test_returns_success_message(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="OK")):
            result = rename_table("doc", "Sheet 1", "Old", "New")
        assert "Old" in result and "New" in result

    def test_noop_when_names_identical(self):
        with patch("numbridge.numbers_bridge.subprocess.run") as mock:
            result = rename_table("doc", "Sheet 1", "Same", "Same")
            mock.assert_not_called()
        assert "already has that name" in result

    def test_raises_value_error_when_new_name_taken(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="NEW_EXISTS")):
            with pytest.raises(ValueError, match="already exists"):
                rename_table("doc", "Sheet 1", "Old", "Taken")

    def test_raises_value_error_when_old_name_not_found(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="NOT_FOUND")):
            with pytest.raises(ValueError, match="not found"):
                rename_table("doc", "Sheet 1", "Ghost", "New")

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                rename_table("doc", "Sheet 1", "Old", "New")


# ---------------------------------------------------------------------------
# get_table_info
# ---------------------------------------------------------------------------

class TestGetTableInfo:
    def test_returns_expected_dict(self):
        payload = "Table 1||10||5||1||0||0"
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout=payload)):
            result = get_table_info("doc", "Sheet 1", "Table 1")
        assert result["name"] == "Table 1"
        assert result["row_count"] == 10
        assert result["column_count"] == 5
        assert result["header_row_count"] == 1
        assert result["header_column_count"] == 0
        assert result["footer_row_count"] == 0

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                get_table_info("doc", "Sheet 1", "Table 1")


# ---------------------------------------------------------------------------
# set_table_headers
# ---------------------------------------------------------------------------

class TestSetTableHeaders:
    def test_nothing_to_change_returns_early(self):
        with patch("numbridge.numbers_bridge.subprocess.run") as mock:
            result = set_table_headers("doc", "Sheet 1", "Table 1")
            mock.assert_not_called()
        assert "nothing" in result.lower()

    def test_sets_header_rows(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            result = set_table_headers("doc", "Sheet 1", "Table 1", header_rows=1)
            script = mock.call_args[0][0][2]
        assert "header row count" in script
        assert "1" in result

    def test_sets_footer_rows(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            set_table_headers("doc", "Sheet 1", "Table 1", footer_rows=2)
            script = mock.call_args[0][0][2]
        assert "footer row count" in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                set_table_headers("doc", "Sheet 1", "Table 1", header_rows=1)


# ---------------------------------------------------------------------------
# get_table_layout / set_table_layout
# ---------------------------------------------------------------------------

class TestGetTableLayout:
    def test_returns_expected_dict(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stdout="10.0||20.0||300.0||200.0")):
            result = get_table_layout("doc", "Sheet 1", "Table 1")
        assert result == {"x": 10.0, "y": 20.0, "width": 300.0, "height": 200.0}

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                get_table_layout("doc", "Sheet 1", "Table 1")


class TestSetTableLayout:
    def test_nothing_to_change_returns_early(self):
        with patch("numbridge.numbers_bridge.subprocess.run") as mock:
            result = set_table_layout("doc", "Sheet 1", "Table 1")
            mock.assert_not_called()
        assert "nothing" in result.lower()

    def test_sets_width_and_height(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            set_table_layout("doc", "Sheet 1", "Table 1", width=400.0, height=300.0)
            script = mock.call_args[0][0][2]
        assert "set width to 400.0" in script
        assert "set height to 300.0" in script

    def test_position_requires_both_coords(self):
        # Supplying only x triggers a read of current layout first
        responses = [
            _make_completed(stdout="5.0||10.0||300.0||200.0"),  # get_table_layout
            _make_completed(),                                   # set_table_layout
        ]
        with patch("numbridge.numbers_bridge.subprocess.run", side_effect=responses) as mock:
            set_table_layout("doc", "Sheet 1", "Table 1", x=50.0)
        assert mock.call_count == 2

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                set_table_layout("doc", "Sheet 1", "Table 1", width=100.0)


# ---------------------------------------------------------------------------
# set_table_locked
# ---------------------------------------------------------------------------

class TestSetTableLocked:
    def test_locks_table(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            result = set_table_locked("doc", "Sheet 1", "Table 1", True)
            script = mock.call_args[0][0][2]
        assert "set locked to true" in script
        assert "locked" in result

    def test_unlocks_table(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            result = set_table_locked("doc", "Sheet 1", "Table 1", False)
            script = mock.call_args[0][0][2]
        assert "set locked to false" in script
        assert "unlocked" in result

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                set_table_locked("doc", "Sheet 1", "Table 1", True)


# ---------------------------------------------------------------------------
# insert_row / insert_column / remove_row / remove_column
# ---------------------------------------------------------------------------

class TestInsertRow:
    def test_raises_for_zero_row(self):
        with pytest.raises(ValueError, match="before_row"):
            insert_row("doc", "Sheet 1", "Table 1", 0)

    def test_script_uses_add_row_above(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            insert_row("doc", "Sheet 1", "Table 1", 3)
            script = mock.call_args[0][0][2]
        assert "add row above row 3" in script

    def test_returns_confirmation(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()):
            result = insert_row("doc", "Sheet 1", "Table 1", 2)
        assert "2" in result

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                insert_row("doc", "Sheet 1", "Table 1", 1)


class TestInsertColumn:
    def test_raises_for_zero_column(self):
        with pytest.raises(ValueError, match="before_column"):
            insert_column("doc", "Sheet 1", "Table 1", 0)

    def test_script_uses_add_column_before(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            insert_column("doc", "Sheet 1", "Table 1", 2)
            script = mock.call_args[0][0][2]
        assert "add column before column 2" in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                insert_column("doc", "Sheet 1", "Table 1", 1)


class TestRemoveRow:
    def test_raises_for_zero_row(self):
        with pytest.raises(ValueError, match="row"):
            remove_row("doc", "Sheet 1", "Table 1", 0)

    def test_script_uses_remove_row(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            remove_row("doc", "Sheet 1", "Table 1", 4)
            script = mock.call_args[0][0][2]
        assert "remove row 4" in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                remove_row("doc", "Sheet 1", "Table 1", 1)


class TestRemoveColumn:
    def test_raises_for_zero_column(self):
        with pytest.raises(ValueError, match="column"):
            remove_column("doc", "Sheet 1", "Table 1", 0)

    def test_script_uses_remove_column(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            remove_column("doc", "Sheet 1", "Table 1", 3)
            script = mock.call_args[0][0][2]
        assert "remove column 3" in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                remove_column("doc", "Sheet 1", "Table 1", 1)


# ---------------------------------------------------------------------------
# merge_cells / unmerge_cells / clear_range / transpose_range
# ---------------------------------------------------------------------------

class TestMergeCells:
    def test_script_contains_merge_range(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            merge_cells("doc", "Sheet 1", "Table 1", 1, 1, 2, 3)
            script = mock.call_args[0][0][2]
        assert 'merge range "A1:C2"' in script

    def test_returns_confirmation(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()):
            result = merge_cells("doc", "Sheet 1", "Table 1", 1, 1, 1, 2)
        assert "A1:B1" in result

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                merge_cells("doc", "Sheet 1", "Table 1", 1, 1, 2, 2)


class TestUnmergeCells:
    def test_script_contains_unmerge_range(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            unmerge_cells("doc", "Sheet 1", "Table 1", 1, 1, 2, 2)
            script = mock.call_args[0][0][2]
        assert 'unmerge range "A1:B2"' in script

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                unmerge_cells("doc", "Sheet 1", "Table 1", 1, 1, 2, 2)


class TestClearRange:
    def test_script_contains_clear_range(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            clear_range("doc", "Sheet 1", "Table 1", 1, 1, 3, 4)
            script = mock.call_args[0][0][2]
        assert 'clear range "A1:D3"' in script

    def test_returns_confirmation(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()):
            result = clear_range("doc", "Sheet 1", "Table 1", 2, 2, 4, 5)
        assert "cleared" in result

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                clear_range("doc", "Sheet 1", "Table 1", 1, 1, 2, 2)


class TestTransposeTable:
    def test_script_contains_transpose_table(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()) as mock:
            transpose_table("doc", "Sheet 1", "Table 1")
            script = mock.call_args[0][0][2]
        assert 'transpose table "Table 1"' in script

    def test_returns_confirmation(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed()):
            result = transpose_table("doc", "Sheet 1", "Table 1")
        assert "transposed" in result

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.subprocess.run",
                   return_value=_make_completed(stderr="err", returncode=1)):
            with pytest.raises(NumbersError):
                transpose_table("doc", "Sheet 1", "Table 1")


# ---------------------------------------------------------------------------
# export_document
# ---------------------------------------------------------------------------

class TestExportDocument:
    def test_raises_for_invalid_format(self):
        with pytest.raises(ValueError, match="format"):
            export_document("doc", "/tmp/out.txt", "txt")

    def test_raises_when_parent_dir_missing(self):
        with pytest.raises(ValueError, match="directory"):
            export_document("doc", "/nonexistent/dir/out.numbers", "numbers")

    def test_script_uses_export_command(self):
        with patch("numbridge.numbers_bridge.os.path.exists", return_value=True):
            with patch("numbridge.numbers_bridge.subprocess.run",
                       return_value=_make_completed()) as mock:
                export_document("My Doc", "/tmp/out.xlsx", "xlsx")
                script = mock.call_args[0][0][2]
        assert "export to POSIX file" in script
        assert "Microsoft Excel" in script

    def test_numbers_format_uses_correct_constant(self):
        with patch("numbridge.numbers_bridge.os.path.exists", return_value=True):
            with patch("numbridge.numbers_bridge.subprocess.run",
                       return_value=_make_completed()) as mock:
                export_document("My Doc", "/tmp/out.numbers", "numbers")
                script = mock.call_args[0][0][2]
        assert "Numbers 09" in script

    def test_returns_confirmation(self):
        with patch("numbridge.numbers_bridge.os.path.exists", return_value=True):
            with patch("numbridge.numbers_bridge.subprocess.run",
                       return_value=_make_completed()):
                result = export_document("My Doc", "/tmp/out.pdf", "pdf")
        assert "My Doc" in result and "pdf" in result

    def test_propagates_numbers_error(self):
        with patch("numbridge.numbers_bridge.os.path.exists", return_value=True):
            with patch("numbridge.numbers_bridge.subprocess.run",
                       return_value=_make_completed(stderr="err", returncode=1)):
                with pytest.raises(NumbersError):
                    export_document("My Doc", "/tmp/out.xlsx", "xlsx")
