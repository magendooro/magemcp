"""Tests for magemcp.utils.dates — natural language date parsing."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from magemcp.utils.dates import parse_date_expr


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# Relative expressions
# ---------------------------------------------------------------------------

class TestRelativeDates:
    def test_today(self) -> None:
        today = date.today()
        assert parse_date_expr("today") == today.isoformat()

    def test_today_case_insensitive(self) -> None:
        assert parse_date_expr("Today") == date.today().isoformat()

    def test_yesterday(self) -> None:
        yesterday = date.today() - timedelta(days=1)
        assert parse_date_expr("yesterday") == yesterday.isoformat()

    def test_this_week(self) -> None:
        monday = _monday(date.today())
        assert parse_date_expr("this week") == monday.isoformat()

    def test_this_week_underscore(self) -> None:
        monday = _monday(date.today())
        assert parse_date_expr("this_week") == monday.isoformat()

    def test_last_week(self) -> None:
        last_monday = _monday(date.today()) - timedelta(weeks=1)
        assert parse_date_expr("last week") == last_monday.isoformat()

    def test_this_month(self) -> None:
        first = date.today().replace(day=1)
        assert parse_date_expr("this month") == first.isoformat()

    def test_last_month(self) -> None:
        today = date.today()
        first_this = today.replace(day=1)
        first_last = (first_this - timedelta(days=1)).replace(day=1)
        assert parse_date_expr("last month") == first_last.isoformat()

    def test_this_year(self) -> None:
        jan1 = date.today().replace(month=1, day=1)
        assert parse_date_expr("this year") == jan1.isoformat()

    def test_ytd(self) -> None:
        jan1 = date.today().replace(month=1, day=1)
        assert parse_date_expr("ytd") == jan1.isoformat()

    def test_last_year(self) -> None:
        last_jan1 = date.today().replace(year=date.today().year - 1, month=1, day=1)
        assert parse_date_expr("last year") == last_jan1.isoformat()


# ---------------------------------------------------------------------------
# Pass-through ISO dates
# ---------------------------------------------------------------------------

class TestPassThrough:
    def test_iso_date(self) -> None:
        assert parse_date_expr("2025-03-01") == "2025-03-01"

    def test_iso_datetime(self) -> None:
        assert parse_date_expr("2025-03-01 09:00:00") == "2025-03-01 09:00:00"

    def test_iso_date_with_whitespace(self) -> None:
        assert parse_date_expr("  2025-01-15  ") == "2025-01-15"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrors:
    def test_unknown_expression(self) -> None:
        with pytest.raises(ValueError, match="Unrecognised"):
            parse_date_expr("next tuesday")

    def test_empty_string(self) -> None:
        with pytest.raises(ValueError):
            parse_date_expr("")

    def test_none_input(self) -> None:
        with pytest.raises((ValueError, AttributeError)):
            parse_date_expr(None)  # type: ignore[arg-type]
