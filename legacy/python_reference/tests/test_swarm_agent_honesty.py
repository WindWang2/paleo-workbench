"""#1143 (+extension): swarm stub agents must not fabricate QC/provenance/delivery claims."""
from __future__ import annotations

from types import SimpleNamespace

from paleo_workbench.agent.agents.carto_agent import CartographyAgent
from paleo_workbench.agent.agents.data_agent import DataAgent
from paleo_workbench.agent.agents.gis_agent import GISAgent
from paleo_workbench.agent.agents.qa_agent import QAAgent
from paleo_workbench.agent.agents.result_agent import ResultAgent
from paleo_workbench.agent.agents.seismic_agent import SeismicAgent
from paleo_workbench.agent.agents.viz_agent import VisualizationAgent
from paleo_workbench.agent.agents.well_agent import WellAgent
from paleo_workbench.agent.planner import TaskNode
from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument


def _node(agent: str) -> TaskNode:
    return TaskNode(
        id=f"task_{agent}",
        agent_name=agent,
        action="run",
        description="honesty regression",
    )


def test_qa_agent_reports_unverified_not_passed() -> None:
    out = QAAgent().run(_node("qa_agent"), {})
    assert out["status"] == "success"  # node executed; not a QC verdict
    assert out["passed"] is False
    assert out.get("stub") is True
    audit = out["audit"]
    assert audit["quality_score"] is None
    assert "Ready for publication" not in str(out)


def test_result_agent_reports_no_deliverables() -> None:
    out = ResultAgent().run(_node("result_agent"), {})
    assert out["status"] == "success"
    assert out["deliverables_ready"] is False
    assert out["report"]["lineage_tracked"] is False
    assert out["report"].get("stub") is True
    assert "2026-08-23" not in str(out)


def test_data_agent_lists_assets_without_claiming_verification() -> None:
    project = SimpleNamespace(
        resources=[
            SimpleNamespace(id="r1", name="A12.Las", type="well_log", path="wells/A12.Las"),
            SimpleNamespace(id="r2", name="D63.dat", type="horizon", path="horizons/D63.dat"),
        ]
    )
    out = DataAgent().run(_node("data_agent"), {"project": project})
    assert out["status"] == "success"
    assert out["assets_count"] == 2  # real enumeration is kept
    assert out["catalog_verified"] is False
    assert "SHA-256" not in str(out).replace("未执行 SHA-256 校验", "")


def test_well_agent_does_not_fabricate_wells() -> None:
    project = ProjectDocument.new("P")
    project.wells.append(
        WellEntity(name="REAL-1", surface_x=1.0, surface_y=2.0,
                   project_x=500000.0, project_y=4400000.0)
    )
    out = WellAgent().run(_node("well_agent"), {"project": project})
    assert out["status"] == "success"
    assert out.get("stub") is True
    names = [str(p.get("well", "")) for p in out["well_points"]]
    assert not {"W1", "W2", "W3", "W4"} & set(names)
    assert "REAL-1" in names
    assert out["correlated_well_count"] == len(out["well_points"])


def test_well_agent_without_project_returns_empty_points() -> None:
    out = WellAgent().run(_node("well_agent"), {})
    assert out["status"] == "success"
    assert out["well_points"] == []
    assert out["correlated_well_count"] == 0


# ------------------------------------------- #1143 extension: 4 more agents --
def test_gis_agent_marks_fault_barriers_synthetic_and_unverified() -> None:
    out = GISAgent().run(_node("gis_agent"), {})
    assert out["status"] == "success"  # node executed; not a verification verdict
    assert out["stub"] is True
    # The old agent claimed "topology verified and sealed" — never again.
    assert out["topology_verified"] is False
    assert out["fault_barriers_source"] == "synthetic_demo"
    assert out["barrier_count"] == len(out["fault_barriers"])


def test_carto_agent_marks_grid_synthetic_not_interpolated() -> None:
    out = CartographyAgent().run(_node("carto_agent"), {})
    assert out["status"] == "success"
    assert out["stub"] is True
    assert out["grid_source"] == "synthetic_demo"
    assert out["interpolated_from_wells"] is False
    assert out["grid_data"] is not None and out["grid_data"].size > 0


def test_seismic_agent_does_not_claim_loaded_volume_or_coherence() -> None:
    out = SeismicAgent().run(_node("seismic_agent"), {})
    assert out["status"] == "success"
    assert out["stub"] is True
    assert out["coherence_calculated"] is False  # was a fabricated True
    assert out["volume_loaded"] is False
    assert out["active_inline"] is None  # placeholder coords removed, not faked


def test_viz_agent_selects_template_but_claims_no_placement_or_export() -> None:
    out = VisualizationAgent().run(_node("viz_agent"), {})
    assert out["status"] == "success"
    assert out["stub"] is True
    # Template/palette selection is real; placement and export never ran.
    assert out["layout_template"]
    assert out["template_elements"]  # what the template WOULD include
    assert out["elements_placed"] == []
    assert out["export_formats_ready"] == []
