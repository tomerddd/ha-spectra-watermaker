"""Persistent storage helpers for Spectra Watermaker."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_HISTORY_LIMIT, DOMAIN
from .models import RunRecord

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY_DATA = f"{DOMAIN}_data"
STORAGE_KEY_HISTORY = f"{DOMAIN}_history"


class SpectraStorage:
    """Manages persistent data for the Spectra Watermaker integration.

    Stores:
    - Prefilter last changed timestamp
    - Prefilter hours since change
    - Last flush timestamp
    - Total liters produced
    - Total production hours
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{STORAGE_KEY_DATA}_{entry_id}"
        )
        self._data: dict[str, Any] = {}

    async def async_load(self) -> None:
        """Load persisted data."""
        stored = await self._store.async_load()
        if stored:
            self._data = stored
        _LOGGER.debug("Loaded storage data: %s", self._data)

    async def async_save(self) -> None:
        """Save data to persistent storage."""
        await self._store.async_save(self._data)

    @property
    def prefilter_last_changed(self) -> str | None:
        """ISO timestamp of last prefilter change."""
        return self._data.get("prefilter_last_changed")

    @prefilter_last_changed.setter
    def prefilter_last_changed(self, value: str | None) -> None:
        self._data["prefilter_last_changed"] = value

    @property
    def prefilter_hours(self) -> float:
        """Production hours since last prefilter change."""
        return self._data.get("prefilter_hours", 0.0)

    @prefilter_hours.setter
    def prefilter_hours(self, value: float) -> None:
        self._data["prefilter_hours"] = value

    @property
    def last_flush(self) -> str | None:
        """ISO timestamp of last flush completion."""
        return self._data.get("last_flush")

    @last_flush.setter
    def last_flush(self, value: str | None) -> None:
        self._data["last_flush"] = value

    @property
    def total_liters(self) -> float:
        """Total liters produced (only while filling tank)."""
        return self._data.get("total_liters", 0.0)

    @total_liters.setter
    def total_liters(self, value: float) -> None:
        self._data["total_liters"] = value

    @property
    def total_hours(self) -> float:
        """Total production hours."""
        return self._data.get("total_hours", 0.0)

    @total_hours.setter
    def total_hours(self, value: float) -> None:
        self._data["total_hours"] = value

    @property
    def run_duration(self) -> float | None:
        """Persisted run duration in hours (None means use default)."""
        return self._data.get("run_duration")

    @run_duration.setter
    def run_duration(self, value: float | None) -> None:
        self._data["run_duration"] = value

    @property
    def tank_full_threshold(self) -> float | None:
        """Persisted tank full auto-stop threshold percentage (None means use config default)."""
        return self._data.get("tank_full_threshold")

    @tank_full_threshold.setter
    def tank_full_threshold(self, value: float | None) -> None:
        self._data["tank_full_threshold"] = value

    def reset_prefilter(self) -> None:
        """Reset prefilter tracking to now."""
        self.prefilter_last_changed = datetime.now(timezone.utc).isoformat()
        self.prefilter_hours = 0.0


class SpectraHistoryStorage:
    """Manages run history for the Spectra Watermaker integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        max_records: int = DEFAULT_HISTORY_LIMIT,
    ) -> None:
        self._store = Store[dict[str, Any]](
            hass, STORAGE_VERSION, f"{STORAGE_KEY_HISTORY}_{entry_id}"
        )
        self._max_records = max_records
        self._runs: list[RunRecord] = []

    async def async_load(self) -> None:
        """Load run history from storage."""
        stored = await self._store.async_load()
        if stored and "runs" in stored:
            self._runs = [RunRecord.from_dict(r) for r in stored["runs"]]
        _LOGGER.debug("Loaded %d run history records", len(self._runs))

    async def async_save(self) -> None:
        """Save run history to storage."""
        await self._store.async_save(
            {"runs": [r.to_dict() for r in self._runs]}
        )

    @property
    def runs(self) -> list[RunRecord]:
        """All stored run records, newest first."""
        return self._runs

    @property
    def last_run(self) -> RunRecord | None:
        """Most recent run record."""
        return self._runs[0] if self._runs else None

    def add_run(self, record: RunRecord) -> None:
        """Add a run record. Trims to max_records."""
        self._runs.insert(0, record)
        self._runs = self._runs[: self._max_records]

    def get_history(self, limit: int = 10) -> list[dict]:
        """Get last N runs as dicts for service responses."""
        return [r.to_dict() for r in self._runs[:limit]]
