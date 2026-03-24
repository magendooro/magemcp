"""Date expression parser — converts natural language to YYYY-MM-DD strings."""

from __future__ import annotations

import re
from datetime import date, timedelta


def parse_date_expr(expr: str) -> str:
    """Convert a natural language date expression or ISO date to YYYY-MM-DD.

    Supported expressions (case-insensitive):
      today            → today's date
      yesterday        → yesterday's date
      this week        → Monday of the current ISO week
      last week        → Monday of the previous ISO week
      this month       → 1st of the current month
      last month       → 1st of the previous month
      this year / ytd  → January 1st of the current year
      last year        → January 1st of the previous year
      YYYY-MM-DD       → passed through unchanged

    Args:
        expr: A date expression string.

    Returns:
        An ISO date string (YYYY-MM-DD).

    Raises:
        ValueError: If the expression is not recognised.
    """
    if not expr or not isinstance(expr, str):
        raise ValueError(f"Invalid date expression: {expr!r}")

    normalised = expr.strip().lower().replace("-", " ").replace("_", " ")
    today = date.today()

    if normalised == "today":
        return today.isoformat()

    if normalised == "yesterday":
        return (today - timedelta(days=1)).isoformat()

    if normalised in ("this week", "this week"):
        # ISO weekday: Monday=1 … Sunday=7
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    if normalised == "last week":
        monday = today - timedelta(days=today.weekday() + 7)
        return monday.isoformat()

    if normalised == "this month":
        return today.replace(day=1).isoformat()

    if normalised == "last month":
        first_this_month = today.replace(day=1)
        last_month_last_day = first_this_month - timedelta(days=1)
        return last_month_last_day.replace(day=1).isoformat()

    if normalised in ("this year", "ytd"):
        return today.replace(month=1, day=1).isoformat()

    if normalised == "last year":
        return today.replace(year=today.year - 1, month=1, day=1).isoformat()

    # Pass through ISO dates (YYYY-MM-DD) or datetime strings (YYYY-MM-DD HH:MM:SS)
    if re.match(r"^\d{4}-\d{2}-\d{2}", expr.strip()):
        return expr.strip()

    raise ValueError(
        f"Unrecognised date expression: {expr!r}. "
        "Use YYYY-MM-DD or one of: today, yesterday, this week, last week, "
        "this month, last month, this year, last year, ytd."
    )
