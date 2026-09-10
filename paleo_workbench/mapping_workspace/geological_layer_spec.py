"""GeologicalLayerSpec V2 (qgis-geolayer-cartography-v7 §3).

Declarative, QGIS-drivable layer specifications for every geological layer
role.  The registry is the ONE formal binding between:

* ``LayerRole`` — the science vocabulary (:mod:`.layer_roles`);
* ``LayerType`` — the runtime document types (:mod:`paleo_workbench.mapping.layers`);
* the QGIS layer schema — QgsFields / constraints / value domains / defaults
  / editor widgets, delivered through :mod:`paleo_workbench.mapping.qgis_layer_schema`
  as a ``fields_json`` wire payload.

Policies (edit / snapping / topology / stage / maturity / provenance) derive
from the existing authorities (``ROLE_EDITABLE``, ``ROLE_RAW_PROTECTED``,
``stages_for_role``) instead of duplicating them.  Pure data — no Qt, no
QGIS import — so the whole registry validates in every environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .layer_groups import stages_for_role
from .layer_roles import (
    ROLE_EDITABLE,
    ROLE_RAW_PROTECTED,
    ConstraintKind,
    LayerRole,
)
from .stages import MappingStage

__all__ = [
    "GEOLOGICAL_LAYER_SPECS",
    "EditPolicy",
    "GeologicalLayerSpec",
    "LabelBinding",
    "MaturityPolicy",
    "ProvenancePolicy",
    "RendererBinding",
    "ScaleVisibility",
    "SnappingPolicy",
    "SpecField",
    "StagePolicy",
    "TopologyPolicy",
    "layer_type_for_role",
    "role_for_layer_type",
    "spec_for_role",
    "specs_for_constraint_kind",
]


# ---------------------------------------------------------------------------
# Field-level description (generalizes composite_editing.TemplateField)


@dataclass(frozen=True)
class SpecField:
    """One attribute field of a geological layer.

    ``kind`` ∈ text/int/real/bool/datetime.  ``choices`` is a closed value
    domain (QGIS ValueMap editor widget); ``value_range`` a numeric range
    (QGIS Range widget bounds); ``required``+``expression`` map to QGIS
    field constraints.  Defaults seed new features during digitizing.
    """

    name: str
    label: str = ""
    kind: str = "text"
    length: int | None = None
    precision: int | None = None
    choices: tuple[str, ...] = ()
    value_range: tuple[float, float] | None = None
    default: Any = ""
    required: bool = False
    unique: bool = False
    expression: str = ""
    editor_widget: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "required": self.required,
            "default": self.default,
        }
        if self.length is not None:
            data["length"] = self.length
        if self.precision is not None:
            data["precision"] = self.precision
        if self.choices:
            data["choices"] = list(self.choices)
        if self.value_range is not None:
            data["value_range"] = list(self.value_range)
        if self.unique:
            data["unique"] = True
        if self.expression:
            data["expression"] = self.expression
        if self.editor_widget is not None:
            data["editor_widget"] = self.editor_widget
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpecField":
        value_range = data.get("value_range")
        return cls(
            name=str(data["name"]),
            label=str(data.get("label", "")),
            kind=str(data.get("kind", "text")),
            length=data.get("length"),
            precision=data.get("precision"),
            choices=tuple(str(c) for c in data.get("choices", ())),
            value_range=tuple(value_range) if value_range else None,
            default=data.get("default", ""),
            required=bool(data.get("required", False)),
            unique=bool(data.get("unique", False)),
            expression=str(data.get("expression", "")),
            editor_widget=data.get("editor_widget"),
        )


# ---------------------------------------------------------------------------
# Policies


@dataclass(frozen=True)
class EditPolicy:
    editable: bool
    raw_protected: bool
    allow_geometry_edit: bool = True
    allow_attribute_edit: bool = True

    def to_dict(self):
        return {
            "editable": self.editable,
            "raw_protected": self.raw_protected,
            "allow_geometry_edit": self.allow_geometry_edit,
            "allow_attribute_edit": self.allow_attribute_edit,
        }


@dataclass(frozen=True)
class SnappingPolicy:
    enabled: bool
    modes: tuple[str, ...] = ("vertex",)
    tolerance: float = 10.0
    unit: str = "pixels"
    topological: bool = False

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "modes": list(self.modes),
            "tolerance": self.tolerance,
            "unit": self.unit,
            "topological": self.topological,
        }


@dataclass(frozen=True)
class TopologyPolicy:
    validate_on_flush: bool = True
    rules: tuple[str, ...] = ("ring_closure",)

    def to_dict(self):
        return {
            "validate_on_flush": self.validate_on_flush,
            "rules": list(self.rules),
        }


@dataclass(frozen=True)
class StagePolicy:
    visible_stages: tuple[MappingStage, ...]
    locked_stages: tuple[MappingStage, ...] = ()


@dataclass(frozen=True)
class MaturityPolicy:
    track: bool = True
    initial: str = "draft"


@dataclass(frozen=True)
class ProvenancePolicy:
    #: catalog_version_pinned — layer pins a catalog DataVersion (factors);
    #: content_fingerprint — content hashed for freshness (constraints);
    #: session_only — ephemeral view layers.
    mode: str = "session_only"
    pins_inputs: bool = False


@dataclass(frozen=True)
class RendererBinding:
    style_id: str
    fallback_style: str
    renderer_kind: str = "single"  # single|categorized|graduated|pseudocolor|rule_based
    field: str | None = None

    def to_dict(self):
        return {
            "style_id": self.style_id,
            "fallback_style": self.fallback_style,
            "renderer_kind": self.renderer_kind,
            "field": self.field,
        }


@dataclass(frozen=True)
class LabelBinding:
    enabled: bool = False
    field: str | None = None
    size_field: str | None = None
    color_field: str | None = None
    rotation_field: str | None = None

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "field": self.field,
            "size_field": self.size_field,
            "color_field": self.color_field,
            "rotation_field": self.rotation_field,
        }


@dataclass(frozen=True)
class ScaleVisibility:
    min_scale: int | None = None  # visible when scale <= min (larger features)
    max_scale: int | None = None  # visible when scale >= max (zoomed in past)

    def to_dict(self):
        return {"min_scale": self.min_scale, "max_scale": self.max_scale}


# ---------------------------------------------------------------------------
# The spec


@dataclass(frozen=True)
class GeologicalLayerSpec:
    spec_id: str
    role: LayerRole
    geometry_kind: str  # point|line|polygon|raster
    title: str
    fields: tuple[SpecField, ...] = ()
    edit_policy: EditPolicy | None = None
    snapping_policy: SnappingPolicy | None = None
    topology_policy: TopologyPolicy | None = None
    stage_policy: StagePolicy | None = None
    maturity_policy: MaturityPolicy | None = None
    provenance_policy: ProvenancePolicy | None = None
    renderer_binding: RendererBinding | None = None
    label_binding: LabelBinding | None = None
    scale_visibility: ScaleVisibility | None = None
    constraint_kind: ConstraintKind | None = None
    factor_child: str | None = None

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        def _opt(name: str, value: Any) -> dict[str, Any]:
            return {name: value.to_dict()} if value is not None else {}

        data: dict[str, Any] = {
            "spec_id": self.spec_id,
            "role": self.role.value,
            "geometry_kind": self.geometry_kind,
            "title": self.title,
            "fields": [f.to_dict() for f in self.fields],
            **_opt("edit_policy", self.edit_policy),
            **_opt("snapping_policy", self.snapping_policy),
            **_opt("topology_policy", self.topology_policy),
            **_opt("renderer_binding", self.renderer_binding),
            **_opt("label_binding", self.label_binding),
            **_opt("scale_visibility", self.scale_visibility),
        }
        if self.stage_policy is not None:
            data["stage_policy"] = {
                "visible_stages": [s.value for s in self.stage_policy.visible_stages],
                "locked_stages": [s.value for s in self.stage_policy.locked_stages],
            }
        if self.maturity_policy is not None:
            data["maturity_policy"] = {
                "track": self.maturity_policy.track,
                "initial": self.maturity_policy.initial,
            }
        if self.provenance_policy is not None:
            data["provenance_policy"] = {
                "mode": self.provenance_policy.mode,
                "pins_inputs": self.provenance_policy.pins_inputs,
            }
        if self.constraint_kind is not None:
            data["constraint_kind"] = self.constraint_kind.value
        if self.factor_child is not None:
            data["factor_child"] = self.factor_child
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeologicalLayerSpec":
        edit = data.get("edit_policy")
        snap = data.get("snapping_policy")
        topo = data.get("topology_policy")
        renderer = data.get("renderer_binding")
        label = data.get("label_binding")
        scale = data.get("scale_visibility")
        stage = data.get("stage_policy")
        maturity = data.get("maturity_policy")
        provenance = data.get("provenance_policy")
        return cls(
            spec_id=str(data["spec_id"]),
            role=LayerRole(str(data["role"])),
            geometry_kind=str(data["geometry_kind"]),
            title=str(data["title"]),
            fields=tuple(SpecField.from_dict(f) for f in data.get("fields", ())),
            edit_policy=EditPolicy(**edit) if edit else None,
            snapping_policy=(
                SnappingPolicy(
                    enabled=snap["enabled"],
                    modes=tuple(snap.get("modes", ("vertex",))),
                    tolerance=float(snap.get("tolerance", 10.0)),
                    unit=str(snap.get("unit", "pixels")),
                    topological=bool(snap.get("topological", False)),
                ) if snap else None
            ),
            topology_policy=(
                TopologyPolicy(
                    validate_on_flush=bool(topo.get("validate_on_flush", True)),
                    rules=tuple(topo.get("rules", ("ring_closure",))),
                ) if topo else None
            ),
            stage_policy=(
                StagePolicy(
                    visible_stages=tuple(
                        MappingStage(s) for s in stage.get("visible_stages", ())),
                    locked_stages=tuple(
                        MappingStage(s) for s in stage.get("locked_stages", ())),
                ) if stage else None
            ),
            maturity_policy=(
                MaturityPolicy(
                    track=bool(maturity.get("track", True)),
                    initial=str(maturity.get("initial", "draft")),
                ) if maturity else None
            ),
            provenance_policy=(
                ProvenancePolicy(
                    mode=str(provenance.get("mode", "session_only")),
                    pins_inputs=bool(provenance.get("pins_inputs", False)),
                ) if provenance else None
            ),
            renderer_binding=(
                RendererBinding(
                    style_id=str(renderer["style_id"]),
                    fallback_style=str(renderer["fallback_style"]),
                    renderer_kind=str(renderer.get("renderer_kind", "single")),
                    field=renderer.get("field"),
                ) if renderer else None
            ),
            label_binding=(
                LabelBinding(
                    enabled=bool(label.get("enabled", False)),
                    field=label.get("field"),
                    size_field=label.get("size_field"),
                    color_field=label.get("color_field"),
                    rotation_field=label.get("rotation_field"),
                ) if label else None
            ),
            scale_visibility=(
                ScaleVisibility(
                    min_scale=scale.get("min_scale"),
                    max_scale=scale.get("max_scale"),
                ) if scale else None
            ),
            constraint_kind=(
                ConstraintKind(str(data["constraint_kind"]))
                if data.get("constraint_kind") else None),
            factor_child=data.get("factor_child"),
        )

    def to_template_schema(self) -> dict[str, Any]:
        """Convert fields to the existing TemplateField schema consumed by
        composite editing (name/kind/choices/default/required survive)."""
        return {
            "fields": [
                {
                    "name": f.name,
                    "label": f.label or f.name,
                    "kind": "choice" if f.choices else (
                        "number" if f.kind in {"int", "real"} else "text"),
                    "choices": list(f.choices) if f.choices else [],
                    "default": f.default,
                    "required": f.required,
                }
                for f in self.fields
            ]
        }


# ---------------------------------------------------------------------------
# Registry construction


def _policies(role: LayerRole, *, snapping: SnappingPolicy | None = None,
              topology: TopologyPolicy | None = None,
              provenance: ProvenancePolicy | None = None,
              maturity: MaturityPolicy | None = None) -> dict[str, Any]:
    editable = role in ROLE_EDITABLE
    raw = role in ROLE_RAW_PROTECTED
    stages = tuple(stages_for_role(role))
    # Locked stages are owned by the system group templates (layer_groups);
    # the spec only repeats the visibility routing, never re-derives locks.
    locked: tuple[MappingStage, ...] = ()
    return {
        "edit_policy": EditPolicy(
            editable=editable, raw_protected=raw,
            allow_geometry_edit=editable, allow_attribute_edit=True),
        "snapping_policy": snapping if snapping is not None else (
            SnappingPolicy(enabled=editable and role is not LayerRole.USER_GENERAL,
                           modes=("vertex", "segment"))
            if editable else None),
        "topology_policy": topology if topology is not None else (
            TopologyPolicy() if role.value.startswith(("initial", "integrated",
                                                       "factor_class"))
            else TopologyPolicy(validate_on_flush=False, rules=())),
        "stage_policy": StagePolicy(visible_stages=stages, locked_stages=locked),
        "maturity_policy": maturity if maturity is not None else MaturityPolicy(
            track=role in (
                LayerRole.INITIAL_FACIES_DRAFT, LayerRole.INTEGRATED_FACIES,
                LayerRole.INTEGRATED_BOUNDARY)),
        "provenance_policy": provenance if provenance is not None else (
            ProvenancePolicy(mode="catalog_version_pinned", pins_inputs=True)
            if role in (LayerRole.FACTOR_GRID, LayerRole.FACTOR_CONTOUR,
                        LayerRole.FACTOR_CLASSIFICATION,
                        LayerRole.FACTOR_UNCERTAINTY, LayerRole.FACTOR_QC)
            else ProvenancePolicy(mode="session_only")),
    }


def _spec(spec_id: str, role: LayerRole, geometry_kind: str, title: str, *,
          fields: tuple[SpecField, ...] = (),
          renderer: RendererBinding | None = None,
          label: LabelBinding | None = None,
          scale: ScaleVisibility | None = None,
          constraint_kind: ConstraintKind | None = None,
          factor_child: str | None = None,
          **policy_kwargs: Any) -> GeologicalLayerSpec:
    return GeologicalLayerSpec(
        spec_id=spec_id, role=role, geometry_kind=geometry_kind, title=title,
        fields=fields, renderer_binding=renderer, label_binding=label,
        scale_visibility=scale, constraint_kind=constraint_kind,
        factor_child=factor_child, **_policies(role, **policy_kwargs),
    )


_F = SpecField

_FAULT_FIELDS = (
    _F("fault_type", "断层性质", kind="text", choices=(
        "normal", "reverse", "thrust", "strike_slip", "unclassified"),
       default="unclassified", required=True),
    _F("confidence", "置信度", kind="text", choices=(
        "inferred", "interpreted", "verified"), default="interpreted",
       required=True),
    _F("activity", "活动性", kind="text", choices=("active", "dormant", "unknown"),
       default="unknown"),
)

_FACIES_CLASS_FIELD = _F(
    "facies_name", "相名", kind="text", required=True,
    choices=("alluvial_fan", "fluvial", "lacustrine", "delta", "shoreline",
             "shallow_marine", "deep_marine", "volcanic", "other"),
    default="other")

_FACIES_FIELDS = (
    _FACIES_CLASS_FIELD,
    _F("facies_id", "相编号", kind="text", default=""),
    _F("source", "来源", kind="text", default="interpretation"),
)

_CONSTRAINT_BASE_FIELDS = (
    _F("name", "名称", kind="text", default=""),
    _F("active", "参与插值", kind="bool", default=True),
    _F("note", "备注", kind="text", default=""),
)


def _build_registry() -> dict[LayerRole, GeologicalLayerSpec]:
    specs: dict[LayerRole, GeologicalLayerSpec] = {}

    def add(spec: GeologicalLayerSpec) -> None:
        specs[spec.role] = spec

    # -- Phase 1 ------------------------------------------------------------
    add(_spec(
        "initial-facies-source-v2", LayerRole.INITIAL_FACIES_SOURCE, "polygon",
        "初始沉积相（RAW）", fields=_FACIES_FIELDS,
        renderer=RendererBinding("facies_v1", "facies", "categorized",
                                 field="facies_name"),
        label=LabelBinding(enabled=True, field="facies_name")))
    add(_spec(
        "initial-facies-draft-v2", LayerRole.INITIAL_FACIES_DRAFT, "polygon",
        "初始相校正草稿（DERIVED）", fields=_FACIES_FIELDS,
        renderer=RendererBinding("facies_v1", "facies", "categorized",
                                 field="facies_name"),
        label=LabelBinding(enabled=True, field="facies_name"),
        provenance=ProvenancePolicy(mode="content_fingerprint", pins_inputs=True)))
    for role, style_id, kind in (
        (LayerRole.WELL_FACIES_PREDICTION, "prediction_overlay_v1", "categorized"),
        (LayerRole.WELL_FACIES_CONFIDENCE, "confidence_band_v1", "graduated"),
        (LayerRole.SEISMIC_FACIES_PREDICTION, "prediction_overlay_v1", "categorized"),
        (LayerRole.SEISMIC_FACIES_CONFIDENCE, "confidence_band_v1", "graduated"),
    ):
        add(_spec(
            f"{role.value}-v2", role, "polygon", role.label,
            fields=(_F("probability", "概率", kind="real", value_range=(0.0, 1.0),
                       default=0.0),),
            renderer=RendererBinding(style_id, "facies", kind,
                                     field="probability" if kind == "graduated"
                                     else None)))
    add(_spec(
        "interpretation-annotation-v2", LayerRole.INTERPRETATION_ANNOTATION,
        "point", "解释标注",
        fields=(_F("text", "内容", kind="text", required=True, default=""),),
        renderer=RendererBinding("annotation_v1", "annotation", "single"),
        label=LabelBinding(enabled=True, field="text")))

    # -- Phase 2 constraints --------------------------------------------------
    add(_spec(
        "fault-constraint-v2", LayerRole.FAULT_CONSTRAINT, "line", "断层",
        fields=_FAULT_FIELDS + _CONSTRAINT_BASE_FIELDS,
        renderer=RendererBinding("fault_v2", "fault", "categorized",
                                 field="fault_type"),
        constraint_kind=ConstraintKind.FAULT,
        snapping=SnappingPolicy(enabled=True, modes=("vertex", "segment"),
                                topological=True)))
    add(_spec(
        "provenance-line-v2", LayerRole.PROVENANCE_LINE, "line", "物源线",
        fields=_CONSTRAINT_BASE_FIELDS,
        renderer=RendererBinding("provenance_line_v1", "line", "single"),
        constraint_kind=ConstraintKind.PROVENANCE_LINE))
    add(_spec(
        "provenance-direction-v2", LayerRole.PROVENANCE_DIRECTION, "line",
        "物源方向",
        fields=_CONSTRAINT_BASE_FIELDS + (
            _F("azimuth_deg", "方位角", kind="real", value_range=(0.0, 360.0)),
            _F("semi_major", "长半轴", kind="real", value_range=(0.0, 1e9)),
            _F("semi_minor", "短半轴", kind="real", value_range=(0.0, 1e9)),
        ),
        renderer=RendererBinding("provenance_direction_v1", "line", "single"),
        label=LabelBinding(enabled=True, field="azimuth_deg"),
        constraint_kind=ConstraintKind.SOURCE_DIRECTION))
    add(_spec(
        "distribution-line-v2", LayerRole.DISTRIBUTION_LINE, "line", "沉积体系展布线",
        fields=_CONSTRAINT_BASE_FIELDS,
        renderer=RendererBinding("distribution_line_v1", "line", "single"),
        constraint_kind=ConstraintKind.DISTRIBUTION_LINE))
    add(_spec(
        "paleo-shoreline-v2", LayerRole.PALEO_SHORELINE, "line", "古岸线",
        fields=_CONSTRAINT_BASE_FIELDS + (
            _F("shoreline_type", "岸线类型", kind="text",
               choices=("marine", "lacustrine", "deltaic", "unclassified"),
               default="unclassified"),),
        renderer=RendererBinding("shoreline_v1", "formation_boundary", "single"),
        constraint_kind=ConstraintKind.PALEO_SHORELINE))
    add(_spec(
        "facies-boundary-v2", LayerRole.FACIES_BOUNDARY, "line", "相带边界",
        fields=_CONSTRAINT_BASE_FIELDS,
        renderer=RendererBinding("facies_boundary_v1", "formation_boundary",
                                 "single"),
        constraint_kind=ConstraintKind.FACIES_BOUNDARY))
    add(_spec(
        "interpolation-boundary-v2", LayerRole.INTERPOLATION_BOUNDARY, "polygon",
        "插值限制边界（成图范围）",
        fields=_CONSTRAINT_BASE_FIELDS,
        renderer=RendererBinding("interpolation_boundary_v1", "line", "single"),
        constraint_kind=ConstraintKind.INTERPOLATION_BOUNDARY))
    add(_spec(
        "mask-boundary-v2", LayerRole.MASK_BOUNDARY, "polygon", "掩膜/排除区",
        fields=_CONSTRAINT_BASE_FIELDS + (
            _F("mask_kind", "类型", kind="text",
               choices=("mask", "exclusion"), default="mask"),),
        renderer=RendererBinding("mask_v1", "polygon", "single"),
        constraint_kind=ConstraintKind.MASK))

    # -- Phase 2 factor family -------------------------------------------------
    add(_spec(
        "factor-input-v2", LayerRole.FACTOR_INPUT, "point", "单因素输入井点",
        fields=(
            _F("well_id", "井号", kind="text", required=True),
            _F("value", "值", kind="real"),
            _F("qc_flag", "QC", kind="text",
               choices=("ok", "outlier", "invalid_ratio", "missing"),
               default="ok"),
        ),
        renderer=RendererBinding("well_v1", "well", "single"),
        label=LabelBinding(enabled=True, field="value"),
        factor_child="input"))
    add(_spec(
        "factor-grid-v2", LayerRole.FACTOR_GRID, "raster", "单因素栅格",
        renderer=RendererBinding("factor_scalar_v1", "grid", "pseudocolor"),
        factor_child="grid"))
    add(_spec(
        "factor-contour-v2", LayerRole.FACTOR_CONTOUR, "line", "单因素等值线",
        fields=(
            _F("level", "等值线值", kind="real", required=True),
            _F("is_index_contour", "计曲线", kind="bool", default=False),
            _F("unit", "单位", kind="text", default=""),
        ),
        renderer=RendererBinding("contour_v1", "contour", "single"),
        label=LabelBinding(enabled=True, field="level"),
        factor_child="contour"))
    add(_spec(
        "factor-classification-v2", LayerRole.FACTOR_CLASSIFICATION, "polygon",
        "单因素分级区",
        fields=(_FACIES_CLASS_FIELD, _F("area", "面积", kind="real"),
                _F("area_unit", "面积单位", kind="text", default="")),
        renderer=RendererBinding("facies_v1", "facies", "categorized",
                                 field="facies_name"),
        factor_child="classification"))
    add(_spec(
        "factor-uncertainty-v2", LayerRole.FACTOR_UNCERTAINTY, "raster",
        "不确定性面",
        renderer=RendererBinding("uncertainty_band_v1", "grid", "pseudocolor"),
        factor_child="uncertainty"))
    add(_spec(
        "factor-qc-v2", LayerRole.FACTOR_QC, "point", "单因素 QC",
        fields=(
            _F("rule", "规则", kind="text", required=True),
            _F("severity", "严重度", kind="text",
               choices=("info", "warning", "error"), default="warning"),
            _F("reason", "原因", kind="text"),
        ),
        renderer=RendererBinding("qc_overlay_v1", "annotation", "categorized",
                                 field="severity"),
        factor_child="qc"))
    add(_spec(
        "analysis-aid-v2", LayerRole.ANALYSIS_AID, "point", "分析辅助（残差/异常）",
        fields=(
            _F("kind", "类型", kind="text",
               choices=("residual", "outlier", "coverage"), default="residual"),
            _F("value", "值", kind="real"),
        ),
        renderer=RendererBinding("qc_overlay_v1", "annotation", "categorized",
                                 field="kind")))

    # -- Phase 3 ------------------------------------------------------------
    add(_spec(
        "integrated-facies-v2", LayerRole.INTEGRATED_FACIES, "polygon",
        "综合沉积相", fields=_FACIES_FIELDS,
        renderer=RendererBinding("facies_v1", "facies", "categorized",
                                 field="facies_name"),
        label=LabelBinding(enabled=True, field="facies_name"),
        provenance=ProvenancePolicy(mode="content_fingerprint", pins_inputs=True)))
    add(_spec(
        "integrated-boundary-v2", LayerRole.INTEGRATED_BOUNDARY, "line",
        "综合相带边界",
        fields=_CONSTRAINT_BASE_FIELDS,
        renderer=RendererBinding("facies_boundary_v1", "formation_boundary",
                                 "single")))
    add(_spec(
        "map-annotation-v2", LayerRole.MAP_ANNOTATION, "point", "专题标注",
        fields=(_F("text", "内容", kind="text", required=True, default=""),),
        renderer=RendererBinding("annotation_v1", "annotation", "single"),
        label=LabelBinding(enabled=True, field="text")))
    add(_spec(
        "map-reference-v2", LayerRole.MAP_REFERENCE, "vector", "编图参考",
        renderer=RendererBinding("map_reference_v1", "line", "single")))

    # -- base / user / QC ------------------------------------------------------
    add(_spec(
        "base-reference-v2", LayerRole.BASE_REFERENCE, "vector", "基础参考图层",
        fields=(_F("name", "名称", kind="text", default=""),),
        renderer=RendererBinding("base_reference_v1", "line", "single")))
    add(_spec(
        "user-general-v2", LayerRole.USER_GENERAL, "vector", "用户图层"))
    add(_spec(
        "qc-warning-v2", LayerRole.QC_WARNING, "point", "QC 警告",
        fields=(
            _F("rule", "规则", kind="text", required=True),
            _F("severity", "严重度", kind="text",
               choices=("info", "warning", "error"), default="warning"),
            _F("reason", "原因", kind="text"),
        ),
        renderer=RendererBinding("qc_overlay_v1", "annotation", "categorized",
                                 field="severity")))
    add(_spec(
        "qc-conflict-v2", LayerRole.QC_CONFLICT, "point", "QC 冲突",
        fields=(
            _F("rule", "规则", kind="text", required=True),
            _F("reason", "原因", kind="text"),
        ),
        renderer=RendererBinding("qc_overlay_v1", "annotation", "single")))

    return specs


GEOLOGICAL_LAYER_SPECS: dict[LayerRole, GeologicalLayerSpec] = _build_registry()


def spec_for_role(role: LayerRole | str) -> GeologicalLayerSpec:
    """Return the spec for ``role``; unknown roles are an error, never a
    silent default."""
    if isinstance(role, LayerRole):
        key = role
    else:
        try:
            key = LayerRole(role)
        except ValueError:
            raise KeyError(f"unknown LayerRole {role!r}") from None
    try:
        return GEOLOGICAL_LAYER_SPECS[key]
    except KeyError:
        raise KeyError(
            f"no GeologicalLayerSpec registered for role {key.value!r}") from None


def specs_for_constraint_kind(kind: ConstraintKind | str) -> list[LayerRole]:
    """Roles bound to a geological constraint kind (usually one)."""
    want = ConstraintKind(kind) if not isinstance(kind, ConstraintKind) else kind
    return [role for role, spec in GEOLOGICAL_LAYER_SPECS.items()
            if spec.constraint_kind is want]


# ---------------------------------------------------------------------------
# LayerType ↔ LayerRole binding (runtime ↔ science vocabularies)


_LAYER_TYPE_FOR_ROLE: dict[LayerRole, str] = {
    LayerRole.INITIAL_FACIES_SOURCE: "polygon",
    LayerRole.INITIAL_FACIES_DRAFT: "polygon",
    LayerRole.WELL_FACIES_PREDICTION: "polygon",
    LayerRole.WELL_FACIES_CONFIDENCE: "polygon",
    LayerRole.SEISMIC_FACIES_PREDICTION: "polygon",
    LayerRole.SEISMIC_FACIES_CONFIDENCE: "polygon",
    LayerRole.INTERPRETATION_ANNOTATION: "annotation",
    LayerRole.PROVENANCE_DIRECTION: "vector",
    LayerRole.PROVENANCE_LINE: "vector",
    LayerRole.DISTRIBUTION_LINE: "vector",
    LayerRole.PALEO_SHORELINE: "vector",
    LayerRole.FACIES_BOUNDARY: "vector",
    LayerRole.FAULT_CONSTRAINT: "vector",
    LayerRole.INTERPOLATION_BOUNDARY: "polygon",
    LayerRole.MASK_BOUNDARY: "polygon",
    LayerRole.FACTOR_INPUT: "well_point",
    LayerRole.FACTOR_GRID: "scalar_grid",
    LayerRole.FACTOR_CONTOUR: "contour",
    LayerRole.FACTOR_CLASSIFICATION: "polygon",
    LayerRole.FACTOR_UNCERTAINTY: "scalar_grid",
    LayerRole.FACTOR_QC: "vector",
    LayerRole.ANALYSIS_AID: "vector",
    LayerRole.INTEGRATED_FACIES: "polygon",
    LayerRole.INTEGRATED_BOUNDARY: "vector",
    LayerRole.MAP_ANNOTATION: "annotation",
    LayerRole.MAP_SYMBOL: "annotation",
    LayerRole.MAP_REFERENCE: "vector",
    LayerRole.QC_WARNING: "vector",
    LayerRole.QC_CONFLICT: "vector",
    LayerRole.USER_GENERAL: "vector",
    LayerRole.BASE_REFERENCE: "vector",
    LayerRole.PENDING_REVIEW_AREA: "polygon",
    LayerRole.LEGACY_UNCLASSIFIED: "vector",
}

_ROLE_FOR_LAYER_TYPE: dict[str, LayerRole] = {
    # default (typical) role for each runtime document type; a layer's true
    # role always lives in its membership record — this is the type-level
    # binding, not a per-layer classification.
    "vector": LayerRole.USER_GENERAL,
    "grid": LayerRole.FACTOR_GRID,
    "contour": LayerRole.FACTOR_CONTOUR,
    "well_point": LayerRole.FACTOR_INPUT,
    "polygon": LayerRole.INITIAL_FACIES_DRAFT,
    "facies": LayerRole.INITIAL_FACIES_SOURCE,
    "raster": LayerRole.BASE_REFERENCE,
    "scalar_grid": LayerRole.FACTOR_GRID,
    "raster_source": LayerRole.BASE_REFERENCE,
    "annotation": LayerRole.MAP_ANNOTATION,
}


def layer_type_for_role(role: LayerRole | str) -> Any:
    """Primary runtime LayerType for a role (import kept local to avoid a
    mapping→ui dependency cycle; LayerType is a plain str enum)."""
    from paleo_workbench.mapping.layers import LayerType

    key = LayerRole(role) if not isinstance(role, LayerRole) else role
    return LayerType(_LAYER_TYPE_FOR_ROLE[key])


def role_for_layer_type(layer_type: Any) -> LayerRole | None:
    from paleo_workbench.mapping.layers import LayerType

    value = layer_type.value if isinstance(layer_type, LayerType) else str(
        layer_type)
    return _ROLE_FOR_LAYER_TYPE.get(value)
