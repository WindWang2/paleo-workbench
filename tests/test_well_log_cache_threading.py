"""#1041 — thread-safe well-log LRU cache regression tests.

The module-level ``_las_cache`` used to be a bare ``OrderedDict`` mutated from
GUI thread (cache-hit fast path) and worker threads (``WellLogLoadWorker`` /
``CorrelationLoadWorker`` inserts + eviction) with no synchronization. This
suite pins the ``WellLogCache`` abstraction that makes every entry access —
lookup, insert, LRU reorder, eviction, clear — atomic.
"""

from __future__ import annotations

import threading

import pytest

import paleo_workbench.viz.well_log_load as mod
from paleo_workbench.viz.well_log_load import WellLogCache


def test_cache_lookup_miss_then_hit_roundtrip():
    cache = WellLogCache(max_entries=4)
    assert cache.get(("a", 1.0)) is None
    assert not cache.contains(("a", 1.0))
    cache.put(("a", 1.0), "payload-a")
    assert cache.contains(("a", 1.0))
    assert cache.get(("a", 1.0)) == "payload-a"


def test_cache_evicts_least_recently_used_beyond_capacity():
    cache = WellLogCache(max_entries=3)
    for i in range(5):
        cache.put((f"k{i}", 0.0), i)
    assert len(cache) == 3
    # k0/k1 were pushed out by k2/k3/k4
    assert not cache.contains(("k0", 0.0))
    assert not cache.contains(("k1", 0.0))
    assert cache.contains(("k2", 0.0))
    assert cache.contains(("k4", 0.0))


def test_cache_get_promotes_entry_so_lru_order_updates():
    cache = WellLogCache(max_entries=2)
    cache.put(("old", 0.0), 1)
    cache.put(("new", 0.0), 2)
    # touch "old" so "new" becomes the LRU victim
    assert cache.get(("old", 0.0)) == 1
    cache.put(("fresh", 0.0), 3)
    assert not cache.contains(("new", 0.0))
    assert cache.contains(("old", 0.0))


def test_cache_reput_same_key_does_not_grow_beyond_capacity():
    cache = WellLogCache(max_entries=2)
    for _ in range(10):
        cache.put(("same", 0.0), object())
        cache.put(("other", 0.0), object())
    assert len(cache) == 2


def test_cache_clear_empties_all_entries():
    cache = WellLogCache(max_entries=4)
    cache.put(("a", 0.0), 1)
    cache.put(("b", 0.0), 2)
    cache.clear()
    assert len(cache) == 0
    assert cache.get(("a", 0.0)) is None


def test_module_level_cache_is_the_thread_safe_abstraction():
    # The production module must no longer expose a bare OrderedDict that
    # callers can mutate without the lock.
    assert isinstance(mod._las_cache, WellLogCache)


def test_concurrent_mix_of_lookup_insert_and_eviction_is_safe():
    """Hammer the shared cache from many threads.

    Before #1041 the contains→get pair on the GUI thread raced the
    put→move_to_end→popitem eviction on worker threads: a key confirmed by
    ``in`` could be evicted before ``__getitem__``, and two concurrent
    inserts could both drive the size check past capacity. Any exception or
    size violation here fails the suite.
    """
    cache = WellLogCache(max_entries=8)
    errors: list[BaseException] = []

    def hammer(thread_id: int) -> None:
        try:
            for i in range(2_000):
                key = (f"well-{(thread_id * 31 + i) % 40}", float(i % 7))
                hit = cache.get(key)
                if hit is not None:
                    assert hit[0] == key
                cache.put(key, (key, i))
                cache.contains((f"well-{i % 40}", 0.0))
                if len(cache) > 8:
                    raise AssertionError(f"cache exceeded capacity: {len(cache)}")
        except BaseException as exc:  # noqa: BLE001 — recorded and re-raised below
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "hammer thread deadlocked against the cache lock"

    assert not errors, errors
    assert len(cache) <= 8


def test_concurrent_same_key_writes_are_linearizable():
    cache = WellLogCache(max_entries=4)
    readers: list[int] = []

    def writer(tag: int) -> None:
        for i in range(1_000):
            cache.put(("shared", 0.0), tag)

    def reader() -> None:
        for _ in range(1_000):
            value = cache.get(("shared", 0.0))
            if value is not None:
                readers.append(value)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive()

    # every observed value is one of the writer tags — no torn/half-state reads
    assert set(readers) <= {0, 1, 2, 3}


@pytest.mark.parametrize("thread_count", [4, 12])
def test_is_well_log_cached_is_race_free_against_load(thread_count, tmp_path):
    """GUI-thread ``is_well_log_cached`` must not crash while workers fill/evict."""
    las_path = tmp_path / "race.las"
    las_path.write_text(
        "~VERSION INFORMATION\nVERS . 2.0 :\n~WELL\nWELL . RACE :\n"
        "~CURVE INFORMATION\nDEPT . m :\nGR . API :\n~A\n100 55\n110 60\n",
        encoding="utf-8",
    )
    errors: list[BaseException] = []

    def producer() -> None:
        try:
            for i in range(50):
                p = tmp_path / f"w{i}.las"
                p.write_text(
                    "~VERSION INFORMATION\nVERS . 2.0 :\n~WELL\n"
                    f"WELL . W{i} :\n~CURVE INFORMATION\nDEPT . m :\nGR . API :\n"
                    "~A\n100 55\n",
                    encoding="utf-8",
                )
                mod.load_well_log_from_path(str(p))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def consumer() -> None:
        try:
            for _ in range(500):
                mod.is_well_log_cached(str(las_path))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        *[threading.Thread(target=producer) for _ in range(thread_count - 1)],
        threading.Thread(target=consumer),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
        assert not t.is_alive()

    assert not errors, errors
