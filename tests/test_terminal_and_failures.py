"""Terminal restore, plain failure messages, the crash log and the reasons shown for a source that gave nothing."""

from __future__ import annotations

import io
import signal
import sys
from pathlib import Path

import httpx
import pytest
from test_app_smoke import METARS, NOW, make_app, offline_client, wait_for

from wxbrief import diagnostics, terminal
from wxbrief.__main__ import main
from wxbrief.data.awc import AwcClient, TransportError
from wxbrief.data.models import parse_metars
from wxbrief.data.poll import Product
from wxbrief.ui.asciify import to_ascii
from wxbrief.ui.widgets.status_bar import StatusBar


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WXBRIEF_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("WXBRIEF_LOG_DIR", str(tmp_path / "logs"))


# --- #265 #235: every mode the app turns on is turned off, however the program ends ---------------------------------


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_restore_switches_every_mode_off_in_one_write() -> None:
    out = FakeTty()
    terminal.restore(out)
    for code in ("?1000l", "?1003l", "?1006l", "?1015l", "?1004l", "?2004l", "?1049l", "?25h"):
        assert f"\x1b[{code}" in out.getvalue(), code
    assert out.getvalue().index("?1004l") < out.getvalue().index("?1049l")


def test_restore_writes_nothing_where_there_is_no_terminal() -> None:
    out = io.StringIO()
    terminal.restore(out)
    assert out.getvalue() == ""


def test_a_terminating_signal_restores_the_terminal_and_the_handlers_come_back(monkeypatch: pytest.MonkeyPatch) -> None:
    restored: list[bool] = []
    monkeypatch.setattr(terminal, "restore", lambda stream=None: restored.append(True))
    app = type("App", (), {"_loop": None})()
    before = signal.getsignal(signal.SIGTERM)
    with terminal.restore_on_exit(app):  # type: ignore[arg-type]
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not before
        with pytest.raises(SystemExit) as stopped:  # no running loop yet: nothing to close, so the process ends
            handler(signal.SIGTERM, None)  # type: ignore[operator]
        assert stopped.value.code == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) is before
    assert len(restored) == 2, "restored by the handler, and again when the app ends"


# --- #256: no terminal -----------------------------------------------------------------------------------------------


