"""In-process plot-change signal bus (Phase-2, T7 / #251).

The composite figure (油藏综合图) must refresh its embedded source-plot
panels when the source plots change. The Workstation has no engine observer
Python surface (ViewEvent / DocumentRevision are C++-side), so the host
emits ``plot_changed`` after its own imperative save/render calls.

- ``plot_bus`` is a module-level singleton.
- ``plot_changed(plot_id: str, revision: int)`` - revision is a per-plot
  in-memory monotonic counter (NOT persisted; workspace.json stores no
  revision field per T7 - avoids another T9 schema bump).
- Emit sites (T7): shell save_plot_document callers, MultiTrackCanvas /
  CorrelationCanvas depth_range_changed handlers, editor dirty->save hooks.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class PlotEventBus(QObject):
    """Broadcasts per-plot revision changes within the process."""

    plot_changed = Signal(str, int)  # (plot_id, revision)


# Module-level singleton (T7).
plot_bus = PlotEventBus()

# In-memory per-plot revision counters (NOT persisted - T7).
_revisions: dict[str, int] = {}


def bump_plot_revision(plot_id: str) -> int:
    """Increment + return the revision for a plot id (in-memory only)."""
    rev = _revisions.get(plot_id, 0) + 1
    _revisions[plot_id] = rev
    return rev


def emit_plot_changed(plot_id: str) -> int:
    """Bump the revision and emit ``plot_bus.plot_changed``.

    Returns the new revision so callers can correlate.
    """
    rev = bump_plot_revision(plot_id)
    plot_bus.plot_changed.emit(plot_id, rev)
    return rev


def plot_revision(plot_id: str) -> int:
    """Current revision for a plot id (0 when never bumped)."""
    return _revisions.get(plot_id, 0)


def reset_revisions() -> None:
    """Clear revision counters (test/CI hook)."""
    _revisions.clear()
