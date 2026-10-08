from datetime import date

import pytest

from km_bot.rolling_stock.dates import (
    DateParseError,
    Period,
    parse_date_list,
    parse_period,
    parse_schedule,
)
from km_bot.rolling_stock.holidays import easter_sunday, is_holiday, public_holidays
from km_bot.rolling_stock.pdf_parser import period_from_filename

SPRING_2025 = Period(date(2025, 3, 9), date(2025, 5, 29))
OCTOBER_2026 = Period(date(2026, 10, 4), date(2026, 10, 24))


def d(day: int, month: int, year: int = 2025) -> date:
    return date(year, month, day)


class TestDateLists:
    def test_single_range_across_months(self):
        dates = parse_date_list("9 III-29 V", SPRING_2025)
        assert min(dates) == d(9, 3) and max(dates) == d(29, 5) and len(dates) == 82

    def test_month_is_inherited_from_next_item(self):
        assert parse_date_list("1,7 XII", Period(d(1, 12, 2024), d(7, 12, 2024))) == {d(1, 12, 2024), d(7, 12, 2024)}
        assert parse_date_list("16,23 II,2 III", Period(d(14, 2), d(8, 3))) == {d(16, 2), d(23, 2), d(2, 3)}

    def test_multiple_ranges(self):
        dates = parse_date_list("2-5,9-12 VI", Period(d(30, 5), d(14, 6)))
        assert dates == {d(n, 6) for n in (2, 3, 4, 5, 9, 10, 11, 12)}

    def test_line_break_inside_range(self):
        dates = parse_date_list("15 III-26 IV, 10-\n24 V", SPRING_2025)
        assert d(26, 4) in dates and d(10, 5) in dates and d(27, 4) not in dates and d(24, 5) in dates

    def test_mixed_single_dates_and_ranges(self):
        assert parse_date_list("30 V,2-4 VI", Period(d(30, 5), d(14, 6))) == {d(30, 5), d(2, 6), d(3, 6), d(4, 6)}

    def test_year_boundary(self):
        period = Period(date(2025, 12, 14), date(2026, 1, 10))
        dates = parse_date_list("28 XII-3 I", period)
        assert min(dates) == date(2025, 12, 28) and max(dates) == date(2026, 1, 3)

    def test_arabic_and_iso_formats(self):
        assert parse_date_list("04.10-06.10", OCTOBER_2026) == {date(2026, 10, n) for n in (4, 5, 6)}
        assert parse_date_list("2026-10-05", OCTOBER_2026) == {date(2026, 10, 5)}

    @pytest.mark.parametrize("text", ["", "X", "5-", "31 II", "3 V-1 V", "12 ab"])
    def test_invalid(self, text):
        with pytest.raises(DateParseError):
            parse_date_list(text, SPRING_2025)


class TestSchedules:
    def test_weekday_rule_with_exceptions(self):
        dates = parse_schedule("10 III-29 V (1-6) oprócz 21 IV,1,3 V", SPRING_2025)
        assert d(22, 4) in dates  # Tuesday
        assert d(21, 4) not in dates and d(1, 5) not in dates and d(3, 5) not in dates
        assert all(day.isoweekday() <= 6 for day in dates)

    def test_rule_with_additional_dates(self):
        dates = parse_schedule("9 III-29 V (B) i 3 V", SPRING_2025)
        assert d(3, 5) in dates  # Saturday added explicitly
        assert d(10, 5) not in dates  # other Saturdays excluded by (B)
        assert d(11, 5) in dates  # Sunday

    def test_weekday_list_with_additions(self):
        dates = parse_schedule("9 III-25 V (5,7) i 21 IV,1,3 V", SPRING_2025)
        assert {d(21, 4), d(1, 5), d(3, 5), d(14, 3), d(16, 3)} <= dates
        assert d(15, 3) not in dates

    @pytest.mark.parametrize(
        ("rule", "included", "excluded"),
        [
            ("A", [d(21, 4)], [d(19, 4)]),  # Easter Monday is a weekday for (A)
            ("D", [d(22, 4)], [d(21, 4), d(1, 5), d(19, 4)]),
            ("C", [d(19, 4), d(20, 4), d(21, 4)], [d(22, 4)]),
            ("E", [d(19, 4), d(22, 4)], [d(21, 4), d(20, 4)]),
            ("+", [d(20, 4), d(21, 4), d(3, 5)], [d(19, 4), d(22, 4)]),
            ("B", [d(20, 4), d(21, 4)], [d(19, 4)]),
        ],
    )
    def test_legend_letters(self, rule, included, excluded):
        dates = parse_schedule(f"9 III-29 V ({rule})", SPRING_2025)
        assert all(day in dates for day in included)
        assert not any(day in dates for day in excluded)

    def test_empty_value_means_whole_period(self):
        assert parse_schedule("", OCTOBER_2026) == set(OCTOBER_2026.days())

    def test_dates_are_clipped_to_period(self):
        assert max(parse_schedule("1-31 X", OCTOBER_2026)) == date(2026, 10, 24)

    def test_unknown_rule_raises(self):
        with pytest.raises(DateParseError):
            parse_schedule("4-24 X (Q)", OCTOBER_2026)

    def test_unknown_modifier_raises(self):
        with pytest.raises(DateParseError):
            parse_schedule("4-24 X (D) w razie potrzeby", OCTOBER_2026)

    def test_real_october_2026_values(self):
        assert len(parse_schedule("5-23 X (D)", OCTOBER_2026)) == 15
        assert parse_schedule("4,11,18 X", OCTOBER_2026) == {date(2026, 10, n) for n in (4, 11, 18)}
        assert all(day.isoweekday() in (1, 7) for day in parse_schedule("4-19 X (1,7)", OCTOBER_2026))
        assert all(day.isoweekday() in (2, 3, 4, 5, 7) for day in parse_schedule("4-23 X (2-5,7)", OCTOBER_2026))


class TestPeriods:
    def test_header_formats(self):
        assert parse_period("okres obowiązywania 2026-10-04 - 2026-10-24") == OCTOBER_2026
        assert parse_period("okres obowiązywania 09.03.2025 - 29.05.2025") == SPRING_2025
        assert parse_period("nr poc") is None

    def test_from_filename(self):
        assert period_from_filename("Zestawienie pociągów KM kursujących w dniach 4-24 X 2026r..pdf") == OCTOBER_2026
        assert (
            period_from_filename("Zestawienie pociągów KM kursujących w dniach 09 III-29 V 2025r._0.pdf") == SPRING_2025
        )
        assert period_from_filename("random.pdf") is None


class TestHolidays:
    def test_easter(self):
        assert easter_sunday(2025) == d(20, 4)
        assert easter_sunday(2026) == date(2026, 4, 5)

    def test_movable_and_fixed(self):
        holidays = public_holidays(2026)
        assert date(2026, 6, 4) in holidays  # Corpus Christi
        assert date(2026, 5, 24) in holidays  # Pentecost
        assert is_holiday(date(2026, 11, 11))
        assert not is_holiday(date(2026, 11, 12))

    def test_christmas_eve_since_2025(self):
        assert is_holiday(date(2025, 12, 24))
        assert not is_holiday(date(2024, 12, 24))
