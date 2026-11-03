"""The Ctrl+P route switcher: ``KDEN KORD KJFK`` adds what is missing and selects the first station."""

from __future__ import annotations

import pytest
from ux_kit import briefing, load, make_app, rows

from wxbrief.config import WATCHLIST_CAP
from wxbrief.data.stations import StationDB
from wxbrief.ui.commands import Route, parse_route
from wxbrief.ui.screens.help import HelpScreen

KNOWN = {"KDEN", "KORD", "KJFK", "EGLL"}
ALIAS = {"DEN": "KDEN"}


def resolve(code: str) -> str | None:
    return ALIAS.get(code, code if code in KNOWN else None)


@pytest.mark.parametrize(
    "text",
    [
        "KDEN KORD KJFK",
        "kden kord kjfk",
        "KDEN,KORD,KJFK",
        "KDEN>KORD>KJFK",
        "KDEN-KORD-KJFK",
        "KDEN → KORD / KJFK",
        "  KDEN  KORD;KJFK ",
    ],
)
def test_separators_and_case(text: str) -> None:
    assert parse_route(text, resolve) == Route(("KDEN", "KORD", "KJFK"), ())


def test_duplicates_collapse_including_aliases() -> None:
    assert parse_route("KDEN DEN KORD kden", resolve) == Route(("KDEN", "KORD"), ())


def test_invalid_ids_are_rejected_not_dropped() -> None:
    assert parse_route("KDEN ZZZZ KORD ZZZZ", resolve) == Route(("KDEN", "KORD"), ("ZZZZ",))


@pytest.mark.parametrize(
    "text", ["", "   ", "Denver", "Denver KORD", "KD", "ZZZZ", "KDEN KORDX", ">>", "dark mode", "add stat", "ZZZZ QQQQ"]
)
def test_plain_searches_are_not_routes(text: str) -> None:
    assert parse_route(text, resolve) is None


def test_one_known_code_is_a_route_of_one() -> None:
    assert parse_route("kord", resolve) == Route(("KORD",), ())


def test_bundled_database_resolves_through_station_get() -> None:
    db = StationDB.load()
    route = parse_route("KDEN>EGLL>KORD", lambda code: getattr(db.get(code), "icao", None))
    assert route == Route(("KDEN", "EGLL", "KORD"), ())


async def _palette(app, pilot, text: str) -> list[str]:  # type: ignore[no-untyped-def]
    await pilot.press("ctrl+p")
    await pilot.pause()
    assert type(app.screen).__name__ == "CommandPalette"
    names = {" ": "space", ">": "greater_than_sign", "-": "minus"}
    await pilot.press(*(names.get(ch, ch) for ch in text))
    await pilot.pause(0.3)
    from textual.command import CommandList

    options = app.screen.query_one(CommandList)
    return [str(options.get_option_at_index(i).prompt) for i in range(options.option_count)]


async def test_route_adds_missing_stations_and_selects_the_first(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(80, 24)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        titles = await _palette(app, pilot, "KORD>KDEN")
        assert "Show route KORD > KDEN" in titles[0]
        await pilot.press("enter")
        await pilot.pause()
        assert sorted(app.state.ids) == ["EGLL", "KDEN", "KORD"]
        assert briefing(app).selected == "KORD"
        assert type(app.screen).__name__ == "BriefingScreen"


async def test_route_with_an_unknown_id_says_why_and_changes_nothing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(80, 24)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        titles = await _palette(app, pilot, "KORD ZZZZ")
        assert "ZZZZ" in titles[0] and "unknown" in titles[0].lower()
        await pilot.press("enter")
        await pilot.pause()
        assert app.state.ids == ["KDEN", "EGLL"]
        assert any("ZZZZ" in str(n.message) for n in app._notifications)


async def test_route_into_a_full_watchlist_adds_nothing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    full = [f"K{a}{b}{c}" for a in "ABC" for b in "ABCDEFGHIJ" for c in "ABCDEFGHIJ"][:WATCHLIST_CAP]
    app = make_app(tmp_path, [], watchlist=full)
    app.options.use_config = True
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.show_route(["KORD", "KJFK"])
        await pilot.pause()
        assert len(app.state.watchlist) == WATCHLIST_CAP
        assert "KORD" not in app.state.ids
        assert any("full" in str(n.message).lower() for n in app._notifications)


async def test_route_in_an_empty_station_list(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        titles = await _palette(app, pilot, "KDEN KORD")
        assert "Show route KDEN > KORD" in titles[0]
        await pilot.press("enter")
        await pilot.pause()
        assert sorted(app.state.ids) == ["KDEN", "KORD"]
        assert briefing(app).selected == "KDEN"


async def test_no_route_is_offered_over_a_modal(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN", "EGLL"])
    async with app.run_test(size=(80, 24)) as pilot:
        load(app, rows("metar_kden_egll"), rows("taf_kden_egll"))
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        titles = await _palette(app, pilot, "KORD KJFK")
        assert not any("route" in t.lower() for t in titles)


async def test_route_that_does_not_fit_adds_none_of_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    almost = [f"K{a}{b}{c}" for a in "ABC" for b in "ABCDEFGHIJ" for c in "ABCDEFGHIJ"][: WATCHLIST_CAP - 1]
    app = make_app(tmp_path, [], watchlist=almost)
    app.options.use_config = True
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.show_route(["KORD", "KJFK", "KDEN"])
        await pilot.pause()
        assert len(app.state.watchlist) == WATCHLIST_CAP - 1
        assert not {"KORD", "KJFK", "KDEN"} & set(app.state.ids)
        assert any("full" in str(n.message).lower() for n in app._notifications)


async def test_route_is_saved_once_with_every_new_station(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import tomllib

    app = make_app(tmp_path, [])
    app.options.use_config = True
    saves: list[bool] = []
    original = app._save
    app._save = lambda: saves.append(True) or original()  # type: ignore[method-assign]
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        saves.clear()
        app.show_route(["KORD", "KJFK", "KDEN"])
        await pilot.pause()
        assert len(saves) == 1
        saved = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
        assert saved["stations"]["watchlist"] == ["KORD", "KJFK", "KDEN"]
        assert briefing(app).selected == "KORD"
