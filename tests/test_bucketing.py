"""Tests for the hourly bucketing helper used by the statistics backfill."""

from __future__ import annotations

from api import Sample
from bucketing import HourlyBucket, bucket_hourly


def _h(hour: int, minute: int = 0, second: int = 0) -> int:
    """Unix timestamp for YYYY-01-01 hour:minute:second UTC (for readability)."""
    # 2026-04-24 00:00:00 UTC = 1777017600
    base = 1777017600
    return base + hour * 3600 + minute * 60 + second


def test_bucket_hourly_groups_by_hour() -> None:
    samples = [
        Sample(_h(0, 10), 10.0),
        Sample(_h(0, 30), 20.0),
        Sample(_h(0, 50), 30.0),
        Sample(_h(1, 5), 40.0),
        Sample(_h(1, 55), 60.0),
    ]
    buckets = bucket_hourly(samples)
    assert len(buckets) == 2
    assert buckets[0] == HourlyBucket(
        start_ts=_h(0), mean=20.0, minimum=10.0, maximum=30.0, count=3
    )
    assert buckets[1] == HourlyBucket(
        start_ts=_h(1), mean=50.0, minimum=40.0, maximum=60.0, count=2
    )


def test_bucket_hourly_sorted_ascending() -> None:
    # Samples intentionally out of order
    samples = [
        Sample(_h(5), 1.0),
        Sample(_h(2), 2.0),
        Sample(_h(3), 3.0),
    ]
    buckets = bucket_hourly(samples)
    assert [b.start_ts for b in buckets] == [_h(2), _h(3), _h(5)]


def test_bucket_hourly_empty() -> None:
    assert bucket_hourly([]) == []


def test_bucket_hourly_single_sample() -> None:
    samples = [Sample(_h(0, 15), 42.5)]
    buckets = bucket_hourly(samples)
    assert buckets == [HourlyBucket(start_ts=_h(0), mean=42.5, minimum=42.5, maximum=42.5, count=1)]


def test_bucket_hourly_aligns_to_hour_boundary() -> None:
    # Sample at 00:59:59 belongs to the 00:00 bucket.
    # Sample at 01:00:00 belongs to the 01:00 bucket.
    samples = [Sample(_h(0, 59, 59), 1.0), Sample(_h(1, 0, 0), 2.0)]
    buckets = bucket_hourly(samples)
    assert [b.start_ts for b in buckets] == [_h(0), _h(1)]
    assert buckets[0].count == 1
    assert buckets[1].count == 1
