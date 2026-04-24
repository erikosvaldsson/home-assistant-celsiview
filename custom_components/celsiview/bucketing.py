"""Hourly bucketing of Celsiview samples for Home Assistant statistics.

Celsiview devices sample on a 30 s - 5 min cadence but only upload to the
cloud a few times a day. Home Assistant's own recorder would register a
state change only when we poll; to make historical graphs reflect the
actual sample times we aggregate the raw sample stream into hourly
buckets and import them as long-term statistics.

The logic in this module is pure Python and has no Home Assistant
dependency so it can be unit-tested in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import Sample

SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class HourlyBucket:
    """Aggregated statistics for one hour of samples."""

    start_ts: int  # UTC unix seconds, aligned to a whole hour
    mean: float
    minimum: float
    maximum: float
    count: int


def bucket_hourly(samples: Iterable[Sample]) -> list[HourlyBucket]:
    """Aggregate samples into hourly buckets (min / mean / max).

    Samples are bucketed by the UTC hour containing their timestamp.
    The result is sorted ascending by ``start_ts``. Empty inputs yield
    an empty list.
    """
    buckets: dict[int, list[float]] = {}
    for sample in samples:
        hour_start = (sample.ts // SECONDS_PER_HOUR) * SECONDS_PER_HOUR
        buckets.setdefault(hour_start, []).append(sample.value)

    result: list[HourlyBucket] = []
    for hour_start in sorted(buckets):
        values = buckets[hour_start]
        result.append(
            HourlyBucket(
                start_ts=hour_start,
                mean=sum(values) / len(values),
                minimum=min(values),
                maximum=max(values),
                count=len(values),
            )
        )
    return result