def test_no_terminal_says_so_on_stderr_and_fails(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert main(["KDEN"]) == 2
    shown = capsys.readouterr()
    assert "interactive terminal" in shown.err and "wxbrief get" in shown.err
    assert shown.out == "", "the help text must not be printed in place of the app"


# --- #254: get says it in plain words --------------------------------------------------------------------------------


def test_get_with_the_network_down_gives_one_plain_line(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed", request=request)

    real = AwcClient.__init__

    def init(self: AwcClient, *args: object, **kwargs: object) -> None:
        real(self, client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))

    monkeypatch.setattr(AwcClient, "__init__", init)
    assert main(["--no-config", "get", "KJFK", "--plain"]) == 1
    err = capsys.readouterr().err
    assert "ConnectError" not in err and "httpx" not in err
    assert err.count("wxbrief get:") == 1 and "METAR, TAF" in err and "aviationweather.gov" in err


# --- #216: a crash leaves a log and a path; --diagnose -----------------------------------------------------------------


def test_a_crash_prints_the_log_path_not_a_traceback(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(args: object) -> int:
        raise RuntimeError("deliberate")

    monkeypatch.setattr("wxbrief.__main__._run_decode", boom)
    assert main(["decode", "METAR KDEN 131453Z 06007KT 10SM CLR 09/08 A3001"]) == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err and "RuntimeError" in err
    log = tmp_path / "logs" / "wxbrief.log"
    assert str(log) in err and "--diagnose" in err
    assert "RuntimeError: deliberate" in log.read_text(encoding="utf-8")


def test_an_unwritable_log_does_not_hide_the_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("WXBRIEF_LOG_DIR", str(blocker / "inside"))  # a folder cannot be made under a file
    assert diagnostics.write_crash_log(RuntimeError("x")) is None
    assert "could not be written" in diagnostics.crash_message(RuntimeError("x"), None)


def test_diagnose_prints_version_platform_terminal_and_paths(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["--diagnose", "--config", str(tmp_path / "c.toml")]) == 0
    out = capsys.readouterr().out
    for label in ("wxbrief:", "Python:", "Platform:", "Terminal:", "colour system:", "NO_COLOR:", "config:", "cache:", "log:"):
        assert label in out, label
    assert str(tmp_path / "c.toml") in out and str(tmp_path / "logs" / "wxbrief.log") in out


async def test_an_unhandled_error_in_the_app_exits_with_the_log_path(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    app.options.poll = False
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._exception = RuntimeError("inside the app")
        app._fatal_error()
        shown = "".join(str(r) for r in app._exit_renderables)
        app._exit_renderables.clear()
        app._exception = None
        app.exit()
    assert "Traceback" not in shown and str(tmp_path / "logs" / "wxbrief.log") in shown
    assert "RuntimeError: inside the app" in (tmp_path / "logs" / "wxbrief.log").read_text(encoding="utf-8")


# --- #258: the Ctrl-C hint is plain text -----------------------------------------------------------------------------


async def test_ctrl_c_hint_is_plain_text(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    app.options.poll = False
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+c")
        await wait_for(pilot, lambda: bool(app._notifications), "the quit hint")
        messages = [n.message for n in app._notifications]
    assert any("ctrl+q" in m for m in messages) and not any("[b]" in m or "[/b]" in m for m in messages), messages


# --- #234 #247: the ascii glyph set draws ASCII ----------------------------------------------------------------------


def test_to_ascii_maps_borders_bars_arrows_and_keeps_letters_and_degrees() -> None:
    drawn = "▁▔▊▎▌▏▅▀▒─━│┃╭╮╯╰┏┓┗┛▶▲←→…●◐"
    out = to_ascii(drawn)
    assert out.isascii() and len(out) == len(drawn), "one character in, one out"
    assert to_ascii("Zürich 270°") == "Zürich 270°"
    escape = "\x1b[1;38;2;1;2;3mabc\x1b[0m"
    assert to_ascii(escape) == escape


async def test_the_driver_output_is_ascii_only_while_the_ascii_set_is_on(tmp_path: Path) -> None:
    """The headless driver draws nothing, so what the filter hands the driver is tried directly; the real-terminal
    suite (``test_ascii_glyph_set_draws_only_ascii_symbols``) checks the whole screen."""
    app = make_app(tmp_path, ["KDEN"])
    app.options.poll = False
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        driver = app._driver
        assert driver is not None
        sent: list[str] = []
        driver.write = sent.append  # type: ignore[method-assign]
        app._ascii_output()  # wraps whatever write the driver has now
        app.apply_setting("glyph_set", "ascii")
        driver.write("▁▊▔ 270° ▶")
        app.apply_setting("glyph_set", "unicode")
        driver.write("▁▊▔ 270° ▶")
    assert sent[0] == "_|- 270° >" and sent[1] == "▁▊▔ 270° ▶"


# --- #236 #262: a source that gave nothing says so ---------------------------------------------------------------------


def status(app: object) -> str:
    return str(app.screen.query_one(StatusBar).render())  # type: ignore[attr-defined]


async def test_first_run_with_the_network_down_says_offline_after_the_first_failure(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"], offline_client())
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: "offline" in status(app), "offline after the first failed fetch", timeout=10)


async def test_one_dropped_connection_with_saved_data_is_still_not_an_outage(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    app.options.poll = False
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._on_result(Product.METAR, parse_metars(METARS))
        app._on_error(Product.METAR, TransportError("down"))
        await pilot.pause()
        assert "offline" not in status(app)
        app._on_error(Product.METAR, TransportError("down"))
        await wait_for(pilot, lambda: "offline" in status(app), "offline from the second failure")


async def test_a_metar_list_that_came_back_empty_says_so(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"])
    app.options.poll = False
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app._on_result(Product.METAR, [])
        await wait_for(pilot, lambda: "METAR list came back empty" in status(app), "the empty METAR list stated")
        app._on_result(Product.METAR, parse_metars(METARS))
        await wait_for(pilot, lambda: "came back empty" not in status(app), "the note gone once reports arrive")


async def test_a_taf_source_that_failed_or_was_empty_is_stated_while_the_metar_is_fresh(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["KDEN"], now=NOW)
    app.options.poll = False
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app._on_error(Product.TAF, TransportError("dropped"))
        app._on_result(Product.METAR, parse_metars(METARS))
        await wait_for(pilot, lambda: "TAF not available" in status(app), "the missing forecast stated")
        app._on_result(Product.TAF, [])
        await wait_for(pilot, lambda: "TAF list came back empty" in status(app), "the empty forecast list stated")
