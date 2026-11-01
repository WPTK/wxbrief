"""The pure part of the macOS driver (cell to screen point); runs on every OS."""

from uat_macos.driver import cell_center, cell_size


def test_cell_center_is_the_middle_of_the_cell_below_the_title_bar() -> None:
    # An 860 x 600 window at (40, 60) holding 100 x 20 cells: cells are 8.6 x 28.6 points below the 28 point title bar.
    assert cell_center((40, 60, 860, 600), (100, 20), 0, 0) == (44, 102)
    assert cell_center((40, 60, 860, 600), (100, 20), 99, 19) == (896, 646)


def test_cell_center_scales_with_the_reported_size() -> None:
    x0, _ = cell_center((0, 0, 800, 428), (80, 25), 10, 0)
    x1, _ = cell_center((0, 0, 800, 428), (80, 25), 11, 0)
    assert x1 - x0 == 10


def test_cell_size_comes_from_two_window_sizes_so_a_scroller_does_not_skew_it() -> None:
    # Cells 7 x 17 points inside a window with 22 points of side chrome and 36 of top and bottom chrome.
    samples = [(22 + 7 * 119, 36 + 17 * 33, 119, 33), (22 + 7 * 110, 36 + 17 * 36, 110, 36)]
    assert cell_size(samples) == (7.0, 17.0)
    assert cell_size(samples[:1]) is None
    assert cell_size([samples[0], (22 + 7 * 118, 36 + 17 * 34, 118, 34)]) is None  # too close to measure


def test_cell_center_with_a_measured_cell_starts_at_the_window_padding() -> None:
    x, y = cell_center((40, 60, 802, 539), (110, 36), 100, 30, cell=(7.0, 14.0))
    assert (x, y) == (round(40 + 4 + 100.5 * 7), round(60 + 28 + 2 + 30.5 * 14))
