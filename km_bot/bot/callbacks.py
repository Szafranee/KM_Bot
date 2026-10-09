"""Compact ``callback_data`` encoding (Telegram limits it to 64 bytes).

Every action is ``<code>:<arg>:<arg>...``. Trip ids are shortened: ``PLK_KM_2026_114929865`` becomes
``PKM_2026_114929865`` and other ids are prefixed with ``X``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from km_bot.config import TZ

MAX_LENGTH = 64

# Action codes
DEPARTURES = "D"  # D:<station>:<offset>[:<at>]
TRIP = "T"  # T:<trip>:<yyyymmdd>:<station or ->:<back>
CONNECTIONS = "C"  # C:<from>:<to>:<offset>[:<at>]
ROUTE = "R"  # R:<route id>:<offset>
FAV_ADD = "F+"  # F+:<station>
FAV_DEL = "F-"  # F-:<station>:<view>   view: b = board, l = favourites list
ROUTE_SAVE = "R+"  # R+:<from>:<to>
ROUTE_DEL = "R-"  # R-:<route id>
WATCH = "W+"  # W+:<trip>:<yyyymmdd>:<station or ->:<back>
UNWATCH = "W-"  # W-:<watch id>:<view>    view: c = trip card, l = list of watched trains
NUMBER = "N"  # N:<number>:<yyyymmdd>
PICK = "P"  # P:<station>:<mode>        mode: d = departures, f = route from, t = route to
ROUTE_FROM_HERE = "RF"  # RF:<station>
MENU = "M"  # M:<name>
TUTORIAL = "H"  # H:<page>                  0 = table of contents
TUTORIAL_DEMO = "HX"  # HX:<demo>           sends a real example as a new message
NOOP = "_"


def encode_trip(trip_id: str) -> str:
    return "P" + trip_id[4:] if trip_id.startswith("PLK_") else "X" + trip_id


def decode_trip(value: str) -> str:
    return "PLK_" + value[1:] if value.startswith("P") else value[1:]


def encode_date(day: date) -> str:
    return day.strftime("%Y%m%d")


def decode_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def encode_at(moment: datetime | None) -> str | None:
    """Custom start time of a board ("Koło 17:30") as YYMMDDHHMM."""
    return moment.strftime("%y%m%d%H%M") if moment else None


def decode_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%y%m%d%H%M").replace(tzinfo=TZ)
    except ValueError:
        return None


def make(*parts: object) -> str:
    data = ":".join("-" if part is None else str(part) for part in parts)
    if len(data.encode()) > MAX_LENGTH:
        raise ValueError(f"callback_data too long: {data!r}")
    return data


def make_lenient(*parts: object) -> str:
    """Like ``make`` but drops trailing parts (e.g. the 'back' target) when the data would be too long."""
    parts_list = list(parts)
    while parts_list:
        data = ":".join("-" if part is None else str(part) for part in parts_list)
        if len(data.encode()) <= MAX_LENGTH:
            return data
        parts_list.pop()
    raise ValueError("callback_data too long")


@dataclass(frozen=True)
class Callback:
    action: str
    args: list[str]

    def arg(self, index: int, default: str | None = None) -> str | None:
        value = self.args[index] if index < len(self.args) else default
        return None if value == "-" else value

    def int_arg(self, index: int, default: int = 0) -> int:
        value = self.arg(index)
        try:
            return int(value) if value is not None else default
        except ValueError:
            return default


def parse(data: str | None) -> Callback:
    parts = (data or NOOP).split(":")
    return Callback(parts[0], parts[1:])


# "Back" targets embedded in trip callbacks: D<station>.<offset>[.<at>], C<from>.<to>.<offset>[.<at>],
# R<route>.<offset>.


def back_departures(station_id: str, offset: int, at: str | None = None) -> str:
    return f"D{station_id}.{offset}" + (f".{at}" if at else "")


def back_connections(from_id: str, to_id: str, offset: int, at: str | None = None) -> str:
    return f"C{from_id}.{to_id}.{offset}" + (f".{at}" if at else "")


def back_route(route_id: int, offset: int) -> str:
    return f"R{route_id}.{offset}"


def back_to_callback(back: str | None) -> str | None:
    """Turns a back target into the callback data of the view it points to."""
    if not back:
        return None
    kind, rest = back[0], back[1:].split(".")
    if kind == "D" and len(rest) in (2, 3):
        return make(DEPARTURES, *rest)
    if kind == "C" and len(rest) in (3, 4):
        return make(CONNECTIONS, *rest)
    if kind == "R" and len(rest) == 2:
        return make(ROUTE, *rest)
    return None
