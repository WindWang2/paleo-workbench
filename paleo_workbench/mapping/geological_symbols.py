"""Geological symbols V2 (qgis-geolayer-cartography-v7 §6).

The §6 professional symbol vocabulary: versioned, role-checked symbol
definitions for faults, facies, provenance and boundaries.  Pure data —
no Qt, no QGIS, no bridge import — so the library validates in every
environment and serialises to a versioned JSON document.

Authority split (audit-mapping §4.1):

* ``legacy_fallback`` is a flat :class:`VectorStyle` — the compat/fallback
  vocabulary the QPainter canvas and the SVG renderers understand.
* ``renderer_hint`` describes the professional QGIS renderer (kind, field,
  per-class rules, confidence gradations) that the bridge realises as
  renderer XML when it is built; until then the hint is data-only.

Every entry is role-checked: :func:`validate_binding` refuses to bind,
e.g., a fault symbol to a shoreline layer, and the entries cover exactly
the ``RendererBinding.style_id`` vocabulary declared by
``mapping_workspace/geological_layer_spec.py`` (``fault_v2``,
``provenance_direction_v1``, ...; older spec ids resolve through
:data:`SYMBOL_ALIASES`).

Coexistence with :mod:`.geological_style_library`: the V1 library keeps its
12 entries untouched; :func:`register_symbols_into_style_library` registers
V2 symbols into it on demand (explicit, idempotent, reversible).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from paleo_workbench.mapping.facies_patterns import pattern_id_for_facies
from paleo_workbench.mapping.geological_style_library import (
    CATEGORY_BOUNDARY,
    CATEGORY_FACIES,
    CATEGORY_FAULT,
    GEOLOGICAL_STYLE_LIBRARY,
    StyleEntry,
    apply_style_to_layer,
)
from paleo_workbench.mapping.map_styles import (
    LinePattern,
    MarkerSymbol,
    TextStyle,
    VectorStyle,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole

__all__ = [
    "SYMBOL_LIBRARY_SCHEMA_VERSION",
    "GeologicalSymbolDef",
    "GEOLOGICAL_SYMBOLS",
    "SYMBOL_ALIASES",
    "SYMBOL_CATEGORIES",
    "apply_symbol_to_layer",
    "binding_record",
    "canonical_symbol_id",
    "legacy_style_for_symbol",
    "library_from_dict",
    "library_to_dict",
    "library_version",
    "load_symbol_library",
    "register_symbols_into_style_library",
    "save_symbol_library",
    "style_entry_for_symbol",
    "symbol_by_id",
    "symbols_for_role",
    "unregister_symbols_from_style_library",
    "validate_binding",
]

#: Whole-library schema/semantic version (one per §6 revision).
SYMBOL_LIBRARY_SCHEMA_VERSION = 2

CATEGORY_SYMBOL_FAULT = "fault"
CATEGORY_SYMBOL_FACIES = "facies"
CATEGORY_SYMBOL_PROVENANCE = "provenance"
CATEGORY_SYMBOL_BOUNDARY = "boundary"

SYMBOL_CATEGORIES: tuple[str, ...] = (
    CATEGORY_SYMBOL_FAULT,
    CATEGORY_SYMBOL_FACIES,
    CATEGORY_SYMBOL_PROVENANCE,
    CATEGORY_SYMBOL_BOUNDARY,
)

#: Registration into the V1 style library maps V2 categories onto the
#: established V1 category strings where they exist; provenance is new.
_LEGACY_CATEGORY: dict[str, str] = {
    CATEGORY_SYMBOL_FAULT: CATEGORY_FAULT,
    CATEGORY_SYMBOL_FACIES: CATEGORY_FACIES,
    CATEGORY_SYMBOL_BOUNDARY: CATEGORY_BOUNDARY,
    CATEGORY_SYMBOL_PROVENANCE: "provenance",
}

_RENDERER_KINDS = frozenset({"single", "categorized", "graduated"})
_GEOMETRY_KINDS = frozenset({"point", "line", "polygon"})

#: Runtime ``LayerType`` "vector" is a generic carrier (the spec's
#: geometry_kind is authoritative); these sets define what a symbol accepts.
_COMPATIBLE_GEOMETRY: dict[str, frozenset[str]] = {
    "point": frozenset({"point", "vector"}),
    "line": frozenset({"line", "vector", "polyline", "multiline"}),
    "polygon": frozenset({"polygon", "vector", "multipolygon"}),
}

#: Spec ids from before the V2 split resolve to their V2 successor.
SYMBOL_ALIASES: dict[str, str] = {
    "facies_v1": "facies_v2",
    "shoreline_v1": "shoreline_v2",
    "facies_boundary_v1": "facies_boundary_v2",
    "interpolation_boundary_v1": "interpolation_boundary_v2",
}


# ---------------------------------------------------------------------------
# Symbol definition


@dataclass(frozen=True, slots=True)
class GeologicalSymbolDef:
    """One versioned §6 symbol: fallback style + renderer hint + role set.

    ``legacy_fallback`` is what the fallback renderer paints today (flat
    ``VectorStyle``); ``renderer_hint`` describes the professional QGIS
    renderer (``renderer_kind``/``field``/``rules``, plus fault confidence
    gradations) realised through renderer XML later.  ``metadata`` carries
    declaration-only extras (legend grouping, hatch parameters, arrow
    decorations) consumed by legend/composer construction.
    """

    symbol_id: str
    version: int
    title: str
    category: str
    applicable_roles: frozenset[LayerRole]
    geometry_kind: str
    legacy_fallback: VectorStyle
    renderer_hint: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.category not in SYMBOL_CATEGORIES:
            raise ValueError(
                f"symbol {self.symbol_id!r}: unknown category {self.category!r}; "
                f"expected one of {SYMBOL_CATEGORIES}")
        if self.geometry_kind not in _GEOMETRY_KINDS:
            raise ValueError(
                f"symbol {self.symbol_id!r}: unknown geometry_kind "
                f"{self.geometry_kind!r}; expected one of {sorted(_GEOMETRY_KINDS)}")
        kind = str(self.renderer_hint.get("renderer_kind", "single"))
        if kind not in _RENDERER_KINDS:
            raise ValueError(
                f"symbol {self.symbol_id!r}: unknown renderer_kind {kind!r}; "
                f"expected one of {sorted(_RENDERER_KINDS)}")
        if int(self.version) < 1:
            raise ValueError(f"symbol {self.symbol_id!r}: version must be >= 1")

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "version": int(self.version),
            "title": self.title,
            "category": self.category,
            "applicable_roles": sorted(role.value for role in self.applicable_roles),
            "geometry_kind": self.geometry_kind,
            "legacy_fallback": self.legacy_fallback.to_dict(),
            "renderer_hint": _plain(self.renderer_hint),
            "metadata": _plain(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GeologicalSymbolDef":
        return cls(
            symbol_id=str(data["symbol_id"]),
            version=int(data["version"]),
            title=str(data["title"]),
            category=str(data["category"]),
            applicable_roles=frozenset(
                LayerRole(value) for value in data.get("applicable_roles", ())
            ),
            geometry_kind=str(data["geometry_kind"]),
            legacy_fallback=VectorStyle.from_dict(data.get("legacy_fallback")),
            renderer_hint=dict(data.get("renderer_hint") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    # -- V1 integration ------------------------------------------------------

    def style_entry(self) -> StyleEntry:
        """The V1 :class:`StyleEntry` projection used for registration/apply."""
        return StyleEntry(
            key=self.symbol_id,
            category=_LEGACY_CATEGORY[self.category],
            title=self.title,
            style=self.legacy_fallback,
            binding=binding_record(self.symbol_id),
            legend_label=str(self.metadata.get("legend_label") or self.title),
            opacity_hint=(
                float(self.metadata["opacity_hint"])
                if self.metadata.get("opacity_hint") is not None
                else None
            ),
        )


def _plain(value: Any) -> Any:
    """JSON-safe deep copy (tuples→lists, frozensets→sorted lists)."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# §6 vocabulary

