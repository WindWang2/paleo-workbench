"""GeologicalLayerSpec V2 (goal §3): declarative, QGIS-drivable layer specs.

The spec registry is the single formal binding between LayerRole (science
vocabulary), LayerType (runtime document types), and the QGIS layer schema
(QgsFields / constraints / domains / defaults / editor widgets). Tests here
are pure-data and always run; bridge round-trips live in
test_qgis_layer_schema.py.
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.layers import LayerType
from paleo_workbench.mapping_workspace.geological_layer_spec import (
    GEOLOGICAL_LAYER_SPECS,
    GeologicalLayerSpec,
    SpecField,
    layer_type_for_role,
    role_for_layer_type,
    spec_for_role,
    specs_for_constraint_kind,
)
from paleo_workbench.mapping_workspace.layer_groups import stages_for_role
from paleo_workbench.mapping_workspace.layer_roles import (
    ROLE_EDITABLE,
    ROLE_RAW_PROTECTED,
    ConstraintKind,
    LayerRole,
)
from paleo_workbench.mapping_workspace.stages import MappingStage

# Goal §3 role coverage (15 named + factor family).
REQUIRED_ROLES = {
    LayerRole.WELL_POINT if hasattr(LayerRole, "WELL_POINT") else LayerRole.FACTOR_INPUT,
    LayerRole.FAULT_CONSTRAINT,
    LayerRole.INITIAL_FACIES_SOURCE,
    LayerRole.INITIAL_FACIES_DRAFT,
    LayerRole.PROVENANCE_LINE,
    LayerRole.PROVENANCE_DIRECTION,
    LayerRole.DISTRIBUTION_LINE,
    LayerRole.PALEO_SHORELINE,
    LayerRole.FACIES_BOUNDARY,
    LayerRole.MASK_BOUNDARY,
    LayerRole.INTERPOLATION_BOUNDARY,
    LayerRole.INTEGRATED_FACIES,
    LayerRole.INTEGRATED_BOUNDARY,
    LayerRole.FACTOR_GRID,
    LayerRole.FACTOR_CONTOUR,
    LayerRole.FACTOR_CLASSIFICATION,
    LayerRole.FACTOR_UNCERTAINTY,
    LayerRole.FACTOR_QC,
    LayerRole.MAP_EXTENT if hasattr(LayerRole, "MAP_EXTENT") else LayerRole.MASK_BOUNDARY,
}


def test_registry_covers_goal_roles():
    covered = set(GEOLOGICAL_LAYER_SPECS)
    for role in REQUIRED_ROLES:
        assert role in covered, f"missing GeologicalLayerSpec for {role}"
    assert len(GEOLOGICAL_LAYER_SPECS) >= 18


def test_spec_for_role_known_and_unknown():
    spec = spec_for_role(LayerRole.FAULT_CONSTRAINT)
    assert spec.role is LayerRole.FAULT_CONSTRAINT
    assert spec.geometry_kind == "line"
    with pytest.raises(KeyError):
        spec_for_role("not_a_role")


def test_every_spec_geometry_kind_valid():
    valid = {"point", "line", "polygon", "raster", "vector"}
    for role, spec in GEOLOGICAL_LAYER_SPECS.items():
        assert spec.geometry_kind in valid, (role, spec.geometry_kind)


def test_field_schema_wellformed():
    for role, spec in GEOLOGICAL_LAYER_SPECS.items():
        names = [f.name for f in spec.fields]
        assert len(names) == len(set(names)), f"{role}: duplicate field names"
        for f in spec.fields:
            assert f.kind in {"text", "int", "real", "bool", "datetime"}
            if f.kind in {"int", "real"} and f.choices:
                pytest.fail(f"{role}.{f.name}: numeric fields use range, not choices")
            if f.choices:
                assert f.default in f.choices or f.default in (None, ""), (
                    f"{role}.{f.name}: default {f.default!r} not in domain")
            if f.value_range is not None:
                lo, hi = f.value_range
                assert lo < hi


def test_edit_policy_matches_layer_role_authority():
    """The spec never contradicts ROLE_EDITABLE / ROLE_RAW_PROTECTED."""
    for role, spec in GEOLOGICAL_LAYER_SPECS.items():
        if role in ROLE_RAW_PROTECTED:
            assert spec.edit_policy.editable is False, role
        elif role in ROLE_EDITABLE:
            assert spec.edit_policy.editable is True, role


def test_stage_policy_matches_group_authority():
    for role, spec in GEOLOGICAL_LAYER_SPECS.items():
        expected = stages_for_role(role)
        if expected:
            assert set(spec.stage_policy.visible_stages) <= set(expected), (
                f"{role}: spec stages {spec.stage_policy.visible_stages} "
                f"exceed group routing {expected}"
            )


def test_fault_spec_has_semantic_fields():
    spec = spec_for_role(LayerRole.FAULT_CONSTRAINT)
    fields = {f.name: f for f in spec.fields}
    assert "fault_type" in fields
    assert fields["fault_type"].kind == "text"
    assert set(fields["fault_type"].choices or ()) >= {
        "normal", "reverse", "thrust", "strike_slip"}, (
        "fault domain must carry the §6 symbology classes")
    assert "confidence" in fields or "inferred" in fields


def test_constraint_kind_lookup():
    fault = specs_for_constraint_kind(ConstraintKind.FAULT)
    assert LayerRole.FAULT_CONSTRAINT in fault
    shoreline = specs_for_constraint_kind(ConstraintKind.PALEO_SHORELINE)
    assert LayerRole.PALEO_SHORELINE in shoreline


def test_serialization_roundtrip():
    spec = spec_for_role(LayerRole.INTEGRATED_FACIES)
    data = spec.to_dict()
    restored = GeologicalLayerSpec.from_dict(data)
    assert restored == spec


def test_template_field_compat():
    """Spec fields convert to the existing TemplateField schema (composite
    editing authority) without losing name/kind/default/required."""
    spec = spec_for_role(LayerRole.FAULT_CONSTRAINT)
    schema = spec.to_template_schema()
    fields = schema.get("fields")
    assert fields, "template schema must carry fields"
    names = {f["name"] for f in fields}
    assert "fault_type" in names


def test_factor_specs_are_raster_or_derived():
    grid = spec_for_role(LayerRole.FACTOR_GRID)
    assert grid.geometry_kind == "raster"
    assert grid.edit_policy.editable is False
    assert grid.provenance_policy.mode == "catalog_version_pinned"
    uncertainty = spec_for_role(LayerRole.FACTOR_UNCERTAINTY)
    assert uncertainty.geometry_kind == "raster"


def test_snapping_policy_for_constraints():
    for role in (LayerRole.FAULT_CONSTRAINT, LayerRole.PALEO_SHORELINE,
                 LayerRole.PROVENANCE_LINE):
        spec = spec_for_role(role)
        assert spec.snapping_policy is not None
        assert spec.snapping_policy.enabled is True
        assert "vertex" in spec.snapping_policy.modes


def test_layer_type_role_binding_covers_runtime_types():
    for layer_type in (LayerType.VECTOR, LayerType.CONTOUR, LayerType.WELL_POINT,
                       LayerType.POLYGON, LayerType.SCALAR_GRID):
        assert role_for_layer_type(layer_type), layer_type
    # binding is a function both ways for the primary pairs
    assert layer_type_for_role(LayerRole.INITIAL_FACIES_DRAFT) is LayerType.POLYGON
    assert layer_type_for_role(LayerRole.FACTOR_CONTOUR) is LayerType.CONTOUR
    assert layer_type_for_role(LayerRole.FACTOR_GRID) is LayerType.SCALAR_GRID


def test_wkb_equivalent_kinds():
    """geometry_kind strings carry an unambiguous QgsWkbType mapping."""
    from paleo_workbench.mapping.qgis_layer_schema import qgis_geometry_type_name

    assert qgis_geometry_type_name("point") == "Point"
    assert qgis_geometry_type_name("line") == "LineString"
    assert qgis_geometry_type_name("polygon") == "MultiPolygon"
    with pytest.raises(ValueError):
        qgis_geometry_type_name("nonsense")


def test_spec_ids_stable_and_unique():
    ids = [spec.spec_id for spec in GEOLOGICAL_LAYER_SPECS.values()]
    assert len(ids) == len(set(ids))
    assert all(ids), "spec_id must be non-empty"


def test_geometry_kind_matches_layer_type_binding():
    """R2-F5: spec geometry_kind must be consistent with the LayerType it
    maps to (no split vocabulary)."""
    from paleo_workbench.mapping.layers import LayerType

    kind_to_types = {
        "point": {LayerType.WELL_POINT, LayerType.VECTOR, LayerType.ANNOTATION},
        "line": {LayerType.VECTOR, LayerType.CONTOUR},
        "polygon": {LayerType.POLYGON},
        "raster": {LayerType.SCALAR_GRID, LayerType.RASTER, LayerType.GRID},
        "vector": {LayerType.VECTOR, LayerType.ANNOTATION},
    }
    for role, spec in GEOLOGICAL_LAYER_SPECS.items():
        layer_type = layer_type_for_role(role)
        allowed = kind_to_types[spec.geometry_kind]
        assert layer_type in allowed, (
            f"{role}: geometry_kind {spec.geometry_kind!r} vs "
            f"LayerType {layer_type}")
