"""Task categories for global resource governance (P2-A).

Every heavy operation in the workbench is classified into one
:class:`TaskCategory`. The category fixes three governance defaults:

- **base priority** — the ordering the scheduler uses when two tasks compete
  (interactive rendering > previews > user-triggered computation > export >
  background indexing > maintenance);
- **interactivity** — interactive categories may always claim the cores the
  budget reserves for the GUI, background categories may not;
- **IO weight** — how many of the process-wide IO slots a task occupies while
  running (sequential transcode = high-throughput sequential IO, interactive
  slice reads = light random IO).

The mapping from scheduler ``kind`` strings (``"seismic.transcode"`` …) to
categories lives here so callers keep their existing vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskCategory(str, Enum):
    INTERACTIVE_RENDER = "interactive.render"
    INTERACTIVE_QUERY = "interactive.query"
    PREVIEW = "preview"
    BACKGROUND_IO = "background.io"
    BACKGROUND_COMPUTE = "background.compute"
    TRANSCODE = "seismic.transcode"
    ATTRIBUTE = "seismic.attribute"
    INFERENCE = "prediction.inference"
    EXPORT = "export"
    INDEXING = "indexing"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True, slots=True)
class CategoryPolicy:
    """Governance defaults for one category."""

    category: TaskCategory
    base_priority: int
    interactive: bool
    io_weight: float
    default_cpu_cores: float = 1.0

    @property
    def background(self) -> bool:
        return not self.interactive


# Priority ladder: interactive cursor/render > preview > user-triggered
# computation > export > background indexing > maintenance. Background work
# still ages up over time (scheduler aging) so it is never starved forever.
CATEGORY_POLICIES: dict[TaskCategory, CategoryPolicy] = {
    p.category: p
    for p in (
        CategoryPolicy(TaskCategory.INTERACTIVE_RENDER, 100, True, 1.0),
        CategoryPolicy(TaskCategory.INTERACTIVE_QUERY, 90, True, 1.0, 0.5),
        CategoryPolicy(TaskCategory.PREVIEW, 70, True, 1.0, 0.5),
        CategoryPolicy(TaskCategory.ATTRIBUTE, 50, False, 1.0),
        CategoryPolicy(TaskCategory.INFERENCE, 50, False, 1.0),
        CategoryPolicy(TaskCategory.TRANSCODE, 45, False, 4.0),
        CategoryPolicy(TaskCategory.EXPORT, 40, False, 2.0),
        CategoryPolicy(TaskCategory.BACKGROUND_COMPUTE, 30, False, 1.0),
        CategoryPolicy(TaskCategory.BACKGROUND_IO, 30, False, 2.0),
        CategoryPolicy(TaskCategory.INDEXING, 20, False, 2.0),
        CategoryPolicy(TaskCategory.MAINTENANCE, 10, False, 1.0),
    )
}


_KIND_PREFIX_MAP: tuple[tuple[str, TaskCategory], ...] = (
    ("seismic.transcode", TaskCategory.TRANSCODE),
    ("seismic.attribute", TaskCategory.ATTRIBUTE),
    ("prediction.inference", TaskCategory.INFERENCE),
    ("inference", TaskCategory.INFERENCE),
    ("export", TaskCategory.EXPORT),
    ("verify", TaskCategory.INDEXING),
    ("scan", TaskCategory.INDEXING),
    ("index", TaskCategory.INDEXING),
    ("maintenance", TaskCategory.MAINTENANCE),
    ("preview", TaskCategory.PREVIEW),
    ("render", TaskCategory.INTERACTIVE_RENDER),
)


def category_for_kind(kind: str) -> TaskCategory:
    """Classify a scheduler ``kind`` string; unknown kinds are background IO."""
    if not kind:
        return TaskCategory.BACKGROUND_IO
    lowered = kind.lower()
    for prefix, category in _KIND_PREFIX_MAP:
        if lowered.startswith(prefix):
            return category
    return TaskCategory.BACKGROUND_IO


def policy_for(category: TaskCategory) -> CategoryPolicy:
    return CATEGORY_POLICIES[category]
