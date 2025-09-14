"""Helpers for assigning time-band labels to timestamped meter readings.

This module determines which time band (e.g. peak/offpeak/shoulder) a
particular meter reading timestamp belongs to based on the canonical
tariff's ``time_bands`` definitions. It supports optional date ranges
on bands and the special ``"all"`` day to match any day of the week.

The assigner returns the ``id`` of the first matching band. If no bands
match, it returns ``"off_peak"`` by default.

Note: This function intentionally does not handle demand‐specific windows
(e.g. demand bands). Those should be accounted for in the calculation
logic where rolling windows are applied. Here we focus on mapping
timestamps to simple usage categories like ``peak``, ``offpeak`` and
``shoulder``.
"""

from datetime import datetime, date
from typing import Dict, Any


def _in_date_ranges(ts_date: date, date_ranges: list) -> bool:
    """Return True if ts_date falls within any of the provided date ranges.

    Each date range should have ``from`` and ``to`` keys formatted
    ``YYYY-MM-DD``. The check is inclusive.
    """
    for r in date_ranges:
        try:
            frm = datetime.strptime(r.get("from"), "%Y-%m-%d").date()
            to = datetime.strptime(r.get("to"), "%Y-%m-%d").date()
            if frm <= ts_date <= to:
                return True
        except Exception:
            # If parsing fails, skip that range
            continue
    return False


def assign_band(ts: datetime, canonical: Dict[str, Any]) -> str:
    """Assign a time band ID to a timestamp based on the canonical tariff.

    Parameters
    ----------
    ts : datetime
        The timestamp of a meter reading.
    canonical : dict
        The canonical tariff JSON containing ``time_bands`` definitions.

    Returns
    -------
    str
        The ``id`` of the first matching time band, or ``"off_peak"`` if
        none match.
    """
    ts_date = ts.date()
    day_abbr = ts.strftime("%a").lower()[:3]  # e.g. 'mon', 'tue'
    time_str = ts.strftime("%H:%M")
    for band in canonical.get("time_bands", []):
        # Validate date ranges if present
        date_ranges = band.get("date_ranges")
        if date_ranges:
            if not _in_date_ranges(ts_date, date_ranges):
                continue
        # Normalize days to lower-case
        days_list = [d.lower() for d in band.get("days", [])]
        # If 'all' is specified, it applies every day
        if 'all' not in days_list and day_abbr not in days_list:
            continue
        # Check time spans
        for span in band.get("times", []):
            start_time = span.get("from")
            end_time = span.get("to")
            if start_time is None or end_time is None:
                continue
            # Compare HH:MM strings lexicographically
            if start_time <= time_str < end_time:
                return band.get("id", "off_peak")
    # Default band if none matched
    return "off_peak"
