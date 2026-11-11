"""Write hourly energy values into Home Assistant long-term statistics."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .merge import merge_hourly


def _metadata(statistic_id: str, name: str) -> dict:
    meta = {
        "has_mean": False,
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": statistic_id,
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }
    try:  # Home Assistant 2025.4+ / 2025.11+
        from homeassistant.components.recorder.models import (  # noqa: PLC0415
            StatisticMeanType,
        )

        meta["mean_type"] = StatisticMeanType.NONE
        meta["unit_class"] = "energy"
    except ImportError:
        pass
    return meta


def _as_datetime(value) -> datetime:
    if isinstance(value, (int, float)):
        return dt_util.utc_from_timestamp(value)
    return dt_util.as_utc(value)


async def async_import_hourly(
    hass: HomeAssistant,
    statistic_id: str,
    name: str,
    hourly: dict[datetime, float],
) -> None:
    """Merge hourly kWh values into an external statistic.

    Each row stores the hour's energy in `state` and the running total in
    `sum`. Existing rows from the first new hour onward are rewritten so the
    running total stays consistent when older data is (re)imported.
    """
    if not hourly:
        return

    recorder = get_instance(hass)
    existing = await recorder.async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {statistic_id},
        "hour",
        None,
        {"state", "sum"},
    )

    stored = {
        _as_datetime(row["start"]): (row.get("state") or 0.0, row.get("sum") or 0.0)
        for row in existing.get(statistic_id, [])
    }
    rows = merge_hourly(stored, hourly)

    async_add_external_statistics(hass, _metadata(statistic_id, name), rows)
    # Make sure a following import reads what was just written.
    await recorder.async_block_till_done()
