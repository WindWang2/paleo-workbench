"""Latest-revision-per-subject cache shared by the mapping render/mirror paths.

V12-C (docs/development/render-increment-v12/00-decisions.md §D3): the render
backend (``_prepared``, ``_reprojected``, scalar-grid QImage cache) and
``qgis_mirror._SIGNATURE_CACHE`` each kept a private copy of the same
bookkeeping — "at most ONE revision per subject is retained, and a stale
revision is never served". One small container owns that contract here.

Locking, diagnostics and eviction triggers stay with the callers: the render
backend already serialises access with ``_prepared_lock`` and counts
hits/misses itself, and each caller decides when ``prune``/``clear`` run.
"""

from __future__ import annotations

from typing import Generic, Hashable, Iterable, Optional, TypeVar

SubjectT = TypeVar("SubjectT", bound=Hashable)
RevisionT = TypeVar("RevisionT")
ValueT = TypeVar("ValueT")

__all__ = ["LatestRevisionCache"]


class LatestRevisionCache(Generic[SubjectT, RevisionT, ValueT]):
    """One cached value per subject, valid only while its revision key matches.

    - :meth:`get` hits only on an exact revision-key match — an unknown or
      drifted revision is a miss, so callers rebuild instead of serving stale
      data (the #1257 lesson: invalidation must fail towards recompute).
    - :meth:`store` REPLACES any previous revision of the same subject, which
      keeps the container at one entry per subject (bounded by the active
      subject set, not by revision churn).
    - :meth:`latest` reads the stored value WITHOUT revision validation. It
      exists for the one legitimate "old value as delta baseline" reader
      (``qgis_mirror`` pre-delta signatures); render-side caches must not use
      it on the serving path.
    """

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[SubjectT, tuple[RevisionT, ValueT]] = {}

    def get(self, subject: SubjectT, revision_key: RevisionT) -> Optional[ValueT]:
        entry = self._entries.get(subject)
        if entry is not None and entry[0] == revision_key:
            return entry[1]
        return None

    def latest(self, subject: SubjectT) -> Optional[ValueT]:
        entry = self._entries.get(subject)
        return None if entry is None else entry[1]

    def store(self, subject: SubjectT, revision_key: RevisionT, value: ValueT) -> None:
        self._entries[subject] = (revision_key, value)

    def subjects(self) -> tuple[SubjectT, ...]:
        return tuple(self._entries)

    def remove(self, subject: SubjectT) -> None:
        self._entries.pop(subject, None)

    def prune(self, keep: Iterable[SubjectT]) -> None:
        keep_set = set(keep)
        for subject in [subject for subject in self._entries if subject not in keep_set]:
            del self._entries[subject]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
