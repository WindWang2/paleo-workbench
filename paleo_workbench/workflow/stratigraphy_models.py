"""Typed scientific models for multi-well stratigraphic correlation (Stage 12).

Display state (viewport, track style) does not belong here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from paleo_workbench.project.models import _id, _now_iso


class DepthDomain(str, Enum):
    """Domains actually appearing in code (no fake converters)."""

    MD = "MD"
    TVD = "TVD"
    TVDSS = "TVDSS"
    TWT = "TWT"
    DEPTH = "DEPTH"
    TIME = "TIME"  # seismic-aligned vertical when shared as string


class CorrelationMethod(str, Enum):
    MANUAL = "MANUAL"
    DTW_ASSISTED = "DTW_ASSISTED"
    CURVE_SHAPE_ASSISTED = "CURVE_SHAPE_ASSISTED"
    IMPORTED = "IMPORTED"


class FormationTop(BaseModel):
    """One stratigraphic pick on one well."""

    id: str = Field(default_factory=lambda: _id("top"))
    well_id: str = ""  # ResourceItem.id when known
    well_name: str = ""
    marker: str  # stratigraphic marker / horizon name
    depth: float
    depth_domain: DepthDomain = DepthDomain.MD
    confidence: str = ""  # free text; geological scale is EXPERT_CONFIRMATION
    status: str = "active"  # active | rejected | tentative
    method: CorrelationMethod = CorrelationMethod.IMPORTED
    notes: str = ""


class CorrelationLink(BaseModel):
    """Stable scientific link between two formation tops."""

    id: str = Field(default_factory=lambda: _id("clink"))
    top_a_id: str
    top_b_id: str
    well_a_id: str = ""
    well_b_id: str = ""
    method: CorrelationMethod = CorrelationMethod.MANUAL
    adjacent_only: bool = True  # topology hint from current section ordering
    notes: str = ""


class CorrelationScientificPayload(BaseModel):
    """Portable scientific body of a correlation interpretation version.

    Does not embed well-curve samples — wells referenced by version/resource IDs.
    """

    schema_version: int = 1
    interpretation_id: str
    name: str = ""
    framework_ref: str = ""  # stratigraphy scheme name if any
    depth_domain: DepthDomain = DepthDomain.MD
    well_resource_ids: list[str] = Field(default_factory=list)
    well_version_ids: list[str] = Field(default_factory=list)
    curve_names: list[str] = Field(default_factory=list)  # scientific curves if selected
    tops: list[FormationTop] = Field(default_factory=list)
    links: list[CorrelationLink] = Field(default_factory=list)
    method_summary: list[str] = Field(default_factory=list)
    notes: str = ""
    parent_version_id: str | None = None
    created_at: str = Field(default_factory=_now_iso)

    def scientific_dict(self) -> dict[str, Any]:
        """Canonical dict for fingerprinting (display-free).

        parent_version_id is lineage bookkeeping, not scientific content —
        exclude it so no-op saves stay stable after tip advancement.
        """
        return {
            "schema_version": self.schema_version,
            "interpretation_id": self.interpretation_id,
            "name": self.name,
            "framework_ref": self.framework_ref,
            "depth_domain": self.depth_domain.value,
            "well_resource_ids": list(self.well_resource_ids),
            "well_version_ids": list(self.well_version_ids),
            "curve_names": list(self.curve_names),
            "tops": [
                t.model_dump(mode="json")
                for t in sorted(self.tops, key=lambda x: (x.well_id, x.marker, x.depth, x.id))
            ],
            "links": [
                ln.model_dump(mode="json")
                for ln in sorted(self.links, key=lambda x: (x.top_a_id, x.top_b_id, x.id))
            ],
            "method_summary": list(self.method_summary),
            "notes": self.notes,
        }


class CorrelationInterpretationDraft(BaseModel):
    """Mutable working copy (copy-on-edit)."""

    interpretation_id: str = Field(default_factory=lambda: _id("corr"))
    name: str = "连井对比"
    payload: CorrelationScientificPayload
    generation: int = 0
    dirty: bool = True
    last_saved_fingerprint: str = ""
    display: dict[str, Any] = Field(default_factory=dict)  # never fingerprinted

    def bump(self) -> None:
        self.generation += 1
        self.dirty = True


# CorrelationInterpretationRef / FaultInterpretationRef live on project.models
# for ProjectDocument persistence (same pattern as HorizonInterpretationRef).


class FaultTrace(BaseModel):
    """Scientific fault geometry (map-plane polyline); not screen coordinates."""

    id: str = Field(default_factory=lambda: _id("ftrace"))
    name: str = ""
    # Open polyline [[x,y], ...] in project CRS
    polyline: list[list[float]] = Field(default_factory=list)
    role: Literal["break", "fault", "other"] = "fault"
    vertical_domain: str = ""  # empty = map-plane only
    notes: str = ""


class FaultInterpretationPayload(BaseModel):
    schema_version: int = 1
    interpretation_id: str
    name: str = ""
    traces: list[FaultTrace] = Field(default_factory=list)
    source_version_ids: list[str] = Field(default_factory=list)
    parent_version_id: str | None = None
    crs: str = ""
    notes: str = ""

    def scientific_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "interpretation_id": self.interpretation_id,
            "name": self.name,
            "traces": [
                t.model_dump(mode="json")
                for t in sorted(self.traces, key=lambda x: (x.name, x.id))
            ],
            "source_version_ids": list(self.source_version_ids),
            "crs": self.crs,
            "notes": self.notes,
        }


class FaultInterpretationDraft(BaseModel):
    interpretation_id: str = Field(default_factory=lambda: _id("fault"))
    name: str = "断层解释"
    payload: FaultInterpretationPayload
    generation: int = 0
    dirty: bool = True
    last_saved_fingerprint: str = ""
    display: dict[str, Any] = Field(default_factory=dict)

    def bump(self) -> None:
        self.generation += 1
        self.dirty = True


