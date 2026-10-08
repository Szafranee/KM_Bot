"""Station search tuned for Warsaw commuters.

Users type short or sloppy names ("Śródmieście", "zach", "wwa centralna", "koło"). Matching works on
normalized tokens (no diacritics, lowercase) with aliases for common colloquial names. Ranking prefers:
exact name > Warsaw station whose suffix matches ("Koło" -> "Warszawa Koło") > token prefixes > substring >
fuzzy match; ties go to Warsaw stations and then to busier stations. All stations come from the KM/SKM
timetable, so the Mazovian network is naturally covered first.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from km_bot.timetable.queries import Station

WARSAW = "warszawa"

# Colloquial name -> official station name.
ALIASES: dict[str, str] = {
    "lotnisko": "Warszawa Lotnisko Chopina",
    "lotnisko chopina": "Warszawa Lotnisko Chopina",
    "okecie": "Warszawa Lotnisko Chopina",
    "chopin": "Warszawa Lotnisko Chopina",
    "centralny": "Warszawa Centralna",
    "dworzec centralny": "Warszawa Centralna",
    "centrum": "Warszawa Śródmieście",
    "modlin lotnisko": "Lotnisko Modlin",
    "lotnisko modlin": "Lotnisko Modlin",
    "stadion narodowy": "Warszawa Stadion",
    "zoo": "Warszawa Zoo",
}

MAIN_STATION_TOKENS = {"glowny", "glowna", "centralna"}

# Token abbreviations expanded before matching.
TOKEN_ALIASES: dict[str, str] = {
    "wwa": WARSAW,
    "w-wa": WARSAW,
    "wawa": WARSAW,
    "waw": WARSAW,
    "warsaw": WARSAW,
    "pld": "poludniowa",
    "pd": "poludniowa",
    "pn": "polnocna",
    "pln": "polnocna",
    "gl": "glowna",
    "maz": "mazowiecki",
    "sw": "swiety",
}


def normalize(text: str) -> str:
    text = text.lower().replace("ł", "l")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    return [TOKEN_ALIASES.get(token, token) for token in normalize(text).split()]


@dataclass(frozen=True)
class Match:
    station: Station
    score: float


def _prefix_match(query: list[str], name: list[str]) -> bool:
    """Every query token is a prefix of a distinct name token, in order."""
    position = 0
    for token in query:
        while position < len(name) and not name[position].startswith(token):
            position += 1
        if position == len(name):
            return False
        position += 1
    return True


def _score(query: str, query_tokens: list[str], station: Station) -> float:
    name = normalize(station.name)
    name_tokens = tokens(station.name)
    joined = " ".join(query_tokens)
    is_warsaw = name_tokens[:1] == [WARSAW]
    suffix = " ".join(name_tokens[1:]) if is_warsaw else None

    if joined == " ".join(name_tokens) or query == name:
        return 100
    if suffix is not None and joined == suffix:
        return 95
    if _prefix_match(query_tokens, name_tokens):
        # "Grodzisk" -> "Grodzisk Mazowiecki" beats "Grodzisk Mazowiecki Radońska"; first-token hits rank higher.
        starts = name_tokens[0].startswith(query_tokens[0]) or (
            is_warsaw and len(name_tokens) > 1 and name_tokens[1].startswith(query_tokens[0])
        )
        exact = sum(token in name_tokens for token in query_tokens) / len(query_tokens)
        # Main stations win over other stops of the same town ("Radom" -> "Radom Główny").
        # Not for Warsaw itself: there is no single "main" station the user could mean.
        main = (
            query_tokens != [WARSAW]
            and any(token in MAIN_STATION_TOKENS for token in name_tokens[1:])
            and not any(token in MAIN_STATION_TOKENS for token in query_tokens)
        )
        return 70 + (10 if starts else 0) + 10 * exact + (2 if main else 0)
    if joined in " ".join(name_tokens):
        return 60
    ratio = max(
        SequenceMatcher(None, joined, " ".join(name_tokens)).ratio(),
        SequenceMatcher(None, joined, suffix).ratio() if suffix else 0,
    )
    return ratio * 60 if ratio >= 0.72 else 0


def _stem(token: str) -> str:
    """Crude removal of Polish case endings: 'wschodniej' -> 'wschodni', 'otwocka' -> 'otwock'."""
    for ending in ("iej", "ego", "iego", "ej", "ie", "a", "u", "y", "i"):
        if token.endswith(ending) and len(token) - len(ending) >= 4:
            return token[: -len(ending)]
    return token


def _rank(query_norm: str, query_tokens: list[str], stations: Iterable[Station]) -> list[Match]:
    matches = []
    for station in stations:
        if is_secondary(station.name):
            continue
        score = _score(query_norm, query_tokens, station)
        if score > 0:
            matches.append(Match(station, score))
    matches.sort(
        key=lambda m: (
            -round(m.score),
            not normalize(m.station.name).startswith(WARSAW),
            -m.station.departures,
            m.station.name,
        )
    )
    return matches


def search(query: str, stations: Iterable[Station], limit: int = 5) -> list[Match]:
    query_norm = normalize(query)
    if not query_norm:
        return []
    stations = list(stations)
    alias = ALIASES.get(query_norm)
    query_tokens = tokens(alias or query)
    matches = _rank(normalize(alias) if alias else query_norm, query_tokens, stations)
    if not matches or matches[0].score < 70:
        # Declined forms ("z Wschodniej", "do Otwocka") - retry with stems and keep the better result.
        stemmed = [_stem(token) for token in query_tokens]
        if stemmed != query_tokens:
            retry = _rank(" ".join(stemmed), stemmed, stations)
            if retry and (not matches or retry[0].score > matches[0].score):
                matches = retry
    return matches[:limit]


def is_confident(matches: list[Match]) -> bool:
    """True when the best match is clearly the one the user meant."""
    if not matches:
        return False
    best = matches[0]
    if len(matches) == 1:
        return best.score >= 50
    second = matches[1]
    if (best.score >= 90 and best.score - second.score >= 2) or (best.score >= 75 and best.score - second.score >= 15):
        return True
    # "Mińsk" -> "Mińsk Mazowiecki" rather than "Mińsk Mazowiecki Anielina": the best name is a prefix of
    # every other equally good candidate.
    best_name = normalize(best.station.name)
    rivals = [m for m in matches[1:] if round(m.score) >= round(best.score) - 2]
    return best.score >= 80 and all(normalize(m.station.name).startswith(best_name + " ") for m in rivals)


def group_name(name: str) -> str:
    """'Warszawa Zachodnia (Peron 9)' -> 'Warszawa Zachodnia'."""
    return re.sub(r"\s*\(.*\)\s*$", "", name).strip()


def is_secondary(name: str) -> bool:
    return group_name(name) != name.strip()


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest(lat: float, lon: float, stations: Iterable[Station], limit: int = 3) -> list[tuple[Station, float]]:
    with_distance = [
        (s, distance_km(lat, lon, s.lat, s.lon)) for s in stations if s.lat is not None and s.lon is not None
    ]
    with_distance.sort(key=lambda item: item[1])
    return with_distance[:limit]
