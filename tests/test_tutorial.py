from km_bot.bot import callbacks as cb
from km_bot.bot import tutorial
from tests.conftest import at


def _data(view) -> list[str]:
    return [button.callback_data for row in view.buttons for button in row]


def test_contents_lists_every_page():
    view = tutorial.contents_view()
    assert "Samouczek" in view.text
    assert _data(view) == [cb.make(cb.TUTORIAL, 1)] + [
        cb.make(cb.TUTORIAL, n) for n in range(1, len(tutorial.PAGES) + 1)
    ]


def test_page_navigation():
    first, last = tutorial.page_view(1), tutorial.page_view(len(tutorial.PAGES))
    assert f"(samouczek 1/{len(tutorial.PAGES)})" in first.text
    assert "H:0" in _data(first) and "H:2" in _data(first) and not any(d == "H:0:-" for d in _data(first))
    assert not any(d.startswith("H:") and d.endswith(str(len(tutorial.PAGES) + 1)) for d in _data(last))
    assert tutorial.page_view(99).text == tutorial.contents_view().text
    for number in range(1, len(tutorial.PAGES) + 1):
        view = tutorial.page_view(number)
        assert len(view.text) < 4096
        assert all(len(d.encode()) <= 64 for d in _data(view))


def test_every_demo_produces_a_real_result(services):
    demos = [page.demo for page in tutorial.PAGES if page.demo]
    assert demos == ["departures", "number", "route"]
    now = at(7, 55)
    assert "Warszawa Śródmieście" in tutorial.demo_view(services, "departures", 1, 10, now).text
    number_demo = tutorial.demo_view(services, "number", 1, 10, now).text
    assert "Tabor:" in number_demo and "📍<b>Warszawa Śródmieście</b>" in number_demo
    assert "Warszawa Zachodnia → Warszawa Wschodnia" in tutorial.demo_view(services, "route", 1, 10, now).text
    assert "niedostępny" in tutorial.demo_view(services, "unknown", 1, 10, now).text


def test_offer_points_to_contents():
    assert _data(tutorial.offer_view()) == [cb.make(cb.TUTORIAL, 0)]
