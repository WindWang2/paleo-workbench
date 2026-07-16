from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paleo_workbench.adapters.schemas import ExportRequest, ExportResult, ViewerPayload, ViewState


class PaleoMapAdapter:
    adapter_name = "paleo_map"

    def __init__(self):
        self._payload = ViewerPayload(viewer_type="paleo_map")
        self._state = ViewState()

    def set_data(self, payload: ViewerPayload | dict) -> None:
        parsed = payload if isinstance(payload, ViewerPayload) else ViewerPayload.model_validate(payload)
        if parsed.viewer_type != "paleo_map":
            raise ValueError(f"PaleoMapAdapter cannot render {parsed.viewer_type}")
        self._payload = parsed

    def set_view_state(self, state: ViewState | dict) -> None:
        self._state = state if isinstance(state, ViewState) else ViewState.model_validate(state)

    def get_view_state(self) -> ViewState:
        return self._state

    def export(self, request: ExportRequest | dict) -> ExportResult:
        parsed = request if isinstance(request, ExportRequest) else ExportRequest.model_validate(request)
        output = Path(parsed.path)
        output.parent.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        if parsed.format == "geojson":
            features = self._layers_to_geojson_features(parsed.selected_layers)
            collection = {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": self._payload.crs}},
                "features": features,
            }
            output.write_text(
                json.dumps(collection, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not features:
                warnings.append("no layers to export; wrote empty FeatureCollection")
        else:
            # Vector/raster map rendering is not yet wired through this adapter.
            output.write_text(
                f"minimal {parsed.format} export from {self.adapter_name}\n",
                encoding="utf-8",
            )
            warnings.append(
                f"{parsed.format} export is a placeholder; use geojson for geometry"
            )
        return ExportResult(
            output_path=output.as_posix(),
            format=parsed.format,
            byte_size=output.stat().st_size,
            warnings=warnings,
            artifact_metadata={
                "adapter": self.adapter_name,
                "layer_count": len(self._payload.layers),
                "feature_count": len(self._layers_to_geojson_features(parsed.selected_layers))
                if parsed.format == "geojson"
                else 0,
            },
        )

    def clear(self) -> None:
        self._payload = ViewerPayload(viewer_type="paleo_map")
        self._state = ViewState()

    def _layers_to_geojson_features(
        self, selected_layers: list[str] | None = None
    ) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []
        selected = set(selected_layers or [])
        for layer in self._payload.layers:
            layer_id = str(layer.get("id") or layer.get("name") or "")
            if selected and layer_id not in selected and layer.get("name") not in selected:
                continue
            layer_features = layer.get("features")
            if isinstance(layer_features, list):
                for feat in layer_features:
                    converted = self._coerce_feature(feat, layer)
                    if converted is not None:
                        features.append(converted)
                continue
            # Layer itself may be a geometry-bearing record.
            converted = self._coerce_feature(layer, layer)
            if converted is not None:
                features.append(converted)
        return features

    @staticmethod
    def _coerce_feature(feat: Any, layer: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(feat, dict):
            return None
        # Already GeoJSON Feature
        if feat.get("type") == "Feature" and isinstance(feat.get("geometry"), dict):
            return feat
        geometry = feat.get("geometry")
        if isinstance(geometry, dict) and geometry.get("type") and "coordinates" in geometry:
            props = dict(feat.get("properties") or {})
            if "id" in feat and "id" not in props:
                props["id"] = feat["id"]
            if "name" in feat and "name" not in props:
                props["name"] = feat["name"]
            props.setdefault("layer", layer.get("name") or layer.get("id"))
            return {
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            }
        coords = feat.get("coordinates")
        if not isinstance(coords, list) or not coords:
            return None
        # Point: [x, y]
        if len(coords) >= 2 and isinstance(coords[0], (int, float)):
            geom_type = "Point"
            geom_coords: Any = [float(coords[0]), float(coords[1])]
        else:
            # Ring / line of [x, y]
            ring = []
            for pt in coords:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    ring.append([float(pt[0]), float(pt[1])])
            if len(ring) < 2:
                return None
            closed = (
                len(ring) >= 4
                and ring[0][0] == ring[-1][0]
                and ring[0][1] == ring[-1][1]
            )
            if closed:
                geom_type = "Polygon"
                geom_coords = [ring]
            else:
                geom_type = "LineString"
                geom_coords = ring
        props = dict(feat.get("properties") or {})
        for key in ("id", "name", "facies", "probability", "region_id"):
            if key in feat and key not in props:
                props[key] = feat[key]
        props.setdefault("layer", layer.get("name") or layer.get("id"))
        return {
            "type": "Feature",
            "geometry": {"type": geom_type, "coordinates": geom_coords},
            "properties": props,
        }
