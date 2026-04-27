"""Direct-to-recorder state backfill for Celsiview samples.

This module is **opt-in and unsupported**: it bypasses Home Assistant's
public APIs and writes directly into the recorder's ``states`` /
``states_meta`` tables so historical samples appear at their on-device
timestamps in the standard History tab. The public statistics API is
hourly-only and the recorder exposes no public way to insert past states,
so the only path to sample-rate state history is through the internal
SQLAlchemy models.

Risks the caller has accepted by enabling this:

* The recorder schema is HA-internal and may change between versions.
  Column renames or new NOT-NULL columns will break us. We refuse to
  run if the recorder's ``SCHEMA_VERSION`` is below the minimum we've
  tested against, and warn loudly if it's above the tested ceiling.
* Backfilled rows have ``attributes_id = NULL``, so the History tab
  will show the row's value but not its unit / friendly_name at that
  point in time. Live rows (written by HA itself on poll) carry full
  attributes.
* Deeper backfills can balloon the recorder DB. With 5-minute samples
  that's ~105k rows per year per sensor.

The pure-Python helpers (`format_state_value`, `select_new_rows`) have
no Home Assistant dependency so the dedupe/formatting logic can be
unit-tested directly.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import Sample

_LOGGER = logging.getLogger(__name__)

# How many rows to send to the recorder in a single INSERT. Keeps the
# in-flight statement size and the SQLite IN-clause for the dedupe
# SELECT both well under the 999-parameter ceiling.
INSERT_CHUNK = 500


class StateBackfillUnsupported(RuntimeError):
    """Raised when the recorder schema or modules don't match expectations."""


@dataclass(frozen=True)
class StateRow:
    """One row to be inserted into the ``states`` table."""

    last_updated_ts: float
    state: str


def format_state_value(value: float) -> str:
    """Format a numeric sample the way HA stores sensor states.

    Home Assistant stores ``state`` as text. ``SensorEntity`` formats
    floats with up to ~6 significant digits; we mirror that so a
    backfilled row and a live row carrying the same numeric value
    compare equal as strings (avoids spurious "state changed" entries
    in the History view at the seam).
    """
    if value != value:  # NaN
        return "unknown"
    text = f"{value:.6g}"
    return text


def select_new_rows(
    samples: Iterable[Sample],
    existing_ts: set[int],
) -> list[StateRow]:
    """Pick which samples need inserting, skipping duplicates.

    Returned rows are sorted ascending by timestamp. Duplicates within
    ``samples`` itself are also collapsed — the API occasionally returns
    overlapping windows.
    """
    seen: set[int] = set()
    rows: list[StateRow] = []
    for sample in samples:
        ts = int(sample.ts)
        if ts in existing_ts or ts in seen:
            continue
        seen.add(ts)
        rows.append(StateRow(last_updated_ts=float(ts), state=format_state_value(sample.value)))
    rows.sort(key=lambda r: r.last_updated_ts)
    return rows


async def async_write_state_rows(
    hass: HomeAssistant,
    entity_id: str,
    samples: list[Sample],
) -> int:
    """Write samples to the recorder's ``states`` table.

    Returns the number of rows actually inserted after deduplication.
    Raises ``StateBackfillUnsupported`` if the recorder is missing or
    too far from the tested schema range; the caller is expected to
    disable backfill for the rest of the session in that case.

    All SQL work runs on the recorder's executor so the recorder's own
    write pipeline is not blocked by us.
    """
    if not samples:
        return 0

    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.const import SCHEMA_VERSION
        from homeassistant.components.recorder.db_schema import States, StatesMeta
        from homeassistant.components.recorder.util import session_scope
        from sqlalchemy import insert, select

        from .const import RECORDER_SCHEMA_VERSION_MIN, RECORDER_SCHEMA_VERSION_TESTED
    except ImportError as err:
        raise StateBackfillUnsupported(f"recorder imports unavailable: {err}") from err

    if SCHEMA_VERSION < RECORDER_SCHEMA_VERSION_MIN:
        raise StateBackfillUnsupported(
            f"recorder schema {SCHEMA_VERSION} is older than the minimum "
            f"this integration was tested against ({RECORDER_SCHEMA_VERSION_MIN}). "
            "Refusing to write to avoid corrupting an unfamiliar layout."
        )
    if SCHEMA_VERSION > RECORDER_SCHEMA_VERSION_TESTED:
        _LOGGER.warning(
            "Celsiview state backfill running against recorder schema %d "
            "(tested up to %d); proceed with caution",
            SCHEMA_VERSION,
            RECORDER_SCHEMA_VERSION_TESTED,
        )

    recorder = get_instance(hass)

    def _insert() -> int:
        with session_scope(hass=hass) as session:
            metadata_id = session.execute(
                select(StatesMeta.metadata_id).where(StatesMeta.entity_id == entity_id)
            ).scalar_one_or_none()
            if metadata_id is None:
                meta = StatesMeta(entity_id=entity_id)
                session.add(meta)
                session.flush()
                metadata_id = meta.metadata_id

            inserted = 0
            sample_list = list(samples)
            for chunk_start in range(0, len(sample_list), INSERT_CHUNK):
                chunk = sample_list[chunk_start : chunk_start + INSERT_CHUNK]
                ts_floats = [float(int(s.ts)) for s in chunk]
                existing_ts = {
                    int(t)
                    for t in session.execute(
                        select(States.last_updated_ts).where(
                            States.metadata_id == metadata_id,
                            States.last_updated_ts.in_(ts_floats),
                        )
                    ).scalars()
                }
                rows = select_new_rows(chunk, existing_ts)
                if not rows:
                    continue
                session.execute(
                    insert(States),
                    [
                        {
                            "metadata_id": metadata_id,
                            "state": row.state,
                            "last_updated_ts": row.last_updated_ts,
                            # NULL means "same as last_updated_ts" per recorder convention
                            "last_changed_ts": None,
                            "last_reported_ts": None,
                            "old_state_id": None,
                            "attributes_id": None,
                            "origin_idx": 0,
                            "event_id": None,
                        }
                        for row in rows
                    ],
                )
                inserted += len(rows)
            return inserted

    return await recorder.async_add_executor_job(_insert)
