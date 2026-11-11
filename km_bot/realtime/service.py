"""Realtime facade: PKP PLK first when configured, then mkuran.pl for KM/SKM; WKD has its own provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from km_bot.config import Settings
from km_bot.realtime.base import RealtimeProvider, TripKey, TripRequest, TripStatus
from km_bot.realtime.mkuran import MkuranProvider
from km_bot.realtime.plk import PlkProvider
from km_bot.realtime.wkd import WkdProvider
from km_bot.storage import Storage
from km_bot.timetable.gtfs_import import WKD_PREFIX

log = logging.getLogger(__name__)

SOURCE_LABELS = {"plk": "PKP PLK", "mkuran": "PKP PLK via mkuran.pl", "wkd": "WKD"}


@dataclass
class RealtimeResult:
    statuses: dict[TripKey, TripStatus] = field(default_factory=dict)
    source: str | None = None
    error: bool = False
    extra_sources: tuple[str, ...] = ()

    def get(self, key: TripKey) -> TripStatus | None:
        return self.statuses.get(key)

    @property
    def source_label(self) -> str | None:
        names = [name for name in (self.source, *self.extra_sources) if name]
        return ", ".join(SOURCE_LABELS.get(name, name) for name in names) or None


class RealtimeService:
    def __init__(self, providers: list[RealtimeProvider], wkd: RealtimeProvider | None = None):
        self.providers = providers
        self.wkd = wkd

    @classmethod
    def from_settings(cls, settings: Settings, storage: Storage) -> RealtimeService:
        providers: list[RealtimeProvider] = []
        if settings.plk_api_key:
            providers.append(PlkProvider(storage, settings.plk_api_key))
        providers.append(MkuranProvider(storage))
        return cls(providers, WkdProvider(storage))

    def statuses(self, requests: list[TripRequest]) -> RealtimeResult:
        if not requests:
            return RealtimeResult()
        wkd_requests = [r for r in requests if r.trip_id.startswith(WKD_PREFIX)]
        pkp_requests = [r for r in requests if not r.trip_id.startswith(WKD_PREFIX)]
        result = self._pkp(pkp_requests) if pkp_requests else RealtimeResult()
        if wkd_requests and self.wkd is not None:
            try:
                statuses = self.wkd.statuses(wkd_requests)
            except Exception:
                log.exception("Realtime provider %s failed", self.wkd.name)
                result.error = True
            else:
                if statuses:
                    result.statuses.update(statuses)
                    if result.source is None:
                        result.source = self.wkd.name
                    else:
                        result.extra_sources += (self.wkd.name,)
        return result

    def _pkp(self, requests: list[TripRequest]) -> RealtimeResult:
        failed = False
        for provider in self.providers:
            try:
                statuses = provider.statuses(requests)
            except Exception:
                log.exception("Realtime provider %s failed", provider.name)
                failed = True
                continue
            if statuses:
                return RealtimeResult(statuses, provider.name)
        return RealtimeResult(error=failed)
