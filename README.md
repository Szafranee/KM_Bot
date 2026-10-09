# 🚆 KM Bot

Telegram bot ([@kmkobot](https://t.me/kmkobot)) for passengers of **Koleje Mazowieckie** and **SKM Warszawa**.
It started as a way to check the rolling stock of a KM train by its number without digging through
KM's PDF lists, and now also shows live departures, delays and direct connections.

## Features

| | What you type / tap | What you get |
| --- | --- | --- |
| 🚉 Departures | `Śródmieście`, `Koło`, `zach`, `wwa centralna`, `lotnisko`, `Śródmieście 17:30` | Next 5 KM + SKM departures with delay, platform and rolling stock; paging ◀ ▶, refresh, details 1–5 |
| 🔢 Train number | `91450`, `91450/1`, `/pociag 51136` | Rolling stock (e.g. *2× Flirt 3*, *EU47 + 6 wagonów piętrowych*) with photo, full route with times, platforms and per-stop delays, status; previous/next day |
| 🧭 Routes | `Nowa Iwiczna > Służewiec`, `Koło - Wschodnia 17:30`, `Błonie, Pilawa, 08:01` | Direct trains only – departure, arrival, travel time, stock, delay; save ⭐ to *Moje trasy*, reverse ⇄ |
| ⭐ Favourites | ⭐ on a departure board | One-tap boards for favourite stations |
| 📍 Location | share location | 3 nearest KM/SKM stations |
| 🔔 Tracking | 🔔 on a train card | Notification when the delay changes by ≥3 min, when the train is cancelled and ~10 min before departure from your station |
| 📖 Tutorial | `/samouczek`, "❓ Pomoc" in the menu, offered after `/start` | 7-page guide with "▶ Wypróbuj" buttons that show real live examples, plus a legend of all symbols |

Station search understands Warsaw shortcuts (*Śródmieście → Warszawa Śródmieście*, *Koło → Warszawa Koło*),
abbreviations (*wwa*, *zach*, *maz*), colloquial names (*Okęcie*, *lotnisko*, *centralny*) and declined
forms (*z Wschodniej*, *do Otwocka*). Only stations served by KM or SKM are searched, so Mazovian stations
come first naturally; ambiguous queries show a short list to pick from.

## Data sources

| Data | Source | Refresh |
| --- | --- | --- |
| Timetable (stops, platforms, train numbers) | [Polish trains GTFS](https://mkuran.pl/gtfs/) by Mikołaj Kuranowski, built from the PKP PLK open data API | daily (downloaded only when changed) |
| Delays and cancellations | [PKP PLK Otwarte Dane Kolejowe API](https://pdp-api.plk-sa.pl) when `PLK_API_KEY` is set, otherwise the [mkuran.pl realtime feed](https://mkuran.pl/gtfs/) (CC BY 4.0) | on demand, cached for 60 s |
| Rolling stock | "Zestawienie pociągów KM kursujących w dniach …" PDFs from [mazowieckie.com.pl](https://www.mazowieckie.com.pl/pl/kategoria/tabele-rozkladow-jazdy) | daily |

Usage follows the PKP PLK and Koleje Mazowieckie public sector information terms; the realtime feed is
used under CC BY 4.0 (attribution is shown in the bot's help).

### Rolling stock PDFs

The PDFs are hard to parse: cells span several lines, station names are split ("WARSZAWA ZACHODNIA PERON / 9")
and the dates column uses a compact notation with Roman numerals and legend symbols, e.g.

```
10 III-29 V (1-6) oprócz 21 IV,1,3 V     9 III-29 V (B) i 3 V     15 III-26 IV, 10-24 V (6)
```

The pipeline (`km_bot/rolling_stock`):

1. `scraper.py` finds the PDFs on KM's timetable period pages and archives expired ones.
2. `pdf_parser.py` extracts rows with PyMuPDF table detection; the original line-based heuristics remain as
   a fallback for layout changes (both give identical results on current PDFs).
3. `dates.py` turns every dates cell into concrete days: months inherited from the next item, years taken
   from the PDF validity period, the official KM legend – (A) Mon–Fri, (B) Mon–Fri + Sun, (C) Sat, Sun and
   holidays, (D) Mon–Fri except holidays, (E) Mon–Sat except holidays, (+) Sun and holidays, (1)…(7) weekdays
   – plus `oprócz …` / `i …` clauses and Polish public holidays (incl. Easter-based ones and 24 XII).
   All 145 distinct values found in the 2024–2026 PDFs parse deterministically.
4. Notations the parser does not know are sent to **Gemini as a fallback**; answers are validated (dates
   must lie in the validity period) and cached, so a new format no longer breaks the import.
5. `importer.py` stores one row per train number and day in `rolling_stock.sqlite`; when PDFs overlap, the
   newer list wins.

## Architecture

```
km_bot/
├── cli.py                 # python -m km_bot <command>
├── web.py                 # WSGI app for Passenger: Telegram webhook, /health, /img/*
├── config.py              # settings from .env
├── stations.py            # station search, nearest station
├── storage.py             # app.sqlite: favourites, routes, tracked trains, realtime cache
├── timetable/             # GTFS download/import + departure, connection and trip queries
├── realtime/              # PKP PLK and mkuran.pl providers with fallback
├── rolling_stock/         # PDF scraper, parser, date parser, Gemini fallback, catalog, repository
└── bot/                   # python-telegram-bot handlers, views, callbacks, tracking notifications
passenger_wsgi.py          # Passenger entry point
assets/trains/             # rolling stock photos served as link previews
```

Views are plain functions returning text + inline keyboard, so they are tested without Telegram. Handler
state lives in SQLite (not in memory) because Passenger may run several processes. Imported data is built
into a temporary database and swapped in atomically.

## Setup

Requirements: Python 3.14 (same as the hosting), [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env                 # at least TELEGRAM_API_TOKEN
uv run python -m km_bot refresh-data # GTFS + rolling stock (~20 s)
uv run python -m km_bot poll         # run locally with long polling
```

### CLI

| Command | Description |
| --- | --- |
| `poll` | Run the bot with long polling (local development, Docker) |
| `refresh-data [--gtfs-only \| --rolling-stock-only] [--force] [--no-download]` | Download and import data |
| `import-pdf FILE...` | Add rolling stock PDFs manually and rebuild |
| `check-tracked` | Send tracked-train notifications (cron) |
| `set-webhook`, `delete-webhook`, `webhook-info` | Manage the Telegram webhook |
| `plk-check` | Verify the PKP PLK API key |

### Tests

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The suite covers the date parser (real PDF values), PDF parsing, GTFS import and queries (incl. trains
after midnight), station search, realtime providers (mocked HTTP), tracking rules, views and end-to-end
webhook flows through the real python-telegram-bot application with a fake Bot API.

## Deployment

Hosting on Hostido with Phusion Passenger and a webhook, deployed with `deploy.ps1` / `deploy.sh` like
GrafikPlusWeb – see [DEPLOYMENT.md](DEPLOYMENT.md).

## Ideas for next steps

- **Morning digest** – scheduled message with the next trains on a saved route (e.g. weekdays at 7:00).
- **Disruptions** – PKP PLK `/disruptions` endpoint (with an API key) for stations and saved routes.
- **Inline mode** – `@kmkobot Śródmieście` in any chat to share a departure board.
- **Rolling stock statistics** – "which lines run Flirts today", "how often is my train a Kibel".
- **Connections with a change** – two-leg trips (e.g. via Warszawa Zachodnia) for routes without direct trains.
- **WKD and Warsaw public transport** – additional GTFS feeds from mkuran.pl.
