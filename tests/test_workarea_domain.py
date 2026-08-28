"""WorkArea domain model, registries, resolution and migration tests."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt

import pytest

from paleo_workbench.catalog.domain_binding import (
    BindingReport,
    WellExtract,
    SurveyExtract,
    bind_survey_extract,
    bind_well_extracts,
    project_coordinates,
)
from paleo_workbench.project.domain import (
    CoordinateStatus,
    DomainEntity,
    set_well_identity_override,
    well_identity_overrides,
    EntityAssetLink,
    SeismicSurveyEntity,
    WellEntity,
    WorkArea,
    ensure_workarea,
    links_for_asset,
    links_for_entity,
    normalize_well_name,
    resolve_well,
    sync_workarea_with_coordinate,
    upsert_entity_asset_link,
    well_registry,
)
from paleo_workbench.project.domain_migration import (
    SCHEMA_VERSION_WORKAREA,
    migrate_project_to_workarea,
    project_needs_domain_migration,
)
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument, ResourceItem


# --------------------------------------------------------------------------- helpers


def make_project(name: str = "T") -> ProjectDocument:
    return ProjectDocument.new(name=name)


class _FakePrepared:
    def __init__(self, payload):
        self.payload = payload
        self.warning = ""


# NOTE: named exactly like the geoviz payload so duck-type guards accept it.
class XYPreviewPayload:
    def __init__(self, names, xs, ys, source_crs="", coordinate_units=""):
        self.names = tuple(names)
        self.x = xs
        self.y = ys
        self.record_ids = tuple(range(len(names)))
        self.source_rows = tuple(range(1, len(names) + 1))
        self.source_version = "checksum:abc|stat:1:2"
        self.source_crs = source_crs
        self.coordinate_units = coordinate_units


_FakeXYPreviewPayload = XYPreviewPayload  # backwards-friendly alias within tests


class _FakeEngine:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list = []

    def prepare(self, request, options):  # noqa: ARG002
        self.calls.append(request)
        return _FakePrepared(self._payload)


# --------------------------------------------------------------------------- model


class TestWorkAreaModel:
    def test_new_project_has_no_workarea_and_schema_v1(self):
        doc = make_project()
        assert doc.schema_version == 1
        assert doc.workarea is None
        assert doc.wells == []
        assert doc.seismic_surveys == []
        assert doc.entity_asset_links == []

    def test_ensure_workarea_creates_from_meta_and_coordinate(self):
        doc = make_project("盆地A")
        doc.coordinate.project_crs = "EPSG:4490"
        workarea = ensure_workarea(doc)
        assert workarea.name == "盆地A"
        assert workarea.project_crs == "EPSG:4490"
        # Idempotent: same object returned.
        assert ensure_workarea(doc) is workarea
        assert len(doc.workarea.id) > 3

    def test_sync_projects_coordinate_into_workarea(self):
        doc = make_project()
        workarea = ensure_workarea(doc)
        doc.coordinate.project_crs = "EPSG:4546"
        doc.coordinate.display_crs = "EPSG:4326"
        assert sync_workarea_with_coordinate(doc) is True
        assert workarea.project_crs == "EPSG:4546"
        assert workarea.display_crs == "EPSG:4326"
        assert sync_workarea_with_coordinate(doc) is False

    def test_document_roundtrip_preserves_domain_sections(self, tmp_path: Path):
        doc = make_project()
        doc.workarea = WorkArea(name="工区1", project_crs="EPSG:4326")
        well = WellEntity(
            name="W1", uwi="U-001", aliases=["w 1"], surface_x=1.5, surface_y=2.5,
            project_x=1.5, project_y=2.5, coordinate_status=CoordinateStatus.OK,
        )
        doc.wells.append(well)
        doc.seismic_surveys.append(
            SeismicSurveyEntity(name="S1", inline_range=[100, 200, 1])
        )
        doc.geological_entities.append(DomainEntity(name="H1", kind="geological"))
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id=well.id, asset_id="asset_1", role="well_head",
            is_primary=True,
        )
        doc.schema_version = SCHEMA_VERSION_WORKAREA
        raw = json.loads(doc.model_dump_json())
        restored = ProjectDocument.model_validate(raw)
        assert restored.schema_version == SCHEMA_VERSION_WORKAREA
        assert restored.workarea.name == "工区1"
        assert restored.wells[0].uwi == "U-001"
        assert restored.seismic_surveys[0].inline_range == [100, 200, 1]
        assert restored.entity_asset_links[0].asset_id == "asset_1"

    def test_legacy_json_without_domain_fields_loads(self):
        legacy = {
            "meta": {"name": "old"},
            "resources": [
                {"id": "res_1", "name": "a.dat", "path": "a.dat", "type": "well_head", "format": "dat"}
            ],
        }
        doc = ProjectDocument.model_validate(legacy)
        assert doc.meta.name == "old"
        assert doc.workarea is None
        assert doc.wells == []
        assert doc.schema_version == 1


# --------------------------------------------------------------------------- identity


class TestIdentityNormalization:
    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("W-01", "w 01"),
            ("W_01", "W－01"),  # full-width dash
            ("  well A ", "Well A"),
            ("井A（东）", "井A(东)"),
        ],
    )
    def test_equivalent_names(self, left, right):
        assert normalize_well_name(left) == normalize_well_name(right)

    def test_distinct_names_never_collide(self):
        assert normalize_well_name("W-01") != normalize_well_name("W-02")
        assert normalize_well_name("") == ""


class TestResolveWell:
    def _project_with(self, *wells: WellEntity) -> ProjectDocument:
        doc = make_project()
        doc.wells.extend(wells)
        return doc

    def test_persisted_id_first(self):
        w1 = WellEntity(name="A")
        w2 = WellEntity(name="B")
        doc = self._project_with(w1, w2)
        outcome = resolve_well(doc, name="B", well_id=w1.id)
        assert outcome.matched and outcome.strategy == "persisted_id"
        assert outcome.well_id == w1.id

    def test_uwi_beats_name(self):
        by_uwi = WellEntity(name="X", uwi="U-9")
        by_name = WellEntity(name="Y")
        doc = self._project_with(by_uwi, by_name)
        outcome = resolve_well(doc, name="Y", uwi="u-9")
        assert outcome.matched and outcome.strategy == "uwi"
        assert outcome.well_id == by_uwi.id

    def test_canonical_name_match(self):
        w = WellEntity(name="W-01")
        doc = self._project_with(w)
        outcome = resolve_well(doc, name="w 01")
        assert outcome.matched and outcome.strategy == "canonical_name"

    def test_alias_match(self):
        w = WellEntity(name="W-01", aliases=["老井1"])
        doc = self._project_with(w)
        outcome = resolve_well(doc, name="老井１")  # full-width digit via NFKC
        assert outcome.matched

    def test_ambiguous_never_silent_merge(self):
        doc = self._project_with(WellEntity(name="Dup"), WellEntity(name="dup"))
        outcome = resolve_well(doc, name="DUP")
        assert outcome.ambiguous
        assert sorted(outcome.candidates) == sorted(w.id for w in doc.wells)

    def test_no_match(self):
        doc = self._project_with(WellEntity(name="A"))
        outcome = resolve_well(doc, name="Zzz")
        assert not outcome.matched and not outcome.ambiguous


# --------------------------------------------------------------------------- links


class TestEntityAssetLinks:
    def test_upsert_is_idempotent(self):
        doc = make_project()
        link1, created1 = upsert_entity_asset_link(
            doc, entity_type="well", entity_id="w1", asset_id="a1", role="well_log"
        )
        link2, created2 = upsert_entity_asset_link(
            doc, entity_type="well", entity_id="w1", asset_id="a1", role="well_log"
        )
        assert created1 and not created2
        assert link1 is link2
        assert len(doc.entity_asset_links) == 1

    def test_primary_demotes_siblings_same_role(self):
        doc = make_project()
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id="w1", asset_id="a1", role="well_head", is_primary=True
        )
        link2, _ = upsert_entity_asset_link(
            doc, entity_type="well", entity_id="w1", asset_id="a2", role="well_head", is_primary=True
        )
        links = links_for_entity(doc, "well", "w1")
        primaries = [link for link in links if link.is_primary]
        assert len(primaries) == 1 and primaries[0].asset_id == "a2"

    def test_different_roles_keep_separate_primaries(self):
        doc = make_project()
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id="w1", asset_id="a1", role="well_head", is_primary=True
        )
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id="w1", asset_id="a2", role="well_log", is_primary=True
        )
        assert len([link for link in doc.entity_asset_links if link.is_primary]) == 2

    def test_lookup_helpers(self):
        doc = make_project()
        upsert_entity_asset_link(doc, entity_type="well", entity_id="w1", asset_id="a1")
        upsert_entity_asset_link(doc, entity_type="seismic_survey", entity_id="s1", asset_id="a1")
        upsert_entity_asset_link(doc, entity_type="well", entity_id="w2", asset_id="a3")
        assert len(links_for_asset(doc, "a1")) == 2
        assert ("well", "w1") in [(t, e) for t, e in __import__(
            "paleo_workbench.project.domain", fromlist=["entity_ids_for_asset"]
        ).entity_ids_for_asset(doc, "a1")]
        # registry reads the wells list only — w1 exists solely as a link id
        assert well_registry(doc).by_id("w1") is None


# --------------------------------------------------------------------------- binding


class TestBindWells:
    def test_creates_entities_and_primary_link(self):
        doc = make_project()
        doc.coordinate.project_crs = "EPSG:4326"
        extracts = [
            WellExtract(name="W1", x=10.0, y=20.0),
            WellExtract(name="W2", x=11.0, y=21.0, source_crs="EPSG:4326"),
        ]
        report = bind_well_extracts(doc, extracts, asset_id="asset_a")
        assert report.wells_created == 2
        assert report.links_created == 2
        assert [w.name for w in doc.wells] == ["W1", "W2"]
        first = doc.wells[0]
        assert first.coordinate_status == CoordinateStatus.UNTRANSFORMED  # no declared CRS
        assert first.project_x == 10.0
        second = doc.wells[1]
        assert second.coordinate_status == CoordinateStatus.OK
        primary = [link for link in doc.entity_asset_links if link.is_primary]
        assert len(primary) == 2

    def test_reimport_matches_existing_no_duplicates(self):
        doc = make_project()
        bind_well_extracts(doc, [WellExtract(name="W-01", x=1.0, y=2.0)], asset_id="a1")
        report = bind_well_extracts(doc, [WellExtract(name="w 01 ", x=1.0, y=2.0)], asset_id="a2")
        assert report.wells_created == 0
        assert len(doc.wells) == 1

    def test_ambiguous_becomes_unresolved_links_not_merge(self):
        doc = make_project()
        bind_well_extracts(doc, [WellExtract(name="Dup", x=1, y=2)], asset_id="a1")
        # Second distinct asset claims same normalized name -> ambiguous pair.
        doc.wells.append(WellEntity(name="dup"))
        report = bind_well_extracts(doc, [WellExtract(name="DUP", x=9, y=9)], asset_id="a2")
        assert report.ambiguous_assets == 1
        unresolved = [link for link in doc.entity_asset_links if link.unresolved]
        assert len(unresolved) == 2
        merged = [link for link in doc.entity_asset_links if not link.unresolved]
        assert all(link.asset_id != "a2" for link in merged)

    def test_coordinate_transform_via_pyproj(self):
        pytest.importorskip("pyproj")
        px, py, status = project_coordinates(
            116.0, 39.0, source_crs="EPSG:4326", project_crs="EPSG:32650"
        )
        assert status == CoordinateStatus.OK
        # UTM 50N: easting below the 500000 false-easting for 116E, northing ~4.3Mm.
        assert 300000 < px < 500000
        assert 4_000_000 < py < 4_600_000

    def test_invalid_source_crs_stays_untransformed(self):
        px, py, status = project_coordinates(1.0, 2.0, source_crs="NOT-A-CRS", project_crs="EPSG:4326")
        assert status == CoordinateStatus.UNTRANSFORMED
        assert (px, py) == (1.0, 2.0)


class TestBindSurvey:
    def test_creates_survey_with_geometry(self):
        doc = make_project()
        extract = SurveyExtract(
            name="VOL3D",
            corners=[[0, 0], [100, 0], [100, 80]],
            inline_range=[10, 20, 1],
            crossline_range=[30, 60, 2],
            n_samples=750,
            dt_ms=2.0,
        )
        report = bind_survey_extract(doc, extract, asset_id="svy_asset")
        assert report.surveys_created == 1
        assert doc.seismic_surveys[0].inline_range == [10, 20, 1]
        assert doc.seismic_surveys[0].n_samples == 750
        assert doc.entity_asset_links[0].role == "seismic_volume"

    def test_second_volume_same_name_links_to_existing(self):
        doc = make_project()
        bind_survey_extract(doc, SurveyExtract(name="V-1"), asset_id="a1")
        report = bind_survey_extract(doc, SurveyExtract(name="v 1"), asset_id="a2")
        assert report.surveys_created == 0
        assert len(doc.seismic_surveys) == 1
        roles = sorted(link.asset_id for link in doc.entity_asset_links)
        assert roles == ["a1", "a2"]


# --------------------------------------------------------------------------- migration


class TestMigration:
    def _legacy_doc_with_well_head(self, tmp_path: Path) -> tuple[ProjectDocument, Path]:
        doc = make_project("legacy")
        dat = tmp_path / "wells.dat"
        dat.write_text(
            "#WellHead File From SMI\n"
            "#Name X Y\n"
            "W1 100 200\n"
            "W2 101 201\n",
            encoding="utf-8",
        )
        doc.resources.append(
            ResourceItem(
                id="res_wells", name="wells.dat", path=str(dat), type="well_head", format="dat"
            )
        )
        return doc, dat

    def test_legacy_project_migrates_deterministically(self, tmp_path: Path):
        doc, _ = self._legacy_doc_with_well_head(tmp_path)
        engine = _FakeEngine(_FakeXYPreviewPayload(["W1", "W2"], [100.0, 101.0], [200.0, 201.0]))
        report = migrate_project_to_workarea(
            doc,
            asset_id_by_legacy={"res_wells": "asset_wells"},
            project_path=tmp_path,
            engine=engine,
        )
        assert report.migrated and not report.already_migrated
        assert doc.schema_version == SCHEMA_VERSION_WORKAREA
        assert [w.name for w in doc.wells] == ["W1", "W2"]
        # Each discovered well gets its own explicit primary well_head link.
        assert len(doc.entity_asset_links) == 2
        assert all(link.is_primary for link in doc.entity_asset_links)
        assert doc.workarea is not None
        # Legacy resources untouched:
        assert doc.resources[0].id == "res_wells"

    def test_second_run_is_idempotent(self, tmp_path: Path):
        doc, _ = self._legacy_doc_with_well_head(tmp_path)
        engine = _FakeEngine(_FakeXYPreviewPayload(["W1", "W2"], [100.0, 101.0], [200.0, 201.0]))
        migrate_project_to_workarea(
            doc, asset_id_by_legacy={"res_wells": "asset_wells"}, project_path=tmp_path, engine=engine
        )
        snapshot = [(w.name, w.surface_x) for w in doc.wells]
        report2 = migrate_project_to_workarea(
            doc, asset_id_by_legacy={"res_wells": "asset_wells"}, project_path=tmp_path, engine=engine
        )
        assert report2.already_migrated
        assert [(w.name, w.surface_x) for w in doc.wells] == snapshot

    def test_migration_without_catalog_still_discovers_entities(self, tmp_path: Path):
        doc, _ = self._legacy_doc_with_well_head(tmp_path)
        engine = _FakeEngine(_FakeXYPreviewPayload(["W1"], [100.0], [200.0]))
        report = migrate_project_to_workarea(doc, project_path=tmp_path, engine=engine)
        assert report.migrated
        assert len(doc.wells) == 1
        assert doc.entity_asset_links == []  # no asset ids yet; later pass binds

    def test_parse_failure_does_not_raise(self, tmp_path: Path):
        doc, _ = self._legacy_doc_with_well_head(tmp_path)

        class _Boom(_FakeEngine):
            def prepare(self, request, options):
                raise RuntimeError("boom")

        boom = _Boom(None)
        report = migrate_project_to_workarea(
            doc, asset_id_by_legacy={"res_wells": "a"}, project_path=tmp_path, engine=boom
        )
        assert report.migrated
        assert any("RuntimeError" in issue for issue in report.binding.issues)
        assert doc.wells == []

    def test_missing_source_file_reported_not_fatal(self, tmp_path: Path):
        doc, dat = self._legacy_doc_with_well_head(tmp_path)
        dat.unlink()
        report = migrate_project_to_workarea(
            doc,
            asset_id_by_legacy={"res_wells": "a"},
            project_path=tmp_path,
            engine=_FakeEngine(XYPreviewPayload([], [], [])),
        )
        assert report.migrated
        assert any("不存在" in issue for issue in report.binding.issues)

    def test_needs_migration_predicate(self):
        doc = make_project()
        assert project_needs_domain_migration(doc)
        ensure_workarea(doc)
        assert not project_needs_domain_migration(doc)


# --------------------------------------------------------------------------- review fixes


class TestReviewFixes:
    def test_registry_by_key_returns_none_on_ambiguity(self):
        from paleo_workbench.project.domain import well_registry

        doc = make_project()
        doc.wells.append(WellEntity(name="Dup"))
        doc.wells.append(WellEntity(name="dup"))
        registry = well_registry(doc)
        assert registry.by_key("DUP") is None  # never silent first-wins
        # a name absent from the registry resolves to None
        assert registry.by_key("W-01") is None

    def test_staged_pipeline_matches_sync_pipeline(self, tmp_path):
        """Worker staging + GUI binding must equal the synchronous path."""
        from paleo_workbench.catalog.domain_binding import (
            bind_resources,
            bind_staged,
            stage_resources,
        )

        dat = tmp_path / "wells.dat"
        dat.write_text("x", encoding="utf-8")
        resource = ResourceItem(
            id="res_x", name="wells.dat", path=str(dat), type="well_head", format="dat"
        )
        engine = _FakeEngine(XYPreviewPayload(["S1", "S2"], [1.0, 2.0], [3.0, 4.0]))

        doc_a = make_project()
        report_a = bind_resources(
            doc_a,
            [resource],
            asset_id_by_legacy={"res_x": "a"},
            path_resolver=lambda p: Path(p),
            engine=engine,
        )
        doc_b = make_project()
        staged = stage_resources(
            doc_b,
            [resource],
            path_resolver=lambda p: Path(p),
            engine=engine,
        )
        report_b = bind_staged(doc_b, staged, asset_id_by_legacy={"res_x": "a"})
        assert [w.name for w in doc_a.wells] == [w.name for w in doc_b.wells]
        assert len(doc_a.entity_asset_links) == len(doc_b.entity_asset_links)
        assert report_a.wells_created == report_b.wells_created

    def test_stage_resources_missing_file_reports_issue(self, tmp_path):
        from paleo_workbench.catalog.domain_binding import stage_resources

        resource = ResourceItem(
            id="res_gone", name="gone.dat", path=str(tmp_path / "nope.dat"),
            type="well_head", format="dat",
        )
        staged = stage_resources(
            make_project(), [resource], path_resolver=lambda p: Path(p)
        )
        assert staged and any("不存在" in issue for issue in staged[0].issues)

    def test_domain_signature_covers_coordinate_changes(self):
        from paleo_workbench.project.domain import domain_signature

        doc = make_project()
        ensure_workarea(doc)
        sig1 = domain_signature(doc)
        doc.coordinate.project_crs = "EPSG:4490"
        assert domain_signature(doc) != sig1
        well = WellEntity(name="W", project_x=1, project_y=2, coordinate_status="ok")
        doc.wells.append(well)
        sig2 = domain_signature(doc)
        well.coordinate_status = "untransformed"
        assert domain_signature(doc) != sig2

    def test_crs_equivalent_shared_helper(self):
        from paleo_workbench.project.domain import crs_equivalent

        pytest.importorskip("pyproj")
        assert crs_equivalent("EPSG:4326", "epsg:4326")
        # pyproj CRS.equals semantics (exact identity first)
        assert crs_equivalent("EPSG:4326", "EPSG:4326") is True
        assert not crs_equivalent("EPSG:4326", "EPSG:32650")
        assert not crs_equivalent("", "EPSG:4326")

    def test_save_syncs_workarea_crs(self, tmp_path):
        """coordinate is canonical: save must refresh the workarea mirror."""
        doc = make_project("sync")
        ensure_workarea(doc)
        doc.coordinate.project_crs = "EPSG:4546"
        pf = tmp_path / "sync.paleo.json"
        ProjectManager(pf).save(doc)
        saved = json.loads(pf.read_text(encoding="utf-8"))
        assert saved["workarea"]["project_crs"] == "EPSG:4546"


class TestExplicitMapping:
    def test_explicit_mapping_is_last_resort(self):
        doc = make_project()
        well = WellEntity(name="A")
        doc.wells.append(well)
        ensure_workarea(doc)
        overrides = {"zzz": well.id}
        outcome = resolve_well(doc, name="zzz", overrides=overrides)
        assert outcome.matched and outcome.strategy == "explicit_mapping"
        # Automatic chain still wins over mapping.
        assert resolve_well(doc, name="A", overrides=overrides).strategy != "explicit_mapping"

    def test_uwi_key_override(self):
        doc = make_project()
        well = WellEntity(name="X")  # no stored uwi: automatic chain can't fire
        doc.wells.append(well)
        ensure_workarea(doc)
        overrides = {f"uwi:{normalize_well_name('LEGACY-77')}": well.id}
        outcome = resolve_well(doc, name="陌生名", uwi="legacy-77", overrides=overrides)
        assert outcome.matched and outcome.strategy == "explicit_mapping"

    def test_set_override_rejects_automatic_and_unknown_targets(self):
        doc = make_project()
        w1 = WellEntity(name="A")
        doc.wells.append(w1)
        ensure_workarea(doc)
        # Unknown target well → rejected.
        assert set_well_identity_override(doc, "whatever", "well_nope") is False
        # Key the automatic chain already resolves → rejected as dead weight.
        assert set_well_identity_override(doc, "A", w1.id) is False
        # Genuine governance case: alias-free mismatched name → accepted.
        assert set_well_identity_override(doc, "老档案名", w1.id) is True
        stored = well_identity_overrides(doc)
        assert stored[normalize_well_name("老档案名")] == w1.id
        # And resolution now flows through it.
        outcome = resolve_well(doc, name="老档案名")
        assert outcome.matched and outcome.strategy == "explicit_mapping"

    def test_binding_uses_governance_overrides(self):
        doc = make_project()
        w1 = WellEntity(name="W-01")
        doc.wells.append(w1)
        ensure_workarea(doc)
        set_well_identity_override(doc, "历史井名", w1.id)
        report = bind_well_extracts(
            doc, [WellExtract(name="历史井名", x=5.0, y=6.0)], asset_id="a9"
        )
        assert report.wells_created == 0
        assert report.links_created == 1
        assert [link.asset_id for link in links_for_entity(doc, "well", w1.id)] == ["a9"]


class TestFileSideUWI:
    """File-side UWI extraction (upstream payload ≥ gve 2a6b3bbf)."""

    def test_payload_uwis_feed_extraction(self):
        from paleo_workbench.catalog.domain_binding import _payload_wells

        payload = XYPreviewPayload(
            ["陌生名", "另一口"], [1.0, 2.0], [3.0, 4.0]
        )
        object.__setattr__(payload, "uwis", ("U-42", "-"))
        extracts = _payload_wells(payload)
        assert [e.uwi for e in extracts] == ["U-42", ""]
        assert extracts[0].name == "陌生名"

    def test_uwi_resolves_across_renamed_file(self):
        """UWI beats a changed display name: same physical well, no duplicate."""
        doc = make_project()
        doc.wells.append(WellEntity(name="旧名", uwi="U-42"))
        report = bind_well_extracts(
            doc,
            [WellExtract(name="文件里改叫新名了", x=9.0, y=9.0, uwi="u-42")],
            asset_id="a2",
        )
        assert report.wells_created == 0
        assert len(doc.wells) == 1
        # Geometry refreshed on the matched master record.
        assert doc.wells[0].surface_x == 9.0


class TestWellIdentityAdapter:
    """Canonical Well.id surface for legacy modules (ADR 0059 §7)."""

    def _adapter(self, doc, service=None):
        from paleo_workbench.project.well_identity_adapter import WellIdentityAdapter

        return WellIdentityAdapter(doc, service)

    def test_resolve_by_name_uwi_and_id(self):
        doc = make_project()
        well = WellEntity(name="W-01", uwi="U-9")
        doc.wells.append(well)
        adapter = self._adapter(doc)
        assert adapter.resolve(name="w 01") is well
        assert adapter.resolve(uwi="u-9") is well
        assert adapter.resolve(well_id=well.id) is well
        assert adapter.resolve(name="nope") is None
        assert adapter.display_name(well.id) == "W-01"

    def test_resource_bridge_through_links_and_legacy_ids(self):
        doc = make_project()
        well = WellEntity(name="W1")
        doc.wells.append(well)
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id=well.id, asset_id="asset_1",
            role="well_log", is_primary=True,
        )

        class Asset:
            id = "asset_1"
            legacy_resource_id = "res_1"

        class Service:
            def list_assets(self, include_trashed=False):  # noqa: ARG002
                return [Asset()]

        adapter = self._adapter(doc, Service())
        # Direct asset-id hit:
        assert adapter.well_ids_for_resource("asset_1") == [well.id]
        # Legacy resource-id bridged through the catalog map:
        assert adapter.well_for_resource("res_1") is well

    def test_ambiguous_resource_returns_none_not_silent_pick(self):
        doc = make_project()
        w1 = WellEntity(name="A")
        w2 = WellEntity(name="B")
        doc.wells.extend([w1, w2])
        for target in (w1, w2):
            upsert_entity_asset_link(
                doc, entity_type="well", entity_id=target.id, asset_id="shared_asset",
                role="other",
            )
        adapter = self._adapter(doc)
        assert adapter.well_for_resource("shared_asset") is None

    def test_invalidate_refreshes_index(self):
        doc = make_project()
        well = WellEntity(name="W1")
        doc.wells.append(well)
        adapter = self._adapter(doc)
        assert adapter.well_ids_for_resource("late_asset") == []
        upsert_entity_asset_link(
            doc, entity_type="well", entity_id=well.id, asset_id="late_asset"
        )
        adapter.invalidate()
        assert adapter.well_ids_for_resource("late_asset") == [well.id]

    def test_data_page_exposes_cached_adapter(self, qtbot):
        from paleo_workbench.ui.pages.data_page import DataPage

        page = DataPage(project=make_project())
        qtbot.addWidget(page)
        first = page.well_identity_adapter()
        second = page.well_identity_adapter()
        assert first is second


class TestGeologicalEntityBinding:
    """③ 地质/辅助实体：interpretation resources → DomainEntity + links."""

    def test_horizon_resource_creates_geological_entity(self, tmp_path):
        from paleo_workbench.catalog.domain_binding import bind_staged, stage_resources

        dat = tmp_path / "H1.dat"
        dat.write_text("x", encoding="utf-8")
        resource = ResourceItem(
            id="res_h1", name="H1", path=str(dat), type="horizon", format="dat"
        )
        doc = make_project()
        ensure_workarea(doc)
        staged = stage_resources(doc, [resource], path_resolver=lambda p: Path(p))
        report = bind_staged(doc, staged, asset_id_by_legacy={"res_h1": "asset_h"})
        assert report.entities_created == 1
        entity = doc.geological_entities[0]
        assert (entity.kind, entity.entity_kind) == ("geological", "horizon")
        link = doc.entity_asset_links[0]
        assert (link.entity_type, link.role) == ("geological_entity", "horizon")

    def test_rebind_is_idempotent(self, tmp_path):
        from paleo_workbench.catalog.domain_binding import bind_staged, stage_resources

        dat = tmp_path / "Tops.dat"
        dat.write_text("x", encoding="utf-8")
        resource = ResourceItem(
            id="res_t", name="Tops", path=str(dat), type="well_stratification", format="dat"
        )
        doc = make_project()
        ensure_workarea(doc)
        for _ in range(2):
            staged = stage_resources(doc, [resource], path_resolver=lambda p: Path(p))
            bind_staged(doc, staged, asset_id_by_legacy={"res_t": "a"})
        assert len(doc.geological_entities) == 1
        assert len(doc.entity_asset_links) == 1

    def test_tree_renders_geological_children(self, qtbot):
        from paleo_workbench.project.domain import DomainEntity as DE

        from paleo_workbench.ui.pages.navigation_tree import NavigationTree

        tree = NavigationTree()
        qtbot.addWidget(tree)
        doc = make_project()
        doc.seismic_surveys.clear()
        doc.geological_entities.append(DE(name="H1", kind="geological", entity_kind="horizon"))
        upsert_entity_asset_link(
            doc, entity_type="geological_entity", entity_id=doc.geological_entities[0].id,
            asset_id="ah", role="horizon",
        )
        tree.set_project(doc)
        geo = next(
            (tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
             if tree.topLevelItem(i).text(0).endswith("地质解释")),
            None,
        )
        assert geo is not None and geo.childCount() == 1
        query = geo.child(0).data(0, Qt.ItemDataRole.UserRole)
        assert query.node_type == "entity" and query.node_value.startswith("ent_")
