"""Gemini-based fallback for date expressions the deterministic parser does not understand.

KM occasionally introduces new notations in the PDFs. Instead of failing the import, unknown expressions are
sent to Gemini. The model does not list dates itself - language models are unreliable at calendar arithmetic
(which weekday is 17 X 2026?). It translates the expression into a structure instead:

    {"input": "4-24 X w dni robocze", "understood": true,
     "ranges": [{"from": "2026-10-04", "to": "2026-10-24"}], "rule": "D", "except": [], "also": []}

The dates are then computed by the same code as for parsed expressions (``build_schedule``), including its
checks: every date inside the validity period, exceptions inside the range, a non-empty result. The model can
answer ``understood: false``; such rows, and answers that fail the checks, are skipped rather than guessed.
Accepted answers are cached on disk, so each new expression costs one request at most once.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from km_bot.rolling_stock.dates import DateParseError, Period, build_schedule
from km_bot.rolling_stock.holidays import public_holidays

log = logging.getLogger(__name__)

BATCH_SIZE = 20
# Alias that always points to the current Flash-Lite model, used when the configured model is retired.
FALLBACK_MODEL = "gemini-flash-lite-latest"

SYSTEM_PROMPT = """\
You translate "operating days" expressions from Polish railway timetables (Koleje Mazowieckie) into a JSON
structure. You never list individual operating days and never compute weekdays yourself.

Notation:
- Months are Roman numerals: I=January ... XII=December. A month applies to all preceding days without a month:
  "1,7 XII" = 1 XII and 7 XII; "2-5,9-12 VI" = 2-5 VI and 9-12 VI; "16,23 II,2 III" = 16 II, 23 II, 2 III.
- "a-b" is an inclusive range. Arabic dates like "04.10" or "2026-10-04" may also appear.
- Day rules (official legend), usually in parentheses:
  A = Monday-Friday; B = Monday-Friday and Sundays; C = Saturdays, Sundays and public holidays;
  D = Monday-Friday except public holidays; E = Monday-Saturday except public holidays;
  + = Sundays and public holidays; digits are ISO weekdays: "1-6" = Monday-Saturday, "2-5,7", "6" = Saturday.
- "oprócz <dates>" = except these dates; "i <dates>" = also on these dates (even if the rule excludes them).
- "except" and "also" contain only dates written explicitly in the expression. Weekday exclusions are rules:
  "oprócz sobót" = rule "1-5,7", "oprócz niedziel" = rule "1-6"; never list such dates one by one.
- Plain-language rules map to the same codes: "w dni robocze" = D, "codziennie" = no rule,
  "w soboty i niedziele" = "6-7", "pn-pt" = "1-5", "w weekendy i święta" = C.

Output one object per input expression, in the same order, with:
- "input": the expression exactly as given,
- "understood": false if any part of the expression is ambiguous or not covered above; then leave the lists empty,
- "ranges": date ranges as {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"} (a single day has from == to). Years come
  from the validity period. An expression without explicit dates means the whole validity period,
- "rule": one legend code (A, B, C, D, E, +), an ISO weekday list such as "1-5" or "2-5,7", or null for every day,
- "except": dates removed (YYYY-MM-DD), "also": dates added (YYYY-MM-DD).

Example for validity period 2025-03-09 - 2025-05-29:
"10 III-29 V (1-6) oprócz 21 IV,1,3 V" -> {"understood": true, "ranges": [{"from": "2025-03-10", "to": "2025-05-29"}],
"rule": "1-6", "except": ["2025-04-21", "2025-05-01", "2025-05-03"], "also": []}
"9 III-29 V (B) i 3 V" -> {"understood": true, "ranges": [{"from": "2025-03-09", "to": "2025-05-29"}], "rule": "B",
"except": [], "also": ["2025-05-03"]}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "understood": {"type": "boolean"},
                    "ranges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"from": {"type": "string"}, "to": {"type": "string"}},
                            "required": ["from", "to"],
                        },
                    },
                    "rule": {"type": "string", "nullable": True},
                    "except": {"type": "array", "items": {"type": "string"}},
                    "also": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["input", "understood", "ranges", "except", "also"],
            },
        }
    },
    "required": ["results"],
}


