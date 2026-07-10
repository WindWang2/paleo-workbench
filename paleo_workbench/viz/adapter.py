from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.viz.map_load import load_map_payload_from_document
from paleo_workbench.viz.models import VizPayload, VizRef
from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path
from paleo_workbench.viz.well_log_load import load_well_log_from_path


class VizAdapter:
    """UI-agnostic conversion from project assets to geo-viz payloads."""

    WELL_TYPES = {"well_log"}
    WELL_FORMATS = {"las"}
    SEISMIC_TYPES = {"seismic"}
    SEISMIC_FORMATS = {"sgy", "segy"}

    def supports_resource(self, resource: Any) -> bool:
        if resource is None:
            return False
        rtype = str(getattr(resource, "type", "") or "").strip().lower()
        fmt = str(getattr(resource, "format", "") or "").strip().lower().lstrip(".")
        if rtype in self.WELL_TYPES and fmt in self.WELL_FORMATS:
            return True
        if rtype in self.SEISMIC_TYPES and fmt in self.SEISMIC_FORMATS:
            return True
        return False

    def ref_from_resource(self, resource: Any) -> VizRef | None:
        if not self.supports_resource(resource):
            return None
        rtype = str(getattr(resource, "type", "") or "").strip().lower()
        fmt = str(getattr(resource, "format", "") or "").strip().lower().lstrip(".")
        if rtype in self.WELL_TYPES and fmt in self.WELL_FORMATS:
            kind = "well_log"
        else:
            kind = "seismic"
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

    def resolve(self, ref: VizRef, project: Any) -> VizPayload:
        label = ref.label or ref.id or ref.kind
        try:
            if ref.kind == "well_log":
                return self._resolve_well_log(ref, project, label)
            if ref.kind == "seismic":
                return self._resolve_seismic(ref, project, label)
            if ref.kind == "map":
                return self._resolve_map(ref, project, label)
            if ref.kind == "prediction":
                task = self._find_prediction(ref, project)
                if task is None:
                    return VizPayload(
                        kind="message",
                        label=label,
                        message="未找到对应的预测任务",
                    )
                return self.from_prediction(task)
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

    def from_prediction(self, task: Any) -> VizPayload:
        # Bridge prediction mock converters; keep dual well_log + seismic for UI tabs.
        from paleo_workbench.ui.pages.prediction_helpers import well_log_data_from_prediction
        from paleo_workbench.ui.pages.seismic_prediction_helpers import (
            seismic_volume_from_prediction,
        )

        well_log = well_log_data_from_prediction(task)
        seismic_volume = seismic_volume_from_prediction(task)
        name = str(getattr(task, "name", "") or "") or "prediction"
        return VizPayload(
            kind="prediction",
            label=name,
            well_log=well_log,
            seismic_volume=seismic_volume,
        )

    def _resolve_well_log(self, ref: VizRef, project: Any, label: str) -> VizPayload:
        resource = self._find_resource(ref, project)
        path = (str(getattr(resource, "path", "") or "") if resource is not None else "") or ref.path
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
                message="无法解析 LAS 井数据",
            )
        return VizPayload(
            kind="well_log",
            label=label or str(getattr(data, "well_name", "") or path),
            well_log=data,
        )

    def _resolve_seismic(self, ref: VizRef, project: Any, label: str) -> VizPayload:
        resource = self._find_resource(ref, project)
        path = (str(getattr(resource, "path", "") or "") if resource is not None else "") or ref.path
        if not path or not Path(path).is_file():
            return VizPayload(
                kind="message",
                label=label,
                message="地震数据文件不存在或不可读",
            )
        volume, warning = load_seismic_volume_from_path(path)
        if volume is None:
            return VizPayload(
                kind="message",
                label=label,
                message=warning or "无法加载 SEGY 体数据",
            )
        return VizPayload(
            kind="seismic",
            label=label,
            seismic_volume=volume,
            warning=warning or "",
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

    @staticmethod
    def _find_resource(ref: VizRef, project: Any) -> Any | None:
        resources = getattr(project, "resources", None) or []
        for item in resources:
            if str(getattr(item, "id", "")) == ref.id:
                return item
        # Fallback: match by path when id is empty / stale
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
