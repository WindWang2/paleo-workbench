"""Geological style library (M9).

Reusable, versioned, non-hardcoded geological styles built on the mapping
style authority (:class:`~paleo_workbench.mapping.map_styles.VectorStyle`).
Every entry pairs a style with its **scientific binding** — which field and
which classes it renders — so a style can always be traced back to the data
semantics it visualises (and a legend built from it stays complete).

The library is data, not code paths: entries serialise to a JSON document
(``schema_version``) and can be saved/loaded/extended per project without
touching renderers. Applying an entry to a layer records the binding in the
layer style payload (``style_binding``), keeping style↔science traceability
on the layer itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from paleo_workbench.mapping.map_styles import LinePattern, MarkerSymbol, VectorStyle

__all__ = [
    "STYLE_LIBRARY_SCHEMA_VERSION",
    "StyleEntry",
    "GEOLOGICAL_STYLE_LIBRARY",
    "style_entry",
    "save_style_library",
    "load_style_library",
    "apply_style_to_layer",
]

STYLE_LIBRARY_SCHEMA_VERSION = 1

CATEGORY_WELLS = "well_symbols"
CATEGORY_FACIES = "facies_fills"
CATEGORY_CONTOUR = "contour"
CATEGORY_FAULT = "fault"
CATEGORY_HORIZON = "horizon"
CATEGORY_UNCERTAINTY = "uncertainty"
CATEGORY_BOUNDARY = "boundary"
CATEGORY_REFERENCE = "reference"
CATEGORY_ANNOTATION = "annotation"

CATEGORIES: tuple[str, ...] = (
    CATEGORY_WELLS,
    CATEGORY_FACIES,
    CATEGORY_CONTOUR,
    CATEGORY_FAULT,
    CATEGORY_HORIZON,
    CATEGORY_UNCERTAINTY,
    CATEGORY_BOUNDARY,
    CATEGORY_REFERENCE,
    CATEGORY_ANNOTATION,
)


@dataclass(frozen=True, slots=True)
class StyleEntry:
    """One named style + the scientific binding it visualises."""

    key: str
    category: str
    title: str
    style: VectorStyle
    # Traceability: which field/classes this style renders (e.g. facies_name
    # with the class list of the palette). Renderers never read this; QA and
    # legend construction do.
    binding: dict[str, Any] = field(default_factory=dict)
    legend_label: str = ""
    # Suggested LAYER opacity (the layer owns opacity; the style never does).
    opacity_hint: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "category": self.category,
            "title": self.title,
            "style": self.style.to_dict(),
            "binding": dict(self.binding),
            "legend_label": self.legend_label,
            "opacity_hint": self.opacity_hint,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StyleEntry":
        return cls(
            key=str(data["key"]),
            category=str(data["category"]),
            title=str(data["title"]),
            style=VectorStyle.from_dict(data.get("style")),
            binding=dict(data.get("binding") or {}),
            legend_label=str(data.get("legend_label") or ""),
            opacity_hint=(
                float(data["opacity_hint"])
                if data.get("opacity_hint") is not None
                else None
            ),
        )


# ---------------------------------------------------------------------------
# V1 library
# ---------------------------------------------------------------------------


def _facies_palette() -> list[dict[str, Any]]:
    """The standard V1 沉积相 palette; every class binds to facies_name."""
    classes = (
        ("泥岩", "#9aa7b5"),
        ("砂岩", "#f2d38a"),
        ("河口坝", "#e8b04b"),
        ("浅湖", "#8fc7c2"),
        ("半深湖", "#5f9ea0"),
        ("深湖", "#3d6b8e"),
        ("扇三角洲", "#d9a066"),
        ("冲积扇", "#c47f4e"),
    )
    categories = [
        [name, color, name]  # (value, fill, label) — VectorStyle contract
        for name, color in classes
    ]
    return categories


GEOLOGICAL_STYLE_LIBRARY: dict[str, StyleEntry] = {
    f"{entry.category}.{entry.key}": entry
    for entry in (
        # --- wells -----------------------------------------------------------
        StyleEntry(
            "well_standard", CATEGORY_WELLS, "标准井位",
            VectorStyle(fill="#22b8a7", stroke="#182431", stroke_width=1.0,
                        marker=MarkerSymbol.WELL, marker_size=8.0),
            binding={"class": "well", "field": ""},
            legend_label="井位",
        ),
        StyleEntry(
            "well_fenced", CATEGORY_WELLS, "围栏井位",
            VectorStyle(fill="#e45756", stroke="#3a1a1a", stroke_width=1.2,
                        marker=MarkerSymbol.TRIANGLE, marker_size=9.0),
            binding={"class": "well", "field": "well_type"},
            legend_label="围栏井",
        ),
        # --- facies ----------------------------------------------------------
        StyleEntry(
            "facies_v1", CATEGORY_FACIES, "沉积相标准色板",
            VectorStyle(
                fill="#b0bec5",
                stroke="#26364d",
                stroke_width=1.0,
                renderer="categorized",
                field="facies_name",
                categories=tuple(
                    (value, color, label)
                    for value, color, label in _facies_palette()
                ),
            ),
            binding={
                "field": "facies_name",
                "classes": [value for value, _color, _label in _facies_palette()],
                "source": "geological-style-library-v1/facies_v1",
            },
            legend_label="沉积相",
        ),
        # --- contour ---------------------------------------------------------
        StyleEntry(
            "contour_index", CATEGORY_CONTOUR, "计曲线",
            VectorStyle(stroke="#7a4f21", stroke_width=1.6),
            binding={"class": "contour", "field": "is_index_contour"},
            legend_label="计曲线",
        ),
        StyleEntry(
            "contour_intermediate", CATEGORY_CONTOUR, "首曲线",
            VectorStyle(stroke="#a9763f", stroke_width=0.8),
            binding={"class": "contour", "field": "is_index_contour"},
            legend_label="首曲线",
        ),
        # --- fault -----------------------------------------------------------
        StyleEntry(
            "fault_major", CATEGORY_FAULT, "主干断层",
            VectorStyle(stroke="#c0392b", stroke_width=2.0, line_pattern=LinePattern.DASH),
            binding={"class": "fault", "field": "fault_level"},
            legend_label="主干断层",
        ),
        StyleEntry(
            "fault_secondary", CATEGORY_FAULT, "次级断层",
            VectorStyle(stroke="#e67e22", stroke_width=1.2, line_pattern=LinePattern.DASH_DOT),
            binding={"class": "fault", "field": "fault_level"},
            legend_label="次级断层",
        ),
        # --- horizon ---------------------------------------------------------
        StyleEntry(
            "horizon_top", CATEGORY_HORIZON, "层位顶界",
            VectorStyle(stroke="#2f6fab", stroke_width=1.4),
            binding={"class": "horizon", "field": ""},
            legend_label="层位顶界",
        ),
        # --- uncertainty -------------------------------------------------------
        StyleEntry(
            "uncertainty_band", CATEGORY_UNCERTAINTY, "不确定度分级",
            VectorStyle(
                fill="#808080",
                stroke="#4d4d4d",
                stroke_width=0.6,
                renderer="graduated",
                field="confidence",
                ranges=(
                    (0.0, 0.5, "#c9b8d8", "低置信度 (<0.5)"),
                    (0.5, 0.8, "#8fa8c8", "中等置信度"),
                    (0.8, 1.01, "#7fbf9e", "高置信度"),
                ),
            ),
            binding={
                "field": "confidence",
                "classes": ["低置信度 (<0.5)", "中等置信度", "高置信度"],
                "note": "透明度经图层 opacity 应用，样式色板保持可读",
            },
            legend_label="置信度",
        ),
        # --- boundary --------------------------------------------------------
        StyleEntry(
            "study_boundary", CATEGORY_BOUNDARY, "工区边界",
            VectorStyle(stroke="#34495e", stroke_width=2.2, line_pattern=LinePattern.SOLID),
            binding={"class": "boundary", "field": ""},
            legend_label="工区边界",
        ),
        # --- reference -------------------------------------------------------
        StyleEntry(
            "reference_basemap", CATEGORY_REFERENCE, "参考底图",
            VectorStyle(fill="#f5f2ea", stroke="#b8b0a0", stroke_width=0.6),
            binding={"class": "reference", "field": ""},
            legend_label="参考底图",
            opacity_hint=0.4,
        ),
        # --- annotation ------------------------------------------------------
        StyleEntry(
            "annotation_text", CATEGORY_ANNOTATION, "图面标注",
            VectorStyle(stroke="#2c3e50", stroke_width=0.8),
            binding={"class": "annotation", "field": ""},
            legend_label="标注",
        ),
    )
}


def style_entry(category: str, key: str) -> StyleEntry:
    """Lookup helper; unknown keys raise with the available keys listed."""
    full_key = f"{category}.{key}"
    entry = GEOLOGICAL_STYLE_LIBRARY.get(full_key)
    if entry is None:
        available = sorted(k for k in GEOLOGICAL_STYLE_LIBRARY if k.startswith(category))
        raise KeyError(f"unknown style {full_key!r}; available: {available}")
    return entry


def save_style_library(path: str | Path) -> Path:
    """Serialise the library (or a project-derived copy) as versioned JSON."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": STYLE_LIBRARY_SCHEMA_VERSION,
        "styles": [entry.to_dict() for entry in GEOLOGICAL_STYLE_LIBRARY.values()],
    }
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def load_style_library(path: str | Path) -> dict[str, StyleEntry]:
    """Load a (possibly project-extended) style library document."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = int(data.get("schema_version") or 0)
    if version != STYLE_LIBRARY_SCHEMA_VERSION:
        raise ValueError(
            f"style library schema {version} unsupported; "
            f"expected {STYLE_LIBRARY_SCHEMA_VERSION}"
        )
    entries: dict[str, StyleEntry] = {}
    for raw in data.get("styles") or []:
        entry = StyleEntry.from_dict(raw)
        entries[f"{entry.category}.{entry.key}"] = entry
    return entries


def apply_style_to_layer(layer, entry: StyleEntry) -> None:
    """Apply an entry's style to a layer, recording the binding.

    An explicit ``opacity_hint`` (e.g. reference basemaps) is applied to the
    LAYER (the opacity authority) — the style never mutates scientific
    payloads, and the binding travels with the style payload.
    """
    style_payload = entry.style.to_dict()
    style_payload["style_binding"] = dict(entry.binding)
    layer.style = style_payload
    if entry.opacity_hint is not None and hasattr(layer, "opacity"):
        layer.opacity = min(layer.opacity, float(entry.opacity_hint))
