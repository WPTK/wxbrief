"""(e) The decoded table is synced in place: a refresh keeps the row cursor and the pane's scroll position."""

from __future__ import annotations

from dataclasses import replace

from ux_kit import load, make_app, rows

from wxbrief.ui.widgets.detail import DecodedTable, DetailPane


async def _loaded(tmp_path, pilot_app):  # type: ignore[no-untyped-def]
    load(pilot_app, rows("metar_kden_egll"), rows("taf_kden_egll"))


async def test_refresh_with_a_changed_value_keeps_cursor_scroll_and_untouched_rows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(80, 24)) as pilot:
        await _loaded(tmp_path, app)
        await pilot.pause()
        pane = app.screen.query_one(DetailPane)
        table = app.screen.query_one(DecodedTable)
        while pane.max_scroll_y < 6:  # laid out a frame or more after the load; a scroll before it clamps to 0
            await pilot.pause(0.02)
        table.cursor_type = "row"  # the table is read-only today; the cursor is how a refresh would show a reset
        table.move_cursor(row=4, animate=False)
        pane.scroll_to(y=6, animate=False)
        await pilot.pause()
        before_keys = list(table.rows)
        cursor, scroll = table.cursor_coordinate, pane.scroll_y
        assert cursor.row == 4 and scroll > 0

        changed = [replace(r, value=r.value + " (updated)") if i == 5 else r for i, r in enumerate(table._rows)]
        table.set_rows(changed, table._ctx, table._labels)  # type: ignore[arg-type]
        await pilot.pause()

        assert list(table.rows) == before_keys  # the same rows: nothing was cleared and rebuilt
        assert "(updated)" in str(table.get_row_at(5)[1])
        assert table.cursor_coordinate == cursor and pane.scroll_y == scroll


async def test_a_row_added_and_a_row_removed_leave_the_cursor_on_its_row(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = make_app(tmp_path, ["KDEN"])
    async with app.run_test(size=(120, 40)) as pilot:
        await _loaded(tmp_path, app)
        await pilot.pause()
        table = app.screen.query_one(DecodedTable)
        table.cursor_type = "row"
        original = list(table._rows)
        table.move_cursor(row=2, animate=False)
        extra = replace(original[-1], label=original[-1].label, value="one more")
        table.set_rows([*original[:-1], extra, replace(extra, value="and another")], table._ctx, table._labels)  # type: ignore[arg-type]
        assert table.row_count == len(original) + 1 and table.cursor_row == 2
        table.set_rows(original[1:], table._ctx, table._labels)  # type: ignore[arg-type]
        assert table.row_count == len(original) - 1
        assert [str(table.get_row_at(i)[0]) for i in range(table.row_count)] == [r.label for r in original[1:]]
