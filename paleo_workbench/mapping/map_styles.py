"""Unified cartographic style and symbol definitions for map rendering.

Styles are pure data (no Qt imports) so the authoring document, the render
snapshot seam, persistence, and both render backends share one vocabulary.
``VectorStyle.to_dict`` keeps the established flat dict keys (``fill``,
``stroke``, ``stroke_width``, ``marker_size``, ``labels``) and only adds new
ones, so persisted projects and the QGIS bridge payload stay compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "LinePattern",
    "MarkerSymbol",
    "TextStyle",
    "VectorStyle",
    "STYLE_LIBRARY",
    "default_style_for",
    "load_style_library",
    "save_style_library",
    "style_dict_revision",
]


class LinePattern(str, Enum):
    """Named cartographic line patterns for geological map features."""

    SOLID = "solid"
    DASH = "dash"
    DOT = "dot"
    DASH_DOT = "dash_dot"
    # 断层线: the classic long-dash fault trace used on paleogeographic maps.
    FAULT = "fault"
    # 地层界线: solid with a heavier weight is expressed via stroke_width;
    # the pattern itself is solid, listed for symbol-library completeness.
    BOUNDARY = "boundary"

    def dash_pattern(self, width: float) -> tuple[float, ...]:
        """Qt dash units (multiples of pen width) for this pattern."""
        if self is LinePattern.DASH:
            return (4.0, 2.0)
        if self is LinePattern.DOT:
            return (1.0, 2.0)
        if self is LinePattern.DASH_DOT:
            return (4.0, 2.0, 1.0, 2.0)
        if self is LinePattern.FAULT:
            return (6.0, 2.0)
        return ()


class MarkerSymbol(str, Enum):
    """Point symbol vocabulary including standard well markers."""

    CIRCLE = "circle"
    SQUARE = "square"
    TRIANGLE = "triangle"
    DIAMOND = "diamond"
    CROSS = "cross"
    STAR = "star"
    # 井符号: ring with a centre dot, the standard well location mark.
    WELL = "well"


@dataclass(frozen=True, slots=True)
class TextStyle:
    """Label placement style consumed by labeling-capable backends."""

    field: str = ""
    size: float = 9.0
    color: str = "#f8f9fa"
    font_family: str = ""
    bold: bool = False
    halo_color: str = "#182431"
    halo_width: float = 1.0
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "size": self.size,
            "color": self.color,
            "font_family": self.font_family,
            "bold": self.bold,
            "halo_color": self.halo_color,
            "halo_width": self.halo_width,
            "visible": self.visible,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "TextStyle":
        if not isinstance(data, Mapping):
            return cls()
        values = dict(data)
        style = cls()
        replacements: dict[str, Any] = {}
        for key in ("field", "color", "font_family", "halo_color"):
            if values.get(key) is not None:
                replacements[key] = str(values[key])
        for key in ("size", "halo_width"):
            if values.get(key) is not None:
                try:
                    replacements[key] = float(values[key])
                except (TypeError, ValueError):
                    continue
        if values.get("bold") is not None:
            replacements["bold"] = bool(values["bold"])
        if values.get("visible") is not None:
            replacements["visible"] = bool(values["visible"])
        return replace(style, **replacements) if replacements else style


@dataclass(frozen=True, slots=True)
class VectorStyle:
    """One layer-level vector style with per-feature renderer settings.

    Stroke width, marker size and label size are logical pixels at 96 dpi;
    renderers scale them by ``dpi / 96`` so screen and export stay identical.
    """

    fill: str = "#6c8ebf"
    stroke: str = "#26364d"
    stroke_width: float = 1.0
    line_pattern: LinePattern = LinePattern.SOLID
    marker: MarkerSymbol = MarkerSymbol.CIRCLE
    marker_size: float = 6.0
    # Renderer classification (currently honoured by the QGIS backend; kept
    # here so one schema describes both backends).
    renderer: str = "single"
    field: str = ""
    categories: tuple[tuple[str, str, str], ...] = ()  # (value, fill, label)
    ranges: tuple[tuple[float, float, str, str], ...] = ()  # (lo, hi, fill, label)
    labels: TextStyle | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "fill": self.fill,
            "stroke": self.stroke,
            "stroke_width": self.stroke_width,
            "line_pattern": self.line_pattern.value,
            "marker": self.marker.value,
            "marker_size": self.marker_size,
            "renderer": self.renderer,
            "field": self.field,
        }
        if self.categories:
            data["categories"] = [list(entry) for entry in self.categories]
        if self.ranges:
            data["ranges"] = [list(entry) for entry in self.ranges]
        if self.labels is not None:
            data["labels"] = self.labels.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "VectorStyle":
        """Parse persisted/host style dicts tolerantly (unknown keys ignored)."""
        if not isinstance(data, Mapping):
            return cls()
        values = dict(data)
        replacements: dict[str, Any] = {}
        for key in ("fill", "stroke"):
            if values.get(key):
                replacements[key] = str(values[key])
        for key in ("stroke_width", "marker_size"):
            if values.get(key) is not None:
                try:
                    replacements[key] = max(0.0, float(values[key]))
                except (TypeError, ValueError):
                    continue
        if values.get("line_pattern"):
            try:
                replacements["line_pattern"] = LinePattern(str(values["line_pattern"]))
            except ValueError:
                pass
        if values.get("marker"):
            try:
                replacements["marker"] = MarkerSymbol(str(values["marker"]))
            except ValueError:
                pass
        for key in ("renderer", "field"):
            if values.get(key) is not None:
                replacements[key] = str(values[key])
        categories: list[tuple[str, str, str]] = []
        raw_categories = values.get("categories")
        if isinstance(raw_categories, Mapping):
            # Established QGIS payload form: {"value": "#color"}.
            categories.extend(
                (str(key), str(color), "") for key, color in raw_categories.items()
            )
        for entry in raw_categories if isinstance(raw_categories, (list, tuple)) else ():
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                categories.append((str(entry[0]), str(entry[1]), str(entry[2]) if len(entry) > 2 else ""))
        if categories:
            replacements["categories"] = tuple(categories)
        ranges: list[tuple[float, float, str, str]] = []
        for entry in values.get("ranges") or ():
            if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                try:
                    ranges.append(
                        (
                            float(entry[0]),
                            float(entry[1]),
                            str(entry[2]),
                            str(entry[3]) if len(entry) > 3 else "",
                        )
                    )
                except (TypeError, ValueError):
                    continue
        if ranges:
            replacements["ranges"] = tuple(ranges)
        if values.get("labels") is not None:
            replacements["labels"] = TextStyle.from_dict(values.get("labels"))
        return cls(**replacements) if replacements else cls()


# 断层/等值线/地层界线/井符号/注记/相带 named presets. Values intentionally
# match the previously hard-coded defaults so existing projects look unchanged.
STYLE_LIBRARY: dict[str, VectorStyle] = {
    "facies": VectorStyle(
        fill="#6c8ebf", stroke="#26364d", stroke_width=1.0,
    ),
    "well": VectorStyle(
        fill="#22b8a7", stroke="#182431", marker=MarkerSymbol.WELL, marker_size=7.0,
    ),
    "contour": VectorStyle(
        fill="transparent", stroke="#f08c46", stroke_width=1.0,
        labels=TextStyle(field="", size=8.0, color="#ffd8a8"),
    ),
    "formation_boundary": VectorStyle(
        fill="transparent", stroke="#e8590c", stroke_width=2.0, line_pattern=LinePattern.SOLID,
    ),
    "fault": VectorStyle(
        fill="transparent", stroke="#e03131", stroke_width=2.0, line_pattern=LinePattern.FAULT,
    ),
    "line": VectorStyle(
        fill="transparent", stroke="#f08c46", stroke_width=2.0,
    ),
    "annotation": VectorStyle(
        fill="#eff3f8", stroke="#182431", marker=MarkerSymbol.CIRCLE, marker_size=4.0,
        labels=TextStyle(field="text", size=10.0, color="#f8f9fa"),
    ),
    "label": VectorStyle(
        fill="#eff3f8", stroke="#182431", marker=MarkerSymbol.CIRCLE, marker_size=4.0,
    ),
}

_STYLE_FOR_KIND = {"facies": "facies", "well": "well", "line": "line", "label": "label"}


def default_style_for(kind: str) -> VectorStyle:
    """Return the symbol-library preset for a compatibility layer kind."""
    return STYLE_LIBRARY[_STYLE_FOR_KIND.get(str(kind), "facies")]


def save_style_library(path: Path | str, *, styles: Mapping[str, VectorStyle] | None = None) -> None:
    """Persist named styles as a JSON file for reuse across documents."""
    payload = {
        "schema_version": 1,
        "styles": {
            name: style.to_dict() for name, style in (styles or STYLE_LIBRARY).items()
        },
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_style_library(path: Path | str) -> dict[str, VectorStyle]:
    """Load a previously saved style library; unknown entries are ignored."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    styles: dict[str, VectorStyle] = {}
    for name, entry in (data.get("styles") or {}).items():
        if isinstance(entry, Mapping):
            styles[str(name)] = VectorStyle.from_dict(entry)
    return styles


def style_dict_revision(style: Mapping[str, Any] | None) -> int:
    """Cheap stable revision for a style dict.

    Uses recursive tuple conversion (C-speed for str/float/tuple) instead of a
    JSON round-trip; style dicts are small so this stays well under a
    microsecond while remaining content-stable.
    """
    def freeze(value: Any) -> Any:
        if isinstance(value, Mapping):
            return tuple(sorted((str(key), freeze(item)) for key, item in value.items()))
        if isinstance(value, (list, tuple)):
            return tuple(freeze(item) for item in value)
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float, str)):
            return value
        return str(value)

    return hash(freeze(style or {}))
