"""Tests for the pure-Python helpers in state_backfill.

The DB-writing path (`async_write_state_rows`) requires a live Home
Assistant + recorder, so it's out of scope for these unit tests. The
dedupe and value-formatting helpers are pure and exercised here.
"""

from __future__ import annotations

import math

from api import Sample
from state_backfill import StateRow, format_state_value, select_new_rows


def test_format_state_value_round_trips_simple_floats() -> None:
    assert format_state_value(18.72) == "18.72"
    assert format_state_value(0.0) == "0"
    assert format_state_value(-3.5) == "-3.5"


def test_format_state_value_trims_to_six_significant_figures() -> None:
    # 1234.567891 has 10 significant digits; HA stores ~6.
    text = format_state_value(1234.567891)
    assert text == "1234.57"


def test_format_state_value_handles_nan() -> None:
    assert format_state_value(float("nan")) == "unknown"


def test_select_new_rows_skips_existing_timestamps() -> None:
    samples = [
        Sample(ts=100, value=1.0),
        Sample(ts=200, value=2.0),
        Sample(ts=300, value=3.0),
    ]
    rows = select_new_rows(samples, existing_ts={200})
    assert rows == [
        StateRow(last_updated_ts=100.0, state="1"),
        StateRow(last_updated_ts=300.0, state="3"),
    ]


def test_select_new_rows_deduplicates_within_input() -> None:
    samples = [
        Sample(ts=100, value=1.0),
        Sample(ts=100, value=1.5),  # duplicate ts
        Sample(ts=200, value=2.0),
    ]
    rows = select_new_rows(samples, existing_ts=set())
    assert [r.last_updated_ts for r in rows] == [100.0, 200.0]
    # First occurrence wins
    assert rows[0].state == "1"


def test_select_new_rows_sorted_ascending() -> None:
    samples = [
        Sample(ts=300, value=3.0),
        Sample(ts=100, value=1.0),
        Sample(ts=200, value=2.0),
    ]
    rows = select_new_rows(samples, existing_ts=set())
    assert [r.last_updated_ts for r in rows] == [100.0, 200.0, 300.0]


def test_select_new_rows_empty() -> None:
    assert select_new_rows([], existing_ts=set()) == []


def test_select_new_rows_all_filtered() -> None:
    samples = [Sample(ts=100, value=1.0), Sample(ts=200, value=2.0)]
    assert select_new_rows(samples, existing_ts={100, 200}) == []


def test_state_row_uses_float_timestamp() -> None:
    rows = select_new_rows([Sample(ts=12345, value=4.2)], existing_ts=set())
    assert rows[0].last_updated_ts == 12345.0
    assert isinstance(rows[0].last_updated_ts, float)
    assert rows[0].state == "4.2"
    # Sanity: last_updated_ts should round-trip back to the original ts.
    assert math.isclose(rows[0].last_updated_ts, 12345)
