"""The pure part of the macOS driver (cell to screen point); runs on every OS."""

from uat_macos import cell_center


def test_cell_center_is_the_middle_of_the_cell_below_the_title_bar() -> None:
    # An 860 x 600 window at (40, 60) holding 100 x 20 cells: cells are 8.6 x 28.6 points below the 28 point title bar.
    assert cell_center((40, 60, 860, 600), (100, 20), 0, 0) == (44, 102)
    assert cell_center((40, 60, 860, 600), (100, 20), 99, 19) == (896, 646)


def test_cell_center_scales_with_the_reported_size() -> None:
    x0, _ = cell_center((0, 0, 800, 428), (80, 25), 10, 0)
    x1, _ = cell_center((0, 0, 800, 428), (80, 25), 11, 0)
    assert x1 - x0 == 10
