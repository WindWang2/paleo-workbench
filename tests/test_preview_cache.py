from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_cache import PreviewCache, make_preview_cache_key
from paleo_workbench.ui.pages.preview_provider import PreviewResult


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