def written_day_numbers(expression: str) -> set[int]:
    """Day numbers written in an expression, ignoring rule codes "(1-6)" and footnotes "[1]"."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", expression)
    return {int(n) for n in re.findall(r"(?<![\d.])(\d{1,2})(?![\d])", text) if 1 <= int(n) <= 31}


def check_grounded(item: dict, expression: str, period: Period) -> None:
    """Rejects answers that use days not written in the expression (hallucinated dates)."""
    written = written_day_numbers(expression)
    ranges = item.get("ranges") or []
    used = [span[key] for span in ranges for key in ("from", "to")]
    used += list(item.get("except") or []) + list(item.get("also") or [])
    if not written:
        # No explicit dates ("codziennie"): only "the whole validity period" is acceptable.
        whole = [{"from": period.start.isoformat(), "to": period.end.isoformat()}]
        if (ranges and ranges != whole) or item.get("except") or item.get("also"):
            raise DateParseError("Answer contains dates although the expression has none")
        return
    invented = sorted({value for value in used if date.fromisoformat(value).day not in written})
    if invented:
        raise DateParseError(f"Answer uses days not written in the expression: {invented[:3]}")


def evaluate_answer(item: dict, period: Period, expression: str | None = None) -> set[date]:
    """Computes operating days from one structured answer. Raises DateParseError when it is unusable."""
    if not item.get("understood"):
        raise DateParseError("Gemini did not understand the expression")
    if expression is not None:
        try:
            check_grounded(item, expression, period)
        except (KeyError, TypeError, ValueError) as exc:
            raise DateParseError(f"Malformed answer: {exc}") from exc
    try:
        base: set[date] = set()
        for span in item.get("ranges") or []:
            start, end = date.fromisoformat(span["from"]), date.fromisoformat(span["to"])
            if end < start or (end - start).days > 400:
                raise DateParseError(f"Invalid range {span}")
            base.update(Period(start, end).days())
        excluded = {date.fromisoformat(d) for d in item.get("except") or []}
        added = {date.fromisoformat(d) for d in item.get("also") or []}
    except (KeyError, TypeError, ValueError) as exc:
        raise DateParseError(f"Malformed answer: {exc}") from exc
    if not base and not added:
        base = set(period.days())  # no explicit dates = the whole validity period
    rule = item.get("rule") or None
    return build_schedule(base, rule, excluded, added, period)


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
        except OSError, ValueError:
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def convert(self, expressions: list[str], period: Period) -> dict[str, set[date]]:
        """Returns dates for every expression that could be converted (missing keys = not converted)."""
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

        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            try:
                answer = self._ask(batch, period)
            except Exception as exc:
                log.error("Gemini request failed for %d expressions: %s", len(batch), exc)
                continue
            answers = {item.get("input"): item for item in answer.get("results") or [] if isinstance(item, dict)}
            for expression in batch:
                item = answers.get(expression)
                if item is None:
                    log.warning("Gemini returned no answer for %r", expression)
                    continue
                try:
                    dates = evaluate_answer(item, period, expression)
                except DateParseError as exc:
                    log.warning("Gemini answer for %r rejected: %s (%s)", expression, exc, json.dumps(item))
                    continue
                result[expression] = dates
                self._cache[self._key(expression, period)] = sorted(d.isoformat() for d in dates)
                log.info("Gemini converted %r -> %d dates", expression, len(dates))
        self._save_cache()
        return result

    def _ask(self, expressions: list[str], period: Period) -> dict:
        from google import genai
        from google.genai import errors as genai_errors
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
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            temperature=0,
        )
        try:
            response = client.models.generate_content(model=self.model, contents=prompt, config=config)
        except genai_errors.ClientError as exc:
            # Google retires model versions (gemini-2.5-flash-lite answers 404 for new keys since 2026).
            if exc.code != 404 or self.model == FALLBACK_MODEL:
                raise
            log.warning("Gemini model %s is not available (%s) - using %s", self.model, exc, FALLBACK_MODEL)
            self.model = FALLBACK_MODEL
            response = client.models.generate_content(model=self.model, contents=prompt, config=config)
        usage = response.usage_metadata
        if usage is not None:
            log.info(
                "Gemini %s: %s prompt + %s output tokens",
                self.model,
                usage.prompt_token_count,
                usage.candidates_token_count,
            )
        return json.loads(response.text or "{}")
