"""Snapshot-based background job for contour extraction."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from geoviz import CancellationToken, JobCancelled


@dataclass(frozen=True)
class ContourDraftResult:
    drafts: list

    @property
    def count(self) -> int:
        return len(self.drafts)


class ContourDraftWorker(QObject):
    """Extract contours from an immutable project snapshot.

    Applying drafts to live map documents remains a short GUI-thread commit,
    so edits made while extraction runs are not overwritten by a stale clone.
    """

    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    terminal = Signal()

    def __init__(
        self,
        project,
        parent=None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project.model_copy(deep=True)
        self._cancellation_token = cancellation_token or CancellationToken()

    def run(self) -> None:
        try:
            self._cancellation_token.raise_if_cancelled()
            from paleo_workbench.workflow.contour_draft import (
                compile_contour_drafts_for_project,
            )

            drafts = compile_contour_drafts_for_project(
                self._project,
                apply_to_map=False,
                cancellation_token=self._cancellation_token,
            )
            self._cancellation_token.raise_if_cancelled()
            self.completed.emit(ContourDraftResult(drafts=list(drafts)))
        except JobCancelled:
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - relay failure to host status
            self.failed.emit(f"{exc.__class__.__name__}: {exc}")
        finally:
            self.terminal.emit()


def commit_contour_drafts(project, result: ContourDraftResult) -> list:
    """Apply a worker result to the live project as a bounded GUI commit."""
    from paleo_workbench.workflow.contour_draft import (
        apply_contour_draft_to_map,
        upsert_contour_draft,
    )

    committed = []
    for draft in result.drafts:
        upsert_contour_draft(project, draft)
        apply_contour_draft_to_map(project, draft)
        committed.append(draft)
    return committed