#: Fault confidence gradations (shared by every fault symbol): the spec's
#: ``confidence`` field (inferred/interpreted/verified) maps to data-defined
#: stroke weight and alpha in the renderer XML; "inferred" additionally
#: drops the classic fault long-dash to a plain dash so uncertainty reads
#: on grayscale printouts where alpha is lost.
FAULT_CONFIDENCE_LEVELS: dict[str, dict[str, Any]] = {
    "inferred": {
        "line_pattern": LinePattern.DASH.value,
        "stroke_width": 0.8,
        "stroke_alpha": 0.55,
    },
    "interpreted": {
        "line_pattern": LinePattern.FAULT.value,
        "stroke_width": 1.6,
        "stroke_alpha": 0.85,
    },
    "verified": {
        "line_pattern": LinePattern.FAULT.value,
        "stroke_width": 2.2,
        "stroke_alpha": 1.0,
    },
}

_FAULT_CLASSES: tuple[tuple[str, str, str, float], ...] = (
    # (fault_type value, stroke, label, stroke_width)
    ("normal", "#c0392b", "正断层", 1.6),
    ("reverse", "#a93226", "逆断层", 1.6),
    ("thrust", "#7b241c", "冲断断层", 2.0),
    ("strike_slip", "#d35400", "走滑断层", 1.4),
    ("unclassified", "#95a5a6", "未分类断层", 1.2),
)

