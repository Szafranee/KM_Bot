"""Gemini-based fallback for date expressions the deterministic parser does not understand.

KM occasionally introduces new notations in the PDFs. Instead of failing the whole import, unknown
expressions are sent to Gemini, which returns explicit ISO dates. The answer is validated (dates must lie
inside the PDF validity period) and cached on disk, so each new expression is sent at most once.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from km_bot.rolling_stock.dates import Period
from km_bot.rolling_stock.holidays import public_holidays

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You convert operating-day expressions from Polish railway timetables (Koleje Mazowieckie) into explicit
lists of dates. Months are Roman numerals (I-XII); a month applies to all preceding days without a month
("1,7 XII" = 1 XII and 7 XII; "2-5,9-12 VI" = 2-5 VI and 9-12 VI).
Day rules in parentheses (official legend):
(A) Monday-Friday; (B) Monday-Friday and Sundays; (C) Saturdays, Sundays and public holidays;
(D) Monday-Friday except public holidays; (E) Monday-Saturday except public holidays;
(+) Sundays and public holidays; (1)...(7) ISO weekdays, e.g. (1-6) = Monday-Saturday, (2-5,7).
"oprócz <dates>" removes dates, "i <dates>" adds dates. An empty expression means every day of the period.
Return JSON: {"results": [{"input": "<expression exactly as given>", "dates": ["YYYY-MM-DD", ...]}]}.
Only return dates inside the validity period."""


class GeminiDateConverter:
    def __init__(self, api_key: str, model: str, cache_path: Path):
        self.api_key = api_key
        self.model = model
        self.cache_path = cache_path
        self._cache: dict[str, list[str]] = self._load_cache()

    @staticmethod
    def _key(expression: str, period: Period) -> str:
        return f"{period.start.isoformat()}|{period.end.isoformat()}|{expression}"

    def _load_cache(self) -> dict[str, list[str]]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def convert(self, expressions: list[str], period: Period) -> dict[str, set[date]]:
        """Returns dates for every expression that could be converted (missing keys = failure)."""
        result: dict[str, set[date]] = {}
        pending = []
        for expression in dict.fromkeys(expressions):
            cached = self._cache.get(self._key(expression, period))
            if cached is not None:
                result[expression] = {date.fromisoformat(d) for d in cached}
            else:
                pending.append(expression)
        if not pending:
            return result
        if not self.api_key:
            log.warning("GEMINI_API_KEY not set - %d date expressions left unparsed", len(pending))
            return result
        try:
            answer = self._ask(pending, period)
        except Exception:
            log.exception("Gemini date conversion failed")
            return result
        for item in answer.get("results", []):
            expression = item.get("input")
            if expression not in pending:
                continue
            try:
                dates = {date.fromisoformat(d) for d in item.get("dates", [])}
            except (TypeError, ValueError):
                log.warning("Gemini returned invalid dates for %r", expression)
                continue
            if not dates or any(d not in period for d in dates):
                log.warning("Gemini returned dates outside %s for %r", period, expression)
                continue
            result[expression] = dates
            self._cache[self._key(expression, period)] = sorted(d.isoformat() for d in dates)
            log.info("Gemini converted %r -> %d dates", expression, len(dates))
        self._save_cache()
        return result

    def _ask(self, expressions: list[str], period: Period) -> dict:
        from google import genai
        from google.genai import types

        holidays = sorted(
            f"{day.isoformat()} ({name})"
            for year in {period.start.year, period.end.year}
            for day, name in public_holidays(year).items()
            if day in period
        )
        prompt = (
            f"Validity period: {period.start.isoformat()} - {period.end.isoformat()}.\n"
            f"Public holidays in the period: {', '.join(holidays) or 'none'}.\n"
            f"Expressions:\n{json.dumps(expressions, ensure_ascii=False)}"
        )
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads(response.text or "{}")
