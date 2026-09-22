"""ContourDraft: extract isolines from FactorMapTask grids (ISS-DOM-03).

Phase-2 promote-down (map #244 / PR-A #256): the pure extraction core
(``suggest_levels`` / ``extract_contour_segments`` / ``segments_to_line_features``
/ ``ContourSegment``) was promoted to ``geoviz_plots.contour_draft`` and is
consumed here through the ``geoviz`` facade where possible. This module keeps
the ``FactorMapTask`` / ``ProjectDocument`` / ``ContourDraft``-coupled adapters
(T10: ``project/models.py`` is NOT promoted); the local ``ContourSegment``
remains the Workbench pydantic type (the promoted dataclass is a separate,
serialization-compatible type).
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

from geoviz import suggest_levels
from paleo_workbench.project.models import (
    ContourDraft,
    ContourSegment,
    FactorMapTask,
    PaleoMapDocument,
    ProjectDocument,
    _id,
    _now_iso,
)

GENERATOR_VERSION = "contour-draft-v2"
DEFAULT_N_LEVELS = 8


def suggest_nice_levels_from_range(
    lo: float, hi: float, *, n_levels: int = DEFAULT_N_LEVELS
) -> list[float]:
    """Nice 1/2/2.5/5×10^k levels for an explicit [lo, hi] value range.

    Shared core of :func:`suggest_nice_levels`; the constrained-IDW adapter
    uses it to pick generation-time levels from the well value range before
    the grid exists (#928 upstream contour pipeline activation).
    """
    if not math.isfinite(lo) or not math.isfinite(hi):
        return []
    if math.isclose(lo, hi):
        return [lo]
    raw = (hi - lo) / max(int(n_levels), 1)
    magnitude = 10.0 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    step = 10.0 * magnitude
    for multiplier in (1.0, 2.0, 2.5, 5.0):
        candidate = multiplier * magnitude
        if candidate >= raw:
            step = candidate
            break
    levels: list[float] = []
    level = math.ceil(lo / step) * step
    guard = 0
    while level <= hi and guard < 512:
        if not (math.isclose(level, lo) or math.isclose(level, hi)):
            levels.append(round(float(level), 6))
        level += step
        guard += 1
    return levels


def suggest_nice_levels(
    grid_z: np.ndarray, *, n_levels: int = DEFAULT_N_LEVELS
) -> list[float]:
    """Upstream-style contour levels: nice 1/2/2.5/5×10^k steps (#928).

    The engine's ``suggest_levels`` is a raw linspace between data min/max,
    which yields unreadable label values (7.3, 14.6, …). Haiyou anchors levels
    at multiples of a rounded step (``ContourEngine.auto_levels``); this ports
    that semantics host-side. Exact min/max endpoints are excluded so
    isolines don't collapse onto the grid boundary (engine convention).
    """
    finite = grid_z[np.isfinite(grid_z)]
    if finite.size == 0:
        return []
    levels = suggest_nice_levels_from_range(
        float(finite.min()), float(finite.max()), n_levels=n_levels
    )
    if not levels:
        return suggest_levels(grid_z, n_levels=n_levels)
    return levels


def _grid_from_task(
    task: FactorMapTask,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load grid axes/values for contouring.

    Prefers the canonical FactorGridResult path (live in-session grid or managed
    NPZ artifact) so contouring does not depend on nested-list re-parsing. Falls
    back to legacy inline ``parameters`` for old fixtures.
    """
    try:
        from paleo_workbench.project.factor_grid_artifacts import (
            factor_grid_result_for_task,
        )

        result = factor_grid_result_for_task(task)
        return (
            np.asarray(result.grid_x, dtype=np.float64),
            np.asarray(result.grid_y, dtype=np.float64),
            np.asarray(result.grid_z, dtype=np.float64),
        )
    except (FileNotFoundError, ValueError, KeyError, TypeError, OSError):
        # Expected fallbacks: missing artifact, incomplete legacy params, bad shape.
        # Unexpected errors (e.g. ImportError of native deps) propagate.
        pass

    params = task.parameters or {}
    gx = params.get("grid_x")
    gy = params.get("grid_y")
    gz = params.get("grid_z")
    # Truthiness checks are only safe for sequences (legacy lists).  ndarray
    # presence is handled via ``is None`` so contour remains list-compatible.
    if gx is None or gy is None or gz is None:
        raise ValueError("FactorMapTask 缺少 grid_x/grid_y/grid_z，请先完成插值")
    if isinstance(gx, (list, tuple)) and not gx:
        raise ValueError("FactorMapTask 缺少 grid_x/grid_y/grid_z，请先完成插值")
    if isinstance(gz, (list, tuple)) and not gz:
        raise ValueError("FactorMapTask 缺少 grid_x/grid_y/grid_z，请先完成插值")
    grid_x = np.asarray(gx, dtype=np.float64)
    grid_y = np.asarray(gy, dtype=np.float64)
    grid_z = np.asarray(gz, dtype=np.float64)
    # JSON may store None for invalid cells
    if grid_z.dtype == object:
        grid_z = np.array(
            [[np.nan if v is None else float(v) for v in row] for row in gz],
            dtype=np.float64,
        )
    if grid_z.ndim != 2:
        raise ValueError(f"grid_z 维数错误: {grid_z.shape}")
    return grid_x, grid_y, grid_z


def _engine_contours_for_task(
    task: FactorMapTask, requested_levels: Sequence[float] | None
) -> tuple[list[ContourSegment], list[float]] | None:
    """Refined isolines stored on the task's grid result (#928).

    Returns ``(segments, stored_levels)`` when the constrained-IDW engine
    contours exist and the request matches the levels they were generated at
    (default request, or an explicit identical level list). Any mismatch
    returns ``None`` so the caller re-extracts from the grid via the raw
    pipeline.
    """
    try:
        from paleo_workbench.project.factor_grid_artifacts import (
            factor_grid_result_for_task,
        )

        result = factor_grid_result_for_task(task)
    except (FileNotFoundError, ValueError, KeyError, TypeError, OSError):
        return None
    contours = getattr(result, "contours", None)
    if not contours:
        return None
    stored_levels_raw = (result.algorithm_parameters or {}).get("contour_levels")
    if not stored_levels_raw:
        return None
    stored_levels = [float(v) for v in stored_levels_raw]
    if requested_levels is not None and not (
        len(requested_levels) == len(stored_levels)
        and all(
            math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-6)
            for a, b in zip(requested_levels, stored_levels)
        )
    ):
        return None
    segments: list[ContourSegment] = []
    for level_str, lines in sorted(contours.items(), key=lambda kv: float(kv[0])):
        for line in lines or []:
            coords = [[float(p[0]), float(p[1])] for p in line]
            if len(coords) < 2:
                continue
            closed = (
                len(coords) >= 3
                and math.isclose(coords[0][0], coords[-1][0], abs_tol=1e-9)
                and math.isclose(coords[0][1], coords[-1][1], abs_tol=1e-9)
            )
            segments.append(
                ContourSegment(
                    level=float(level_str),
                    coordinates=coords,
                    closed=closed,
                    properties={"level": float(level_str), "refined": True},
                )
            )
    if not segments:
        return None
    return segments, stored_levels


def _extract_via_engine(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    grid_z: np.ndarray,
    levels: Sequence[float],
    *,
    cancellation_token=None,
) -> dict[float, list[np.ndarray]]:
    # Workbench production code must import only the public ``geoviz`` facade
    # (see tests/test_geoviz_package_independence.py).
    try:
        from geoviz import extract_contour_lines
    except Exception as exc:
        raise ImportError(
            "geoviz.extract_contour_lines unavailable; ensure geoviz facade is installed"
        ) from exc
    return extract_contour_lines(
        grid_x,
        grid_y,
        grid_z,
        list(levels),
        cancellation_token=cancellation_token,
    )


def _segments_from_lines_dict(
    lines_dict: dict[float, list[Any]],
) -> list[ContourSegment]:
    segments: list[ContourSegment] = []
    for level, lines in sorted(lines_dict.items(), key=lambda kv: kv[0]):
        for line in lines or []:
            arr = np.asarray(line, dtype=np.float64)
            if arr.ndim != 2 or arr.shape[0] < 2 or arr.shape[1] < 2:
                continue
            coords = [[float(p[0]), float(p[1])] for p in arr]
            closed = (
                len(coords) >= 3
                and math.isclose(coords[0][0], coords[-1][0], abs_tol=1e-9)
                and math.isclose(coords[0][1], coords[-1][1], abs_tol=1e-9)
            )
            segments.append(
                ContourSegment(
                    level=float(level),
                    coordinates=coords,
                    closed=closed,
                    properties={"level": float(level)},
                )
            )
    return segments


def contour_draft_from_factor_task(
    task: FactorMapTask,
    *,
    levels: Sequence[float] | None = None,
    n_levels: int = DEFAULT_N_LEVELS,
    name: str | None = None,
    cancellation_token=None,
) -> ContourDraft:
    """Build a ContourDraft isoline set from an interpolated FactorMapTask."""
    grid_x, grid_y, grid_z = _grid_from_task(task)
    finite = grid_z[np.isfinite(grid_z)]
    if finite.size == 0:
        raise ValueError("网格无有效数值，无法生成等值线")
    zmin, zmax = float(np.min(finite)), float(np.max(finite))
    use_levels = (
        list(levels) if levels is not None else suggest_nice_levels(grid_z, n_levels=n_levels)
    )
    if not use_levels:
        use_levels = [zmin]

    # #928: prefer the engine-refined isolines stored at prepare time (the
    # vendored upstream pipeline: smooth / prune / join / barrier
    # interruption) over a raw marching-squares re-extraction when the level
    # request matches what was generated. The draft then reports the levels
    # the contours actually carry.
    engine = _engine_contours_for_task(
        task, list(levels) if levels is not None else None
    )
    if engine is not None:
        segments, use_levels = engine
    else:
        lines_dict = _extract_via_engine(
            grid_x,
            grid_y,
            grid_z,
            use_levels,
            cancellation_token=cancellation_token,
        )
        segments = _segments_from_lines_dict(lines_dict)
    title = name or f"{task.target_horizon} {task.factor_type or task.name} 等值线初稿"
    return ContourDraft(
        name=title,
        target_horizon=task.target_horizon,
        factor_type=task.factor_type,
        linked_factor_task_id=task.id,
        levels=[float(v) for v in use_levels],
        segments=segments,
        source_grid_n=int(task.parameters.get("grid_n") or len(grid_x)),
        source_backend=str(task.parameters.get("interp_backend") or task.method or ""),
        source_value_range=[zmin, zmax],
        status="draft",
        generator_version=GENERATOR_VERSION,
    )


def upsert_contour_draft(project: ProjectDocument, draft: ContourDraft) -> ContourDraft:
    """Replace same-factor/horizon draft or append; stable id when replacing."""
    draft.updated_at = _now_iso()
    for i, existing in enumerate(project.contour_drafts):
        same_task = (
            draft.linked_factor_task_id
            and existing.linked_factor_task_id == draft.linked_factor_task_id
        )
        same_scope = (
            not draft.linked_factor_task_id
            and existing.target_horizon == draft.target_horizon
            and existing.factor_type == draft.factor_type
            and existing.generator_version == GENERATOR_VERSION
        )
        if same_task or same_scope:
            draft = draft.model_copy(update={"id": existing.id})
            draft.updated_at = _now_iso()
            project.contour_drafts[i] = draft
            return draft
    project.contour_drafts.append(draft)
    return draft


def line_features_from_contour_draft(draft: ContourDraft) -> list[dict[str, Any]]:
    """Export isolines as map-edit line_features (role=contour)."""
    features: list[dict[str, Any]] = []
    for seg in draft.segments:
        if len(seg.coordinates) < 2:
            continue
        features.append(
            {
                "id": seg.id,
                "kind": "line",
                "name": f"L={seg.level:g}",
                "role": "contour",
                "coordinates": [list(p) for p in seg.coordinates],
                "properties": {
                    "role": "contour",
                    "constraint_role": "contour",
                    "level": seg.level,
                    "closed": seg.closed,
                    "contour_draft_id": draft.id,
                    "factor_type": draft.factor_type,
                    "target_horizon": draft.target_horizon,
                    **(seg.properties or {}),
                },
            }
        )
    return features


def apply_contour_draft_to_map(
    project: ProjectDocument,
    draft: ContourDraft,
    *,
    map_document: PaleoMapDocument | None = None,
    replace_existing_contours: bool = True,
) -> PaleoMapDocument:
    """Push ContourDraft isolines onto a PaleoMapDocument for mapping edit.

    Creates a map document when none is provided. Contour lines are tagged
    ``role=contour`` so they do not collide with break/direction constraints.
    """
    if map_document is None:
        # Prefer map already linked to this draft.
        if draft.linked_map_document_id:
            map_document = next(
                (
                    d
                    for d in project.paleomap_documents
                    if d.id == draft.linked_map_document_id
                ),
                None,
            )
        if map_document is None:
            map_document = PaleoMapDocument(
                name=f"{draft.target_horizon or '图件'} 等值线",
                linked_target_horizon=draft.target_horizon or "未指定层位",
                linked_contour_draft_id=draft.id,
            )
            project.paleomap_documents.append(map_document)

    lines = list(map_document.line_features or [])
    if replace_existing_contours:
        lines = [
            feat
            for feat in lines
            if not (
                isinstance(feat, dict)
                and (
                    feat.get("role") == "contour"
                    or (feat.get("properties") or {}).get("role") == "contour"
                    or (feat.get("properties") or {}).get("contour_draft_id") == draft.id
                )
            )
        ]
    lines.extend(line_features_from_contour_draft(draft))
    map_document.line_features = lines
    map_document.linked_contour_draft_id = draft.id
    if draft.target_horizon and not map_document.linked_target_horizon:
        map_document.linked_target_horizon = draft.target_horizon

    draft.linked_map_document_id = map_document.id
    draft.status = "editing"
    draft.updated_at = _now_iso()
    upsert_contour_draft(project, draft)
    return map_document


def compile_contour_draft_from_task(
    project: ProjectDocument,
    task: FactorMapTask,
    *,
    levels: Sequence[float] | None = None,
    n_levels: int = DEFAULT_N_LEVELS,
    apply_to_map: bool = True,
    cancellation_token=None,
) -> ContourDraft:
    """End-to-end: task grid → ContourDraft → optional map line_features."""
    draft = contour_draft_from_factor_task(
        task,
        levels=levels,
        n_levels=n_levels,
        cancellation_token=cancellation_token,
    )
    upsert_contour_draft(project, draft)
    if apply_to_map:
        apply_contour_draft_to_map(project, draft)
    return draft


def compile_contour_drafts_for_project(
    project: ProjectDocument,
    *,
    n_levels: int = DEFAULT_N_LEVELS,
    task_ids: Sequence[str] | None = None,
    apply_to_map: bool = True,
    only_complete: bool = True,
    cancellation_token=None,
) -> list[ContourDraft]:
    """Generate ContourDrafts for all (or selected) factor tasks that have grids.

    Skips tasks without ``grid_z``. When *only_complete* is True, requires
    ``status == complete``. Returns drafts created in this call.
    """
    id_filter = set(task_ids) if task_ids is not None else None
    drafts: list[ContourDraft] = []
    for task in project.factor_map_tasks:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if id_filter is not None and task.id not in id_filter:
            continue
        if only_complete and getattr(task, "status", "") != "complete":
            continue
        # Grid may live in parameters, a managed NPZ artifact, or the live cache.
        # Missing grids raise ValueError and are skipped.
        try:
            draft = compile_contour_draft_from_task(
                project,
                task,
                n_levels=n_levels,
                apply_to_map=apply_to_map,
                cancellation_token=cancellation_token,
            )
        except (ValueError, ImportError):
            continue
        drafts.append(draft)
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    return drafts