_FACIES_CLASSES: tuple[tuple[str, str, str], ...] = (
    # (facies_name value, printable fill, label) — domain order matches
    # geological_layer_spec._FACIES_CLASS_FIELD.choices exactly.
    ("alluvial_fan", "#c47f4e", "冲积扇"),
    ("fluvial", "#e8c46b", "河流"),
    ("lacustrine", "#8fc7c2", "湖泊"),
    ("delta", "#d9a066", "三角洲"),
    ("shoreline", "#eae2b0", "岸线带"),
    ("shallow_marine", "#6fb3b8", "浅海"),
    ("deep_marine", "#3d6b8e", "深海"),
    ("volcanic", "#9b6b9e", "火山岩"),
    ("other", "#b0bec5", "其他"),
)

_FACIES_LEGEND_GROUPS: tuple[dict[str, Any], ...] = (
    {"label": "陆相 (Continental)", "classes": ["alluvial_fan", "fluvial", "lacustrine"]},
    {"label": "过渡相 (Transitional)", "classes": ["delta", "shoreline"]},
    {"label": "海相 (Marine)", "classes": ["shallow_marine", "deep_marine"]},
    {"label": "其他 (Other)", "classes": ["volcanic", "other"]},
)

_FACIES_HATCH_ANGLES: dict[str, float] = {
    "alluvial_fan": 45.0,
    "fluvial": 90.0,
    "lacustrine": 0.0,
    "delta": 30.0,
    "shoreline": 60.0,
    "shallow_marine": 135.0,
    "deep_marine": 160.0,
    "volcanic": -45.0,
    "other": 120.0,
}


def _fault_rules() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "value": value,
            "stroke": stroke,
            "stroke_width": width,
            "line_pattern": LinePattern.FAULT.value,
            "label": label,
        }
        for value, stroke, label, width in _FAULT_CLASSES
    )


def _facies_rules(*, with_patterns: bool = False) -> tuple[dict[str, Any], ...]:
    rules: list[dict[str, Any]] = []
    for value, fill, label in _FACIES_CLASSES:
        rule: dict[str, Any] = {"value": value, "fill": fill, "label": label}
        if with_patterns:
            pattern_id = pattern_id_for_facies(value)
            if pattern_id is not None:
                rule["pattern"] = pattern_id
        rules.append(rule)
    return tuple(rules)


def _facies_fill_patterns() -> tuple[tuple[str, str], ...]:
    """(facies value, pattern id) pairs for classes that have a tile."""
    return tuple(
        (value, pattern_id)
        for value, _fill, _label in _FACIES_CLASSES
        if (pattern_id := pattern_id_for_facies(value)) is not None
    )


_LINE_ROLES = frozenset({LayerRole.FAULT_CONSTRAINT})
_FACIES_ROLES = frozenset({
    LayerRole.INITIAL_FACIES_SOURCE,
    LayerRole.INITIAL_FACIES_DRAFT,
    LayerRole.FACTOR_CLASSIFICATION,
    LayerRole.INTEGRATED_FACIES,
})


