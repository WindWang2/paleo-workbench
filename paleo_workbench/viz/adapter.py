from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.viz.map_load import load_map_payload_from_document
from paleo_workbench.viz.models import VizPayload, VizRef
from paleo_workbench.viz.well_log_load import load_well_log_from_path

# Resource type / format → engine-aligned viz kind.
_ENGINE_PREVIEW_TYPES = {
    "horizon": "engine_preview",
    "well_head": "engine_preview",
    "well_stratification": "engine_preview",
    "time_depth": "engine_preview",
    # Alias → same engine semantic as well_stratification
    "formation_tops": "engine_preview",
}


class VizAdapter:
    """Project assets → VizPayload. Parsing/render stay in geo-viz-engine.

    Workbench only maps resource ids/paths and prediction stubs onto engine
    loaders / ``GeoVizEngine.prepare``.
    """

    WELL_TYPES = {"well_log"}
    WELL_FORMATS = {"las", "xml"}
    SEISMIC_TYPES = {"seismic"}
    SEISMIC_FORMATS = {"sgy", "segy"}
    # Formats that go through GeoVizEngine PreviewKind backends.
    ENGINE_FORMATS = {
        "dat",
        "txt",
        "csv",
        "sgy",
        "segy",
        "las",
        "xml",
    }

    def supports_resource(self, resource: Any) -> bool:
        if resource is None:
            return False
        rtype = str(getattr(resource, "type", "") or "").strip().lower()
        fmt = str(getattr(resource, "format", "") or "").strip().lower().lstrip(".")
        if rtype in self.WELL_TYPES and fmt in self.WELL_FORMATS:
            return True
        if rtype in self.SEISMIC_TYPES and fmt in self.SEISMIC_FORMATS:
            return True
        if rtype in _ENGINE_PREVIEW_TYPES:
            return True
        # SEGY also openable as 2D engine preview (slice scrub) when type is seismic —
        # primary path is full SeismicView; engine_preview is optional.
        return False

    def ref_from_resource(self, resource: Any) -> VizRef | None:
        if not self.supports_resource(resource):
            return None
        rtype = str(getattr(resource, "type", "") or "").strip().lower()
        fmt = str(getattr(resource, "format", "") or "").strip().lower().lstrip(".")
        if rtype in self.WELL_TYPES and fmt in self.WELL_FORMATS:
            kind: str = "well_log"
        elif rtype in self.SEISMIC_TYPES and fmt in self.SEISMIC_FORMATS:
            kind = "seismic"
        elif rtype in _ENGINE_PREVIEW_TYPES:
            kind = "engine_preview"
        else:
            return None
        return VizRef(
            kind=kind,  # type: ignore[arg-type]
            id=str(getattr(resource, "id", "") or ""),
            path=str(getattr(resource, "path", "") or ""),
            label=str(getattr(resource, "name", "") or ""),
            source="",
        )

    def ref_from_map_document(self, doc: Any) -> VizRef:
        return VizRef(
            kind="map",
            id=str(getattr(doc, "id", "") or ""),
            path="",
            label=str(getattr(doc, "name", "") or ""),
            source="",
        )

    def ref_from_prediction(self, task: Any) -> VizRef:
        return VizRef(
            kind="prediction",
            id=str(getattr(task, "id", "") or ""),
            path="",
            label=str(getattr(task, "name", "") or ""),
            source="prediction",
        )

    def resolve(self, ref: VizRef, project: Any) -> VizPayload:
        label = ref.label or ref.id or ref.kind
        try:
            if ref.kind == "well_log":
                return self._resolve_well_log(ref, project, label)
            if ref.kind == "seismic":
                return self._resolve_seismic(ref, project, label)
            if ref.kind == "map":
                return self._resolve_map(ref, project, label)
            if ref.kind == "cross_well":
                return self._resolve_cross_well(ref, project, label)
            if ref.kind == "engine_preview":
                return self._resolve_engine_preview(ref, project, label)
            if ref.kind == "prediction":
                task = self._find_prediction(ref, project)
                if task is None:
                    return VizPayload(
                        kind="message",
                        label=label,
                        message="未找到对应的预测任务",
                    )
                return self.from_prediction(task, project)
            return VizPayload(
                kind="message",
                label=label,
                message=f"不支持的可视化类型: {ref.kind}",
            )
        except Exception as exc:
            return VizPayload(
                kind="message",
                label=label,
                message=f"解析失败: {exc.__class__.__name__}",
            )

    def from_prediction(self, task: Any, project: Any = None) -> VizPayload:
        # Soft-fail like resolve(): never raise into UI handlers.
        name = str(getattr(task, "name", "") or "") or "prediction"
        try:
            from paleo_workbench.viz.prediction_helpers import (
                well_log_data_from_prediction,
            )
            from paleo_workbench.viz.seismic_prediction_helpers import (
                seismic_volume_from_prediction,
            )

            well_log = well_log_data_from_prediction(task)
            seismic_volume = seismic_volume_from_prediction(task)
            
            seismic_path = ""
            if project is not None:
                from paleo_workbench.pipeline.assets import SEISMIC_KEY
                ids = (getattr(task, "input_refs", None) or {}).get(SEISMIC_KEY) or []
                if ids:
                    by_id = {r.id: r for r in (getattr(project, "resources", None) or [])}
                    res = by_id.get(ids[0])
                    if res is not None:
                        path = getattr(res, "path", "") or ""
                        seismic_path = self._absolute_path(path, project) if path else ""

            return VizPayload(
                kind="prediction",
                label=name,
                well_log=well_log,
                well_logs=[well_log] if well_log is not None else [],
                well_names=[name],
                seismic_volume=seismic_volume,
                seismic_path=seismic_path,
            )
        except Exception as exc:
            return VizPayload(
                kind="message",
                label=name,
                message=f"预测可视化失败: {exc.__class__.__name__}",
            )

    @staticmethod
    def _absolute_path(path: str, project: Any) -> str:
        """Resolve project-relative resource paths using meta.project_root when needed.

        Relative joins are confined to ``project_root`` (no ``..`` escape).
        """
        from paleo_workbench.project.paths import is_within_directory

        candidate = Path(path).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        if candidate.is_absolute():
            return str(candidate)
        root = str(getattr(getattr(project, "meta", None), "project_root", "") or "").strip()
        if root and root not in {".", ".."}:
            root_path = Path(root).expanduser().resolve()
            joined = (root_path / candidate).resolve()
            if not is_within_directory(joined, root_path):
                # Escape attempt — do not open files outside the project root.
                return str(candidate)
            if joined.is_file():
                return str(joined)
            return str(joined)
        return str(candidate)

    def _resolve_well_log(self, ref: VizRef, project: Any, label: str) -> VizPayload:
        resource = self._find_resource(ref, project)
        path = (str(getattr(resource, "path", "") or "") if resource is not None else "") or ref.path
        path = self._absolute_path(path, project) if path else ""
        if not path or not Path(path).is_file():
            return VizPayload(
                kind="message",
                label=label,
                message="井数据文件不存在或不可读",
            )
        data = load_well_log_from_path(path)
        if data is None:
            return VizPayload(
                kind="message",
                label=label,
                message="无法解析 LAS 井数据（engine load_las_preview）",
            )
        return VizPayload(
            kind="well_log",
            label=label or str(getattr(data, "well_name", "") or path),
            well_log=data,
            well_logs=[data],
            well_names=[str(getattr(data, "well_name", "") or label or Path(path).stem)],
        )

    def _resolve_seismic(self, ref: VizRef, project: Any, label: str) -> VizPayload:
        resource = self._find_resource(ref, project)
        path = (str(getattr(resource, "path", "") or "") if resource is not None else "") or ref.path
        path = self._absolute_path(path, project) if path else ""
        if not path or not Path(path).is_file():
            return VizPayload(
                kind="message",
                label=label,
                message="地震数据文件不存在或不可读",
            )
        # Do not parse SEGY on the caller/GUI thread.  The engine view owns
        # budgeted background preparation and latest-generation commit.
        return VizPayload(
            kind="seismic",
            label=label,
            seismic_path=path,
            seismic_volume=None,
            warning="SEGY 将在后台按体素预算加载",
            message="",
        )

    def _resolve_map(self, ref: VizRef, project: Any, label: str) -> VizPayload:
        doc = self._find_map_document(ref, project)
        if doc is None:
            return VizPayload(
                kind="message",
                label=label,
                message="未找到对应的古地理图文档",
            )
        features, wells, period = load_map_payload_from_document(doc)
        if not features and not wells:
            return VizPayload(
                kind="map",
                label=label or str(getattr(doc, "name", "") or ""),
                map_features=features or [],
                map_wells=wells or [],
                period_name=period or "",
                message="地图文档无可用几何",
                warning="无相多边形或井位可显示",
            )
        return VizPayload(
            kind="map",
            label=label or str(getattr(doc, "name", "") or ""),
            map_features=features,
            map_wells=wells,
            period_name=period or "",
        )

    def _resolve_cross_well(self, ref: VizRef, project: Any, label: str) -> VizPayload:
        ids = list(ref.related_ids) if ref.related_ids else []
        if ref.id and ref.id not in ids:
            ids.insert(0, ref.id)
        resources = getattr(project, "resources", None) or []
        by_id = {str(getattr(r, "id", "")): r for r in resources}
        logs: list[Any] = []
        names: list[str] = []
        for rid in ids:
            res = by_id.get(rid)
            if res is None:
                continue
            path = str(getattr(res, "path", "") or "")
            data = load_well_log_from_path(path) if path else None
            if data is None:
                continue
            logs.append(data)
            names.append(str(getattr(res, "name", "") or getattr(data, "well_name", "") or rid))
        if not logs:
            # Fall back: all well_log resources in project (capped).
            for res in resources:
                if str(getattr(res, "type", "")).lower() != "well_log":
                    continue
                path = str(getattr(res, "path", "") or "")
                data = load_well_log_from_path(path) if path else None
                if data is None:
                    continue
                logs.append(data)
                names.append(str(getattr(res, "name", "") or path))
                if len(logs) >= 8:
                    break
        if not logs:
            return VizPayload(kind="message", label=label, message="无可用测井数据构建连井")
        return VizPayload(
            kind="cross_well",
            label=label,
            well_log=logs[0],
            well_logs=logs,
            well_names=names,
        )

    def _resolve_engine_preview(self, ref: VizRef, project: Any, label: str) -> VizPayload:
        resource = self._find_resource(ref, project)
        path = (str(getattr(resource, "path", "") or "") if resource is not None else "") or ref.path
        path = self._absolute_path(path, project) if path else ""
        if not path or not Path(path).is_file():
            return VizPayload(
                kind="message",
                label=label,
                message="预览文件不存在或不可读",
            )
        try:
            from geoviz import GeoVizEngine, PreviewOptions, PreviewRequest
        except Exception:
            return VizPayload(
                kind="message",
                label=label,
                message="geo-viz-engine 不可用",
            )
        rtype = str(getattr(resource, "type", "") or "") if resource is not None else ""
        # Engine WellStratificationBackend expects well_stratification, not formation_tops.
        if rtype == "formation_tops":
            rtype = "well_stratification"
        fmt = str(getattr(resource, "format", "") or Path(path).suffix).lstrip(".")
        request = PreviewRequest(
            resource_id=ref.id or "viz",
            path=path,
            semantic_type=rtype or "unknown",
            format=fmt,
            label=label,
        )
        engine = GeoVizEngine.default()
        if not engine.supports(request):
            return VizPayload(
                kind="message",
                label=label,
                message=f"引擎不支持此资源类型: {rtype}/{fmt}",
            )
        try:
            prepared = engine.prepare(request, PreviewOptions.local())
        except Exception as exc:
            return VizPayload(
                kind="message",
                label=label,
                message=f"引擎 prepare 失败: {exc.__class__.__name__}",
            )
        return VizPayload(
            kind="engine_preview",
            label=label,
            prepared=prepared,
            warning=getattr(prepared, "warning", "") or "",
        )

    @staticmethod
    def _find_resource(ref: VizRef, project: Any) -> Any | None:
        resources = getattr(project, "resources", None) or []
        for item in resources:
            if str(getattr(item, "id", "")) == ref.id:
                return item
        if ref.path:
            for item in resources:
                if str(getattr(item, "path", "")) == ref.path:
                    return item
        return None

    @staticmethod
    def _find_map_document(ref: VizRef, project: Any) -> Any | None:
        docs = getattr(project, "paleomap_documents", None) or []
        for doc in docs:
            if str(getattr(doc, "id", "")) == ref.id:
                return doc
        if ref.label:
            for doc in docs:
                if str(getattr(doc, "name", "")) == ref.label:
                    return doc
        return None

    @staticmethod
    def _find_prediction(ref: VizRef, project: Any) -> Any | None:
        tasks = getattr(project, "prediction_tasks", None) or []
        for task in tasks:
            if str(getattr(task, "id", "")) == ref.id:
                return task
        return None
