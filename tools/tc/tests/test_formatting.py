"""Tests for formatting utilities (json_output, table_output)."""

import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from tc.formatting.json_output import output_json, output_error_json, _default_serializer
from tc.formatting.table_output import output_table, _output_plain_table


class TestDefaultSerializer:
    """Tests for _default_serializer fallback."""

    def test_object_with_keys(self):
        """Objects with .keys() method should be converted to dict."""
        import sqlite3
        # Simulate sqlite3.Row-like object
        class FakeRow:
            def keys(self):
                return ["a", "b"]
            def __getitem__(self, key):
                return {"a": 1, "b": 2}[key]
            def __iter__(self):
                return iter(["a", "b"])
        row = FakeRow()
        result = _default_serializer(row)
        assert isinstance(result, dict)

    def test_non_serializable_fallback(self):
        """Non-serializable objects without .keys() should be stringified."""
        result = _default_serializer(object())
        assert isinstance(result, str)

    def test_datetime_fallback(self):
        from datetime import datetime
        dt = datetime(2025, 1, 1, 12, 0)
        result = _default_serializer(dt)
        assert "2025" in result


class TestOutputJson:
    """Tests for output_json."""

    def test_dict_output(self, capsys):
        output_json({"key": "value"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["key"] == "value"

    def test_list_output(self, capsys):
        output_json([1, 2, 3])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == [1, 2, 3]

    def test_none_output(self, capsys):
        output_json(None)
        captured = capsys.readouterr()
        assert json.loads(captured.out) is None

    def test_unicode_output(self, capsys):
        output_json({"emoji": "hello"})
        captured = capsys.readouterr()
        assert "hello" in captured.out


class TestOutputErrorJson:
    """Tests for output_error_json."""

    def test_error_to_stderr(self, capsys):
        output_error_json("bad thing happened", 2)
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["error"] == "bad thing happened"
        assert data["code"] == 2

    def test_error_format(self, capsys):
        output_error_json("test error", 5)
        captured = capsys.readouterr()
        assert "test error" in captured.err


class TestOutputTable:
    """Tests for output_table."""

    def test_empty_rows_no_title(self, capsys):
        output_table(["a", "b"], [])
        captured = capsys.readouterr()
        assert "no results" in captured.out.lower()

    def test_empty_rows_with_title(self, capsys):
        output_table(["a", "b"], [], title="My Table")
        captured = capsys.readouterr()
        assert "My Table" in captured.out
        assert "no results" in captured.out.lower()

    def test_normalizes_row_objects(self, capsys):
        """Rows with .keys() method should be normalized to dicts."""
        class FakeRow:
            def keys(self):
                return ["a"]
            def __getitem__(self, key):
                return 1
            def __iter__(self):
                return iter(["a"])
        output_table(["a"], [FakeRow()])
        captured = capsys.readouterr()
        assert "1" in captured.out


class TestPlainTable:
    """Tests for _output_plain_table fallback."""

    def test_plain_with_title(self, capsys):
        _output_plain_table(["col1", "col2"], [{"col1": "a", "col2": "b"}], title="Plain")
        captured = capsys.readouterr()
        assert "=== Plain ===" in captured.out
        assert "col1" in captured.out
        assert "a" in captured.out

    def test_plain_without_title(self, capsys):
        _output_plain_table(["x"], [{"x": "val"}], title=None)
        captured = capsys.readouterr()
        assert "===" not in captured.out
        assert "x" in captured.out
        assert "val" in captured.out

    def test_plain_multiple_rows(self, capsys):
        rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
        _output_plain_table(["a", "b"], rows, title=None)
        captured = capsys.readouterr()
        assert "1" in captured.out
        assert "3" in captured.out

    def test_plain_missing_key(self, capsys):
        _output_plain_table(["a", "b"], [{"a": "1"}], title=None)
        captured = capsys.readouterr()
        assert "1" in captured.out