def _sym(
    symbol_id: str,
    version: int,
    title: str,
    category: str,
    roles: frozenset[LayerRole],
    geometry_kind: str,
    fallback: VectorStyle,
    renderer_kind: str = "single",
    field_name: str | None = None,
    rules: tuple[dict[str, Any], ...] = (),
    extra_hint: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> GeologicalSymbolDef:
    hint: dict[str, Any] = {
        "renderer_kind": renderer_kind,
        "field": field_name,
        "rules": list(rules),
    }
    if extra_hint:
        hint.update(extra_hint)
    return GeologicalSymbolDef(
        symbol_id=symbol_id,
        version=version,
        title=title,
        category=category,
        applicable_roles=roles,
        geometry_kind=geometry_kind,
        legacy_fallback=fallback,
        renderer_hint=hint,
        metadata=dict(metadata or {}),
    )


_SYMBOL_BUILDERS: tuple[GeologicalSymbolDef, ...] = (

    # -- FAULT --------------------------------------------------------------

    _sym(
        "fault_v2", 2, "断层（按性质分类 + 置信度分级）", CATEGORY_SYMBOL_FAULT,
        _LINE_ROLES, "line",
        VectorStyle(
            fill="transparent", stroke="#c0392b", stroke_width=1.6,
            line_pattern=LinePattern.FAULT,
            renderer="categorized", field="fault_type",
            categories=tuple(
                (value, stroke, label)
                for value, stroke, label, _width in _FAULT_CLASSES
            ),
        ),
        renderer_kind="categorized", field_name="fault_type", rules=_fault_rules(),
        extra_hint={
            # Confidence gradations applied as data-defined stroke width /
            # alpha over the categorized base (see FAULT_CONFIDENCE_LEVELS).
            "confidence": {
                "field": "confidence",
                "mechanism": "data_defined",
                "applies_to": ["stroke_width", "stroke_alpha", "line_pattern"],
                "levels": _plain(FAULT_CONFIDENCE_LEVELS),
            },
        },
        metadata={
            "legend_label": "断层",
            "symbol_layers": "fault_type controls the categorized base symbol "
            "(hanging-wall decorations realised via renderer XML); confidence "
            "drives the data-defined gradations in renderer_hint.confidence",
            "confidence_semantics": {
                "inferred": "dashed, thinnest, 55% alpha — 仅供推断",
                "interpreted": "fault long-dash, standard weight — 解释成果",
                "verified": "fault long-dash, heaviest, opaque — 已验证",
            },
        },
    ),
    # Per-class singles: one standalone symbol per typed fault class (the
    # spec's fault_type domain minus the shared "unclassified" default).
    *(
        _sym(
            f"fault_{value}_v2", 2, label, CATEGORY_SYMBOL_FAULT,
            _LINE_ROLES, "line",
            VectorStyle(
                fill="transparent", stroke=stroke, stroke_width=width,
                line_pattern=LinePattern.FAULT,
            ),
            metadata={"legend_label": label, "fault_type": value},
        )
        for value, stroke, label, width in _FAULT_CLASSES
        if value != "unclassified"
    ),
    # "inferred" is a confidence level, not a fault_type: it gets its own
    # dashed single-symbol entry so the §6 vocabulary lists it explicitly.
    _sym(
        "fault_inferred_v2", 2, "推断断层（虚线）", CATEGORY_SYMBOL_FAULT,
        _LINE_ROLES, "line",
        VectorStyle(
            fill="transparent", stroke="#d98880", stroke_width=0.8,
            line_pattern=LinePattern.DASH,
        ),
        metadata={
            "legend_label": "推断断层",
            "confidence_level": "inferred",
            "note": "inferred confidence faults render dashed at reduced "
            "weight; fault_v2 realises this via renderer_hint.confidence",
        },
    ),

    # -- FACIES -------------------------------------------------------------

    _sym(
        "facies_v2", 2, "沉积相分类填充（9 类印刷色板）", CATEGORY_SYMBOL_FACIES,
        _FACIES_ROLES, "polygon",
        VectorStyle(
            fill="#b0bec5", stroke="#26364d", stroke_width=0.6,
            renderer="categorized", field="facies_name",
            categories=tuple(
                (value, fill, label) for value, fill, label in _FACIES_CLASSES
            ),
            fill_patterns=_facies_fill_patterns(),
        ),
        renderer_kind="categorized", field_name="facies_name",
        rules=_facies_rules(with_patterns=True),
        metadata={
            "legend_label": "沉积相",
            "legend_groups": [dict(group) for group in _FACIES_LEGEND_GROUPS],
            "palette": "print-safe geological fills; hierarchy groups drive "
            "composer legend grouping",
        },
    ),
    _sym(
        "facies_hatch_v2", 2, "沉积相纹理（图例 hatching 变体）",
        CATEGORY_SYMBOL_FACIES, _FACIES_ROLES, "polygon",
        VectorStyle(
            fill="transparent", stroke="#26364d", stroke_width=0.3,
            renderer="categorized", field="facies_name",
            categories=tuple(
                (value, "transparent", label)
                for value, _fill, label in _FACIES_CLASSES
            ),
        ),
        renderer_kind="categorized", field_name="facies_name", rules=_facies_rules(),
        metadata={
            "legend_label": "沉积相（纹理）",
            "hatch": {
                "style": "line_pattern_fill",
                "line_color": "#26364d",
                "line_width": 0.3,
                "spacing_mm": 1.2,
                "background": "transparent",
                "per_class_angle_deg": dict(_FACIES_HATCH_ANGLES),
                "note": "declaration only — realised as QGIS LinePatternFill "
                "symbol layers via renderer XML; composer legend textures "
                "read these parameters directly",
            },
        },
    ),

    # -- PROVENANCE ----------------------------------------------------------

    _sym(
        "provenance_line_v1", 1, "物源线（箭头装饰）", CATEGORY_SYMBOL_PROVENANCE,
        frozenset({LayerRole.PROVENANCE_LINE}), "line",
        VectorStyle(fill="transparent", stroke="#2f6fab", stroke_width=1.6),
        metadata={
            "legend_label": "物源线",
            "decorations": [
                {"kind": "arrow", "placement": "line_end", "size": 6.0,
                 "color": "#2f6fab"},
            ],
            "note": "arrow decorations realised as QGIS line-decoration "
            "symbol layers via renderer XML",
        },
    ),
    _sym(
        "provenance_direction_v1", 1, "物源方向（中点方向箭头 + 方位角标注）",
        CATEGORY_SYMBOL_PROVENANCE,
        frozenset({LayerRole.PROVENANCE_DIRECTION}), "line",
        VectorStyle(
            fill="transparent", stroke="#2b6777", stroke_width=1.2,
            line_pattern=LinePattern.DASH,
            labels=TextStyle(field="azimuth_deg", size=8.0),
        ),
        metadata={
            "legend_label": "物源方向",
            "decorations": [
                {"kind": "direction_arrow", "placement": "line_midpoint",
                 "rotation_field": "azimuth_deg", "size": 8.0,
                 "color": "#2b6777"},
            ],
            "labels": {"field": "azimuth_deg", "format": "{:.0f}°"},
        },
    ),
    _sym(
        "distribution_line_v1", 1, "沉积体系展布线", CATEGORY_SYMBOL_PROVENANCE,
        frozenset({LayerRole.DISTRIBUTION_LINE}), "line",
        VectorStyle(
            fill="transparent", stroke="#8a7136", stroke_width=1.8,
            line_pattern=LinePattern.DASH,
        ),
        metadata={"legend_label": "展布线"},
    ),

    # -- BOUNDARY ------------------------------------------------------------

    _sym(
        "shoreline_v2", 2, "古岸线", CATEGORY_SYMBOL_BOUNDARY,
        frozenset({LayerRole.PALEO_SHORELINE}), "line",
        VectorStyle(fill="transparent", stroke="#1f78b4", stroke_width=1.8),
        metadata={"legend_label": "古岸线"},
    ),
    _sym(
        "facies_boundary_v2", 2, "相带边界", CATEGORY_SYMBOL_BOUNDARY,
        frozenset({LayerRole.FACIES_BOUNDARY, LayerRole.INTEGRATED_BOUNDARY}),
        "line",
        VectorStyle(fill="transparent", stroke="#333f48", stroke_width=1.4),
        metadata={"legend_label": "相带边界"},
    ),
    _sym(
        "interpolation_boundary_v2", 2, "插值限制边界（成图范围）",
        CATEGORY_SYMBOL_BOUNDARY,
        frozenset({LayerRole.INTERPOLATION_BOUNDARY}), "polygon",
        VectorStyle(
            fill="transparent", stroke="#7f8c8d", stroke_width=1.2,
            line_pattern=LinePattern.DASH,
        ),
        metadata={"legend_label": "插值限制边界"},
    ),
    _sym(
        "map_extent", 2, "成图范围/图框边界", CATEGORY_SYMBOL_BOUNDARY,
        frozenset({
            LayerRole.INTERPOLATION_BOUNDARY,
            LayerRole.MAP_REFERENCE,
            LayerRole.BASE_REFERENCE,
        }),
        "polygon",
        VectorStyle(fill="transparent", stroke="#1c2833", stroke_width=2.4),
        metadata={"legend_label": "成图范围"},
    ),
)

GEOLOGICAL_SYMBOLS: dict[str, GeologicalSymbolDef] = {
    symbol.symbol_id: symbol for symbol in _SYMBOL_BUILDERS
}


# ---------------------------------------------------------------------------
# Lookups & validation


def canonical_symbol_id(symbol_id: str) -> str:
    """Resolve aliases (``shoreline_v1`` → ``shoreline_v2``)."""
    return SYMBOL_ALIASES.get(symbol_id, symbol_id)


def symbol_by_id(symbol_id: str) -> GeologicalSymbolDef:
    """Lookup; unknown ids raise with the available ids listed."""
    symbol = GEOLOGICAL_SYMBOLS.get(canonical_symbol_id(symbol_id))
    if symbol is None:
        raise KeyError(
            f"unknown geological symbol {symbol_id!r}; available: "
            f"{sorted(GEOLOGICAL_SYMBOLS)}"
        )
    return symbol


def symbols_for_role(role: LayerRole | str) -> list[GeologicalSymbolDef]:
    """All symbols whose ``applicable_roles`` contain ``role``."""
    key = role if isinstance(role, LayerRole) else LayerRole(role)
    return [s for s in GEOLOGICAL_SYMBOLS.values() if key in s.applicable_roles]


def validate_binding(
    symbol_id: str, role: LayerRole | str, geometry_kind: str
) -> tuple[bool, str]:
    """Role/geometry compatibility check (§6: a fault style cannot bind a
    shoreline layer).  Returns ``(ok, reason)``; reason is ``"ok"`` on
    success or a human-readable explanation otherwise."""
    try:
        symbol = symbol_by_id(symbol_id)
    except KeyError:
        return False, f"unknown symbol {symbol_id!r}"
    try:
        key = role if isinstance(role, LayerRole) else LayerRole(role)
    except ValueError:
        return False, f"unknown role {role!r}"
    if key not in symbol.applicable_roles:
        return False, (
            f"symbol {symbol.symbol_id!r} (category {symbol.category!r}) does "
            f"not apply to role {key.value!r}"
        )
    if geometry_kind not in _COMPATIBLE_GEOMETRY[symbol.geometry_kind]:
        return False, (
            f"symbol {symbol.symbol_id!r} expects {symbol.geometry_kind!r} "
            f"geometry; got {geometry_kind!r}"
        )
    return True, "ok"


def library_version() -> int:
    """The §6 symbol library version (bumps on vocabulary changes)."""
    return SYMBOL_LIBRARY_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Fallback style & binding records


def legacy_style_for_symbol(symbol_id: str, **overrides: Any) -> dict[str, Any]:
    """The flat ``VectorStyle`` dict for the fallback renderer.

    Keyword overrides must be ``VectorStyle`` field names (``stroke``,
    ``stroke_width``, ``line_pattern``, ``marker``, ``labels``, ...);
    ``line_pattern``/``marker`` accept their string values.
    """
    symbol = symbol_by_id(symbol_id)
    style = symbol.legacy_fallback
    if overrides:
        replacements: dict[str, Any] = {}
        for key, value in overrides.items():
            if key == "line_pattern":
                value = LinePattern(value)
            elif key == "marker":
                value = MarkerSymbol(value)
            replacements[key] = value
        style = replace(style, **replacements)
    return style.to_dict()


def binding_record(
    symbol_id: str, field_values: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The style↔science traceability record stored as ``style_binding``
    (same role as ``StyleEntry.binding`` in the V1 library)."""
    symbol = symbol_by_id(symbol_id)
    record: dict[str, Any] = {
        "symbol_id": symbol.symbol_id,
        "symbol_version": int(symbol.version),
        "category": symbol.category,
        "field": symbol.renderer_hint.get("field"),
        "classes": [
            rule["value"] for rule in symbol.renderer_hint.get("rules", ())
        ],
        "source": f"geological-symbols-v{SYMBOL_LIBRARY_SCHEMA_VERSION}/"
                  f"{symbol.symbol_id}",
    }
    confidence = symbol.renderer_hint.get("confidence")
    if isinstance(confidence, Mapping):
        record["confidence_field"] = confidence.get("field")
    if field_values:
        record["field_values"] = dict(field_values)
    return record


def style_entry_for_symbol(symbol_id: str) -> StyleEntry:
    """Project a symbol into a V1 ``StyleEntry`` (registration/apply seam)."""
    return symbol_by_id(symbol_id).style_entry()


def apply_symbol_to_layer(
    layer: Any, symbol_id: str, *, field_values: Mapping[str, Any] | None = None
) -> None:
    """Apply a symbol's fallback style to ``layer`` via the V1 apply path,
    recording the versioned symbol binding in the style payload."""
    entry = symbol_by_id(symbol_id).style_entry()
    if field_values:
        entry = replace(entry, binding=binding_record(symbol_id, field_values))
    apply_style_to_layer(layer, entry)


# ---------------------------------------------------------------------------
# V1 library coexistence


def register_symbols_into_style_library(
    library: dict[str, StyleEntry] | None = None,
) -> list[str]:
    """Register every V2 symbol as a ``StyleEntry`` in the V1 library.

    Explicit and idempotent (the 12 V1 entries are never replaced); pass a
    dict to register into a copy.  Returns the keys added."""
    target = GEOLOGICAL_STYLE_LIBRARY if library is None else library
    added: list[str] = []
    for symbol in GEOLOGICAL_SYMBOLS.values():
        entry = symbol.style_entry()
        key = f"{entry.category}.{entry.key}"
        target[key] = entry
        added.append(key)
    return added


def unregister_symbols_from_style_library(
    library: dict[str, StyleEntry] | None = None,
) -> list[str]:
    """Reverse :func:`register_symbols_into_style_library` (idempotent)."""
    target = GEOLOGICAL_STYLE_LIBRARY if library is None else library
    removed: list[str] = []
    for symbol in GEOLOGICAL_SYMBOLS.values():
        key = f"{_LEGACY_CATEGORY[symbol.category]}.{symbol.symbol_id}"
        if target.pop(key, None) is not None:
            removed.append(key)
    return removed


# ---------------------------------------------------------------------------
# Library serialization


def library_to_dict() -> dict[str, Any]:
    """Serialise the whole V2 library (versioned, JSON-safe)."""
    return {
        "schema_version": SYMBOL_LIBRARY_SCHEMA_VERSION,
        "symbols": [symbol.to_dict() for symbol in GEOLOGICAL_SYMBOLS.values()],
    }


def library_from_dict(
    data: Mapping[str, Any],
) -> dict[str, GeologicalSymbolDef]:
    """Rebuild a symbol library from :func:`library_to_dict` output."""
    version = int(data.get("schema_version") or 0)
    if version != SYMBOL_LIBRARY_SCHEMA_VERSION:
        raise ValueError(
            f"symbol library schema {version} unsupported; "
            f"expected {SYMBOL_LIBRARY_SCHEMA_VERSION}"
        )
    return {
        str(raw["symbol_id"]): GeologicalSymbolDef.from_dict(raw)
        for raw in data.get("symbols") or ()
    }


def save_symbol_library(path: str | Path) -> Path:
    """Persist the V2 symbol library as versioned JSON."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(library_to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def load_symbol_library(path: str | Path) -> dict[str, GeologicalSymbolDef]:
    """Load a previously saved V2 symbol library."""
    return library_from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
