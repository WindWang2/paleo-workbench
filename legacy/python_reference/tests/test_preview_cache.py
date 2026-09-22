from pathlib import Path

import pytest

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_cache import PreviewCache, make_preview_cache_key
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def test_cache_defaults_bound_count_and_bytes():
    cache = PreviewCache()

    assert cache.max_size == 32
    assert cache.max_bytes == 128 * 1024 * 1024
    assert cache.current_bytes == 0


def test_byte_budget_evicts_oldest_even_below_count_limit():
    cache = PreviewCache(max_size=32, max_bytes=100)
    cache.put(("a",), PreviewResult(mode="geoviz", title="a", estimated_bytes=60))
    cache.put(("b",), PreviewResult(mode="geoviz", title="b", estimated_bytes=60))

    assert cache.get(("a",)) is None
    assert cache.get(("b",)) is not None
    assert cache.current_bytes == 60


def test_single_oversize_payload_is_not_cached():
    cache = PreviewCache(max_bytes=100)
    cache.put(("big",), PreviewResult(mode="geoviz", title="big", estimated_bytes=101))

    assert cache.get(("big",)) is None
    assert cache.current_bytes == 0


def test_weight_falls_back_to_utf8_and_media_bytes_for_nonpositive_estimate():
    cache = PreviewCache(max_bytes=100)
    value = PreviewResult(
        mode="text",
        title="fallback",
        text="中",
        image_bytes=b"12",
        pdf_bytes=b"345",
        estimated_bytes=-999,
    )

    cache.put(("fallback",), value)

    assert cache.current_bytes == len("中".encode("utf-8")) + 2 + 3


def test_replacing_with_oversize_removes_old_entry_before_rejecting_new_value():
    cache = PreviewCache(max_bytes=100)
    cache.put(("same",), PreviewResult(mode="geoviz", title="old", estimated_bytes=40))

    cache.put(("same",), PreviewResult(mode="geoviz", title="new", estimated_bytes=101))

    assert cache.get(("same",)) is None
    assert cache.current_bytes == 0


def test_replace_updates_exact_weight_and_get_preserves_byte_accounting():
    cache = PreviewCache(max_size=2, max_bytes=100)
    cache.put(("a",), PreviewResult(mode="geoviz", title="a", estimated_bytes=60))
    cache.put(("b",), PreviewResult(mode="geoviz", title="b", estimated_bytes=30))

    assert cache.get(("a",)) is not None
    assert cache.current_bytes == 90
    cache.put(("b",), PreviewResult(mode="geoviz", title="b2", estimated_bytes=50))

    assert cache.get(("a",)) is None
    assert cache.get(("b",)).title == "b2"
    assert cache.current_bytes == 50


def test_clear_resets_current_bytes():
    cache = PreviewCache(max_bytes=100)
    cache.put(("a",), PreviewResult(mode="geoviz", title="a", estimated_bytes=60))

    cache.clear()

    assert cache.current_bytes == 0


def test_cache_rejects_nonpositive_limits():
    for kwargs in (
        {"max_size": 0},
        {"max_size": -1},
        {"max_bytes": 0},
        {"max_bytes": -1},
    ):
        with pytest.raises(ValueError):
            PreviewCache(**kwargs)


def test_cache_rejects_noninteger_limits():
    for kwargs in ({"max_size": 1.5}, {"max_size": True}, {"max_bytes": "100"}):
        with pytest.raises(TypeError):
            PreviewCache(**kwargs)


def test_lru_evicts_oldest(tmp_path):
    cache = PreviewCache(max_size=2)
    a = tmp_path / "a.txt"
    a.write_text("a")
    b = tmp_path / "b.txt"
    b.write_text("b")
    c = tmp_path / "c.txt"
    c.write_text("c")
    ra = ResourceItem(name="a", path=str(a), type="document", format="txt")
    rb = ResourceItem(name="b", path=str(b), type="document", format="txt")
    rc = ResourceItem(name="c", path=str(c), type="document", format="txt")
    cache.put(make_preview_cache_key(ra), PreviewResult(mode="text", title="a", text="a"))
    cache.put(make_preview_cache_key(rb), PreviewResult(mode="text", title="b", text="b"))
    cache.put(make_preview_cache_key(rc), PreviewResult(mode="text", title="c", text="c"))
    assert cache.get(make_preview_cache_key(ra)) is None
    assert cache.get(make_preview_cache_key(rb)) is not None
    assert cache.get(make_preview_cache_key(rc)) is not None


def test_key_changes_when_file_rewritten(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("v1")
    r = ResourceItem(name="a", path=str(path), type="document", format="txt", checksum="1")
    k1 = make_preview_cache_key(r)
    path.write_text("v2-longer")
    k2 = make_preview_cache_key(r)
    assert k1 != k2


def test_get_refreshes_lru_order(tmp_path):
    """Accessing an entry moves it to most-recent so it survives eviction."""
    cache = PreviewCache(max_size=2)
    a = tmp_path / "a.txt"
    a.write_text("a")
    b = tmp_path / "b.txt"
    b.write_text("b")
    c = tmp_path / "c.txt"
    c.write_text("c")
    ra = ResourceItem(name="a", path=str(a), type="document", format="txt")
    rb = ResourceItem(name="b", path=str(b), type="document", format="txt")
    rc = ResourceItem(name="c", path=str(c), type="document", format="txt")
    ka = make_preview_cache_key(ra)
    kb = make_preview_cache_key(rb)
    kc = make_preview_cache_key(rc)
    cache.put(ka, PreviewResult(mode="text", title="a", text="a"))
    cache.put(kb, PreviewResult(mode="text", title="b", text="b"))
    # Touch a so b becomes the oldest.
    assert cache.get(ka) is not None
    cache.put(kc, PreviewResult(mode="text", title="c", text="c"))
    assert cache.get(kb) is None
    assert cache.get(ka) is not None
    assert cache.get(kc) is not None


def test_clear_empties_cache(tmp_path):
    cache = PreviewCache(max_size=4)
    path = tmp_path / "x.txt"
    path.write_text("x")
    r = ResourceItem(name="x", path=str(path), type="document", format="txt")
    key = make_preview_cache_key(r)
    cache.put(key, PreviewResult(mode="text", title="x", text="x"))
    cache.clear()
    assert cache.get(key) is None
