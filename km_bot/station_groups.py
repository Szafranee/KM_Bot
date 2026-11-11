"""Stations that are one place for a passenger although the timetable keeps them apart.

* Warszawa Śródmieście, Ochota, Zachodnia and Aleje Jerozolimskie each have a WKD station next to the KM/SKM
  one (a few minutes on foot). A board or a route to "Warszawa Ochota" should therefore include the WKD trains,
  so Aleje Jerozolimskie → Zachodnia lists WKD, SKM and KM, as other timetable apps do.
* "Warszawa Zachodnia" covers all its platforms: the main ones, Peron 9 and the WKD station. Peron 9 is a
  platform group of its own (S4, S40, R80 and R90 stop there), so it is *also* a station you can pick to see
  only its trains; its stops are marked 🔶 on the merged board.

Ids are the stable PKP PLK station ids and the ``WKD_`` ids of the WKD feed. Members missing from the imported
timetable are ignored.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StationGroups:
    groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Primary station id -> all ids shown together with it (the primary included)."""
    alone: frozenset[str] = frozenset()
    """Members that can still be picked on their own (their own board / route end)."""
    markers: dict[str, str] = field(default_factory=dict)
    """Station id -> label that replaces "peron" on a merged board, e.g. ``"🔶 Peron 9"``."""
    filters: dict[str, tuple[str, str]] = field(default_factory=dict)
    """Station id -> (other station id, button label) to switch between "everything" and "only this part"."""

    def members(self, station_id: str, known: Collection[str] | None = None) -> list[str]:
        """The station itself plus everything shown with it, restricted to ids present in the timetable."""
        ids = list(self.groups.get(station_id, (station_id,)))
        return [i for i in ids if known is None or i in known] or [station_id]

    def hidden(self) -> frozenset[str]:
        """Members that appear only through their primary station (not in search results or nearby lists)."""
        members = {m for ids in self.groups.values() for m in ids}
        return frozenset(members - set(self.groups) - self.alone)

    def extras(self, station_id: str, known: Collection[str] | None = None) -> list[str]:
        """Members shown together with ``station_id`` besides itself."""
        return [m for m in self.members(station_id, known) if m != station_id]


DEFAULT_GROUPS = StationGroups(
    groups={
        "33571": ("33571", "WKD_wsrod"),  # Warszawa Śródmieście
        "33498": ("33498", "WKD_wocho"),  # Warszawa Ochota
        "33506": ("33506", "34868", "WKD_wzach"),  # Warszawa Zachodnia (+ Peron 9 + WKD)
        "33456": ("33456", "WKD_walje"),  # Warszawa Aleje Jerozolimskie
    },
    alone=frozenset({"34868"}),
    markers={"34868": "🔶 Peron 9"},
    filters={
        "33506": ("34868", "🔶 Tylko peron 9"),
        "34868": ("33506", "🚉 Cała Zachodnia"),
    },
)

NO_GROUPS = StationGroups()
