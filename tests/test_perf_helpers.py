from tests.perf.fixtures import make_mock_resources, make_tmp_tree
from tests.perf.timing import timed, format_stress_line


def test_make_mock_resources_count():
    items = make_mock_resources(10)
    assert len(items) == 10
    assert items[0].type == "well_log"
    assert items[5].type in {"well_log", "seismic", "horizon", "document"}


def test_timed_returns_positive_ms():
    t, _ = timed("x", lambda: sum(range(1000)))
    assert t.name == "x"
    assert t.ms >= 0.0
    line = format_stress_line("S1_update", n=2000, ms=12.3)
    assert line.startswith("[datapage-stress]")
    assert "elapsed_ms=12.3" in line or "elapsed_ms=12.30" in line


def test_make_tmp_tree(tmp_path):
    root = make_tmp_tree(tmp_path, n=5)
    assert len(list(root.rglob("*"))) >= 5
