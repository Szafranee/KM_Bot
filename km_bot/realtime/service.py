"""Realtime facade: asks providers in order (PKP PLK first when configured, then mkuran.pl)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from km_bot.config import Settings
from km_bot.realtime.base import RealtimeProvider, TripKey, TripRequest, TripStatus
from km_bot.realtime.mkuran import MkuranProvider
from km_bot.realtime.plk import PlkProvider
from km_bot.storage import Storage

log = logging.getLogger(__name__)

SOURCE_LABELS = {"plk": "PKP PLK", "mkuran": "PKP PLK via mkuran.pl"}


@dataclass
class RealtimeResult:
    statuses: dict[TripKey, TripStatus] = field(default_factory=dict)
    source: str | None = None
    error: bool = False

    def get(self, key: TripKey) -> TripStatus | None:
        return self.statuses.get(key)

    @property
    def source_label(self) -> str | None:
        return SOURCE_LABELS.get(self.source or "", self.source)


class RealtimeService:
    def __init__(self, providers: list[RealtimeProvider]):
        self.providers = providers

    @classmethod
    def from_settings(cls, settings: Settings, storage: Storage) -> RealtimeService:
        providers: list[RealtimeProvider] = []
        if settings.plk_api_key:
            providers.append(PlkProvider(storage, settings.plk_api_key))
        providers.append(MkuranProvider(storage))
        return cls(providers)

    def statuses(self, requests: list[TripRequest]) -> RealtimeResult:
        if not requests:
            return RealtimeResult()
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
