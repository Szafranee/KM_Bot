"""Shared service objects used by the bot handlers and CLI jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from km_bot.config import Settings
from km_bot.realtime.service import RealtimeService
from km_bot.rolling_stock.importer import expand_train_number
from km_bot.rolling_stock.repository import RollingStockRepository, StockEntry
from km_bot.storage import Storage
from km_bot.timetable.queries import TimetableRepository, TripInfo


@dataclass
class Services:
    settings: Settings
    timetable: TimetableRepository
    rolling_stock: RollingStockRepository
    storage: Storage
    realtime: RealtimeService

    @classmethod
    def from_settings(cls, settings: Settings) -> Services:
        storage = Storage(settings.app_db)
        return cls(
            settings=settings,
            timetable=TimetableRepository(settings.timetable_db),
            rolling_stock=RollingStockRepository(settings.rolling_stock_db),
            storage=storage,
            realtime=RealtimeService.from_settings(settings, storage),
        )

    def stock_for_trip(self, trip: TripInfo, service_date: date) -> list[StockEntry]:
        """Rolling stock of a KM trip from the PDF lists (SKM trains are not covered by them)."""
        if trip.agency != "KM" or trip.is_bus:
            return []
        departure = None
        if trip.first_departure is not None:
            hours, rest = divmod(trip.first_departure, 3600)
            departure = f"{hours % 24:02d}:{rest // 60:02d}"
        for number in expand_train_number(trip.number):
            entries = self.rolling_stock.lookup(number, service_date, departure)
            if entries:
                return entries
        return []

    def image_url(self, image: str | None) -> str | None:
        base = self.settings.image_base_url
        return f"{base}/{image}" if base and image else None
