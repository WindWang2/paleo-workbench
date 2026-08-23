"""External XML well locations stay governed but outside the WorkArea scope."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.catalog.domain_binding import bind_resources
from paleo_workbench.project.domain import (
    CoordinateStatus,
    EntityAssetLink,
    WellEntity,
    WorkArea,
    is_reference_well,
)
from paleo_workbench.project.onboarding import boundary_from_wells
from paleo_workbench.project.well_location_map import sync_well_location_map
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.resources.import_service import import_files
from paleo_workbench.resources.well_location_xml import extract_well_locations_xml


def _external_well_xml(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<WellLocations crs="EPSG:4326">
  <Well><WellName>REF-01</WellName><X>120.0</X><Y>30.0</Y></Well>
  <Well><WellName>REF-02</WellName><X>121.0</X><Y>31.0</Y></Well>
</WellLocations>
""",
        encoding="utf-8",
    )
    return path


def _witsml_well_xml(path: Path, well_name: str = "XML-REF-01") -> Path:
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<WITSMLComposite xmlns="http://www.witsml.org/schemas/1series">
  <log>
    <nameWell>{well_name}</nameWell>
    <logCurveInfo><mnemonic>DEPT</mnemonic><unit>m</unit></logCurveInfo>
    <logCurveInfo><mnemonic>GR</mnemonic><unit>gAPI</unit></logCurveInfo>
    <logData><data>1000.0, 40.0</data><data>1000.125, 45.0</data></logData>
  </log>
</WITSMLComposite>
""",
        encoding="utf-8",
    )
    return path


def _project_with_boundary() -> ProjectDocument:
    project = ProjectDocument.new("测区")
    project.coordinate.project_crs = "EPSG:4326"
    project.workarea = WorkArea(
        name="测区",
        project_crs="EPSG:4326",
        boundary_crs="EPSG:4326",
        boundary=[[110.0, 20.0], [111.0, 20.0], [111.0, 21.0], [110.0, 21.0]],
    )
    return project


def test_generic_xml_well_locations_are_imported_as_well_head(tmp_path):
    source = _external_well_xml(tmp_path / "vendor_delivery.xml")

    report = import_files([source], [])

    assert report.added_count == 1
    resource = report.added[0]
    assert resource.type == "well_head"
    assert resource.format == "xml"


def test_xml_location_binding_marks_points_outside_workarea_as_reference(tmp_path):
    source = _external_well_xml(tmp_path / "vendor_delivery.xml")
    resource = import_files([source], []).added[0]
    project = _project_with_boundary()

    report = bind_resources(
        project,
        [resource],
        asset_id_by_legacy={resource.id: "asset:external-locations"},
        path_resolver=lambda raw: Path(raw),
    )

    assert report.wells_created == 2
    assert all(is_reference_well(well) for well in project.wells)
    assert all(well.coordinate_status == CoordinateStatus.OK for well in project.wells)
    assert {link.role for link in project.entity_asset_links} == {"well_head"}
    assert {link.asset_id for link in project.entity_asset_links} == {"asset:external-locations"}


def test_xml_location_binding_is_reference_even_inside_workarea(tmp_path):
    source = tmp_path / "inside_delivery.xml"
    source.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<WellLocations crs="EPSG:4326">
  <Well><WellName>XML-INSIDE</WellName><X>110.5</X><Y>20.5</Y></Well>
</WellLocations>
""",
        encoding="utf-8",
    )
    resource = import_files([source], []).added[0]
    project = _project_with_boundary()

    bind_resources(
        project,
        [resource],
        asset_id_by_legacy={resource.id: "asset:inside-xml"},
        path_resolver=lambda raw: Path(raw),
    )

    assert len(project.wells) == 1
    assert is_reference_well(project.wells[0])


def test_xml_reference_does_not_reclassify_same_named_workarea_well(tmp_path):
    source = _external_well_xml(tmp_path / "same_name.xml")
    resource = import_files([source], []).added[0]
    project = _project_with_boundary()
    target = WellEntity(name="REF-01", spatial_scope="workarea")
    project.wells.append(target)

    bind_resources(
        project,
        [resource],
        asset_id_by_legacy={resource.id: "asset:same-name-xml"},
        path_resolver=lambda raw: Path(raw),
    )

    assert target.spatial_scope == "workarea"
    assert target.surface_x is None
    matching = [well for well in project.wells if well.name == "REF-01"]
    assert len(matching) == 2
    assert sum(is_reference_well(well) for well in matching) == 1


def test_project_reopen_reclassifies_xml_wells_imported_under_old_rule(tmp_path):
    from paleo_workbench.catalog.domain_binding import stage_resources
    from paleo_workbench.project.domain_migration import migrate_project_to_workarea

    source = _external_well_xml(tmp_path / "legacy_xml.xml")
    resource = import_files([source], []).added[0]
    project = _project_with_boundary()
    project.schema_version = 2
    asset_id = "asset:legacy-xml"
    for name in ("REF-01", "REF-02"):
        well = WellEntity(name=name, spatial_scope="workarea")
        project.wells.append(well)
        project.entity_asset_links.append(
            EntityAssetLink(
                entity_type="well",
                entity_id=well.id,
                asset_id=asset_id,
                role="well_head",
            )
        )
    staged = stage_resources(
        project,
        [resource],
        path_resolver=lambda raw: Path(raw),
    )

    report = migrate_project_to_workarea(
        project,
        asset_id_by_legacy={resource.id: asset_id},
        staged=staged,
    )

    assert report.already_migrated is True
    assert all(is_reference_well(well) for well in project.wells)
    snapshot = (
        [(well.id, well.spatial_scope) for well in project.wells],
        [(link.entity_id, link.asset_id) for link in project.entity_asset_links],
    )

    migrate_project_to_workarea(
        project,
        asset_id_by_legacy={resource.id: asset_id},
        staged=staged,
    )

    assert (
        [(well.id, well.spatial_scope) for well in project.wells],
        [(link.entity_id, link.asset_id) for link in project.entity_asset_links],
    ) == snapshot


def test_reopen_splits_xml_from_same_named_workarea_well_with_other_data(tmp_path):
    from paleo_workbench.catalog.domain_binding import stage_resources
    from paleo_workbench.project.domain_migration import migrate_project_to_workarea

    source = tmp_path / "mixed.xml"
    source.write_text(
        """<WellLocations crs="EPSG:4326">
<Well><WellName>MIXED</WellName><X>120</X><Y>30</Y></Well>
</WellLocations>""",
        encoding="utf-8",
    )
    resource = import_files([source], []).added[0]
    project = _project_with_boundary()
    project.schema_version = 2
    target = WellEntity(name="MIXED", spatial_scope="workarea")
    project.wells.append(target)
    xml_asset_id = "asset:mixed-xml"
    project.entity_asset_links.extend(
        (
            EntityAssetLink(
                entity_type="well",
                entity_id=target.id,
                asset_id=xml_asset_id,
                role="well_head",
            ),
            EntityAssetLink(
                entity_type="well",
                entity_id=target.id,
                asset_id="asset:target-las",
                role="well_log",
            ),
        )
    )
    staged = stage_resources(
        project,
        [resource],
        path_resolver=lambda raw: Path(raw),
    )

    migrate_project_to_workarea(
        project,
        asset_id_by_legacy={resource.id: xml_asset_id},
        staged=staged,
    )

    assert target.spatial_scope == "workarea"
    target_assets = {
        link.asset_id
        for link in project.entity_asset_links
        if link.entity_id == target.id
    }
    assert target_assets == {"asset:target-las"}
    references = [
        well
        for well in project.wells
        if well.name == "MIXED" and well.spatial_scope == "reference"
    ]
    assert len(references) == 1
    reference_assets = {
        link.asset_id
        for link in project.entity_asset_links
        if link.entity_id == references[0].id
    }
    assert reference_assets == {xml_asset_id}


def test_xml_without_crs_remains_reference_without_guessing_coordinates(tmp_path):
    source = tmp_path / "unframed.xml"
    source.write_text(
        "<WellLocations><Well><WellName>UNKNOWN-CRS</WellName><X>120</X><Y>30</Y></Well></WellLocations>",
        encoding="utf-8",
    )
    resource = import_files([source], []).added[0]
    project = _project_with_boundary()

    bind_resources(
        project,
        [resource],
        asset_id_by_legacy={resource.id: "asset:unframed"},
        path_resolver=lambda raw: Path(raw),
    )

    assert project.wells[0].coordinate_status == CoordinateStatus.UNTRANSFORMED
    assert project.wells[0].spatial_scope == "reference"


def test_reference_wells_do_not_expand_derived_workarea_boundary():
    project = ProjectDocument.new("测区")
    project.coordinate.project_crs = "EPSG:4326"
    project.workarea = WorkArea(name="测区", project_crs="EPSG:4326")
    project.wells.extend(
        [
            WellEntity(name="T1", project_x=0, project_y=0, coordinate_status="ok"),
            WellEntity(name="T2", project_x=1, project_y=0, coordinate_status="ok"),
            WellEntity(name="T3", project_x=0, project_y=1, coordinate_status="ok"),
            WellEntity(
                name="REF", project_x=100, project_y=100, coordinate_status="ok", spatial_scope="reference"
            ),
        ]
    )

    boundary = boundary_from_wells(project)

    assert boundary
    assert max(point[0] for point in boundary) == 1.0
    assert max(point[1] for point in boundary) == 1.0
    document, _changed = sync_well_location_map(project)
    assert document is not None
    assert [item["name"] for item in document.well_overlays] == ["T1", "T2", "T3"]


def test_spreadsheetml_well_locations_are_recognized(tmp_path):
    source = tmp_path / "finished.xml"
    source.write_text(
        """<?xml version="1.0"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">
  <Worksheet><Table>
    <Row><Cell><Data>井号</Data></Cell><Cell><Data>X</Data></Cell><Cell><Data>Y</Data></Cell></Row>
    <Row><Cell><Data>REF-S</Data></Cell><Cell><Data>120.0</Data></Cell><Cell><Data>30.0</Data></Cell></Row>
  </Table></Worksheet>
</Workbook>
""",
        encoding="utf-8",
    )

    records, warnings = extract_well_locations_xml(source)

    assert not warnings
    assert [(record.name, record.x, record.y) for record in records] == [
        ("REF-S", 120.0, 30.0)
    ]


def test_data_tree_has_separate_reference_well_category(qtbot):
    from paleo_workbench.ui.pages.navigation_tree import NavigationTree

    project = _project_with_boundary()
    target = WellEntity(name="TARGET")
    reference = WellEntity(name="REF-01", spatial_scope="reference")
    project.wells.extend((target, reference))
    project.entity_asset_links.extend(
        (
            EntityAssetLink(
                entity_type="well", entity_id=target.id, asset_id="asset:target", role="well_head"
            ),
            EntityAssetLink(
                entity_type="well", entity_id=reference.id, asset_id="asset:reference", role="well_head"
            ),
        )
    )
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_asset_label_provider(lambda asset_id: asset_id.rsplit(":", 1)[-1] + ".xml")
    tree.set_project(project)

    target_group = tree._well_group_item
    reference_group = tree._reference_well_group_item
    assert target_group is not None and reference_group is not None
    assert target_group.childCount() == 1
    assert reference_group.childCount() == 1
    assert "TARGET" in target_group.child(0).text(0)
    reference_item = reference_group.child(0)
    assert "REF-01" in reference_item.text(0)
    assert reference_item.childCount() == 1
    assert reference_item.child(0).text(0) == "📄 reference.xml"


def test_navigation_tree_context_menu_requests_concrete_well_delete(
    qtbot, monkeypatch
):
    from PySide6.QtCore import QPoint

    from paleo_workbench.ui.pages import navigation_tree as navigation_module
    from paleo_workbench.ui.pages.navigation_tree import NavigationTree

    project = _project_with_boundary()
    well = WellEntity(name="REF-DELETE", spatial_scope="reference")
    project.wells.append(well)
    tree = NavigationTree()
    qtbot.addWidget(tree)
    tree.set_project(project)
    well_node = tree._reference_well_group_item.child(0)

    labels: list[str] = []

    class _Menu:
        def __init__(self, _parent):
            self.action = None

        def addAction(self, label):
            labels.append(label)
            self.action = object()
            return self.action

        def exec(self, _position):
            return self.action

    monkeypatch.setattr(navigation_module, "QMenu", _Menu)
    monkeypatch.setattr(NavigationTree, "itemAt", lambda _self, _pos: well_node)
    requested: list[str] = []
    tree.delete_well_requested.connect(requested.append)

    tree._on_context_menu(QPoint(1, 1))

    assert labels == ["删除井…"]
    assert requested == [well.id]


def test_data_page_well_groups_filter_their_own_linked_files(qtbot):
    """Group clicks separate WorkArea-well assets from reference-well assets."""
    from paleo_workbench.ui.pages.data_page import DataPage

    project = _project_with_boundary()
    target = WellEntity(name="TARGET", spatial_scope="workarea")
    reference = WellEntity(name="REF-01", spatial_scope="reference")
    target_file = ResourceItem(
        name="target.las", path="/target.las", type="well_log", format="las"
    )
    reference_file = ResourceItem(
        name="reference.xml", path="/reference.xml", type="well_head", format="xml"
    )
    project.wells.extend((target, reference))
    project.resources.extend((target_file, reference_file))
    project.entity_asset_links.extend(
        (
            EntityAssetLink(
                entity_type="well",
                entity_id=target.id,
                asset_id=target_file.id,
                role="well_log",
            ),
            EntityAssetLink(
                entity_type="well",
                entity_id=reference.id,
                asset_id=reference_file.id,
                role="well_head",
            ),
        )
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)

    expected_by_group = (
        (page.navigation_tree._well_group_item, {"target.las"}),
        (page.navigation_tree._reference_well_group_item, {"reference.xml"}),
    )
    for group, expected_names in expected_by_group:
        assert group is not None
        page.navigation_tree.setCurrentItem(group)
        assert {
            page.asset_table.asset_at(row).name
            for row in range(page.asset_table.visible_asset_count())
        } == expected_names


def test_catalogued_reference_well_and_file_leaf_filter_the_source(qtbot, tmp_path):
    """A reference node resolves catalog asset ids back to its table resource."""
    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )
    from paleo_workbench.ui.pages.data_page import DataPage

    project_file = tmp_path / "reference-filter.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    try:
        source = _external_well_xml(tmp_path / "reference.xml")
        reference_file = import_files([source], []).added[0]
        note_path = tmp_path / "unrelated.pdf"
        note_path.write_bytes(b"%PDF-1.4\n")
        unrelated = ResourceItem(
            name="unrelated.pdf",
            path=str(note_path),
            type="document",
            format="pdf",
        )
        project = _project_with_boundary()
        project.resources.extend((reference_file, unrelated))
        ref = adapter.register_input(
            name=reference_file.name,
            path=reference_file.path,
            checksum=reference_file.checksum,
            kind=reference_file.type,
            format=reference_file.format,
            legacy_resource_id=reference_file.id,
        )
        assert ref.asset_id != reference_file.id
        bind_resources(
            project,
            [reference_file],
            asset_id_by_legacy={reference_file.id: ref.asset_id},
            path_resolver=lambda raw: Path(raw),
        )
        page = DataPage(project=project)
        qtbot.addWidget(page)

        reference_group = page.navigation_tree._reference_well_group_item
        assert reference_group is not None
        reference_node = reference_group.child(0)
        file_leaf = reference_node.child(0)
        for item in (reference_node, file_leaf):
            page.navigation_tree.setCurrentItem(item)
            assert [
                page.asset_table.asset_at(row).name
                for row in range(page.asset_table.visible_asset_count())
            ] == [reference_file.name]
    finally:
        reset_catalog()
        service.close()


def test_reference_import_after_page_start_filters_its_file(qtbot, tmp_path):
    """A live import remains filterable after an earlier empty entity query."""
    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )
    from paleo_workbench.ui.pages.data_page import DataPage

    project_file = tmp_path / "live-reference-filter.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    set_catalog(CoreCatalogAdapter(service))
    try:
        project = _project_with_boundary()
        page = DataPage(project=project)
        qtbot.addWidget(page)

        # Match the running Data Manager: an entity-group click can happen
        # before a later XML import registers its catalog asset.
        page.navigation_tree.setCurrentItem(page.navigation_tree._well_group_item)

        source = _external_well_xml(tmp_path / "live-reference.xml")
        with qtbot.waitSignal(page.import_finished, timeout=5_000):
            assert page.begin_import_paths([source])
        qtbot.waitUntil(lambda: len(project.wells) == 2, timeout=5_000)

        reference_group = page.navigation_tree._reference_well_group_item
        assert reference_group is not None
        reference_node = reference_group.child(0)
        page.navigation_tree.setCurrentItem(reference_node)
        assert [
            page.asset_table.asset_at(row).name
            for row in range(page.asset_table.visible_asset_count())
        ] == ["live-reference.xml"]
    finally:
        reset_catalog()
        service.close()


def test_cancel_linked_well_delete_preserves_well_file_and_link(
    qtbot, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from paleo_workbench.ui.pages.data_page import DataPage

    project = _project_with_boundary()
    well = WellEntity(name="KEEP", spatial_scope="reference")
    resource = ResourceItem(
        name="keep.xml", path="/keep.xml", type="well_head", format="xml"
    )
    link = EntityAssetLink(
        entity_type="well",
        entity_id=well.id,
        asset_id=resource.id,
        role="well_head",
    )
    project.wells.append(well)
    project.resources.append(resource)
    project.entity_asset_links.append(link)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    questions: list[tuple] = []

    def decline(*args):
        questions.append(args)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(decline))

    assert page.delete_well(well.id) is False
    assert project.wells == [well]
    assert project.resources == [resource]
    assert project.entity_asset_links == [link]
    assert len(questions) == 1
    assert "同步" in questions[0][2]
    assert questions[0][4] == QMessageBox.StandardButton.No


def test_confirm_linked_well_delete_trashes_file_and_removes_entity(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )
    from paleo_workbench.ui.pages.data_page import DataPage

    project_file = tmp_path / "delete-well.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    try:
        source = _external_well_xml(tmp_path / "delete-source.xml")
        resource = import_files([source], []).added[0]
        project = _project_with_boundary()
        well = WellEntity(name="DELETE", spatial_scope="reference")
        project.wells.append(well)
        project.resources.append(resource)
        ref = adapter.register_input(
            name=resource.name,
            path=resource.path,
            checksum=resource.checksum,
            kind=resource.type,
            format=resource.format,
            legacy_resource_id=resource.id,
        )
        project.entity_asset_links.append(
            EntityAssetLink(
                entity_type="well",
                entity_id=well.id,
                asset_id=ref.asset_id,
                role="well_head",
            )
        )
        page = DataPage(project=project)
        qtbot.addWidget(page)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
        )

        assert page.delete_well(well.id) is True
        assert project.wells == []
        assert project.resources == []
        assert project.entity_asset_links == []
        assert service.get_asset(ref.asset_id).trashed is True
    finally:
        reset_catalog()
        service.close()


def test_confirm_unlinked_well_delete_removes_only_the_entity(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from paleo_workbench.ui.pages.data_page import DataPage

    project = _project_with_boundary()
    well = WellEntity(name="MANUAL", spatial_scope="workarea")
    unrelated = ResourceItem(
        name="unrelated.pdf",
        path="/unrelated.pdf",
        type="document",
        format="pdf",
    )
    project.wells.append(well)
    project.resources.append(unrelated)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
    )
    assert page.delete_well(well.id) is True
    assert project.wells == []
    assert project.resources == [unrelated]


def test_confirm_well_delete_clears_dangling_file_link(qtbot, monkeypatch):
    """An unresolvable source file must not strand the well record."""
    from PySide6.QtWidgets import QMessageBox

    from paleo_workbench.ui.pages.data_page import DataPage

    project = _project_with_boundary()
    well = WellEntity(name="STALE-SOURCE", spatial_scope="reference")
    project.wells.append(well)
    project.entity_asset_links.append(
        EntityAssetLink(
            entity_type="well",
            entity_id=well.id,
            asset_id="asset:already-missing",
            role="well_log",
        )
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args: QMessageBox.StandardButton.Yes),
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *args: None))

    assert page.delete_well(well.id) is True
    assert project.wells == []
    assert project.entity_asset_links == []


def test_delete_missing_well_id_clears_its_residual_links(qtbot):
    """Deletion is idempotent when the tree points at an already-missing well."""
    from paleo_workbench.ui.pages.data_page import DataPage

    project = _project_with_boundary()
    project.entity_asset_links.append(
        EntityAssetLink(
            entity_type="well",
            entity_id="well:already-missing",
            asset_id="asset:already-missing",
            role="well_head",
        )
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)

    assert page.delete_well("well:already-missing") is True
    assert project.entity_asset_links == []


def test_data_page_import_places_external_xml_wells_in_reference_group(qtbot, tmp_path):
    """The real async import → registration → binding path reaches the tree."""
    from paleo_workbench.ui.pages.data_page import DataPage

    project = _project_with_boundary()
    page = DataPage(project=project)
    qtbot.addWidget(page)
    source = _external_well_xml(tmp_path / "regional_wells.xml")

    with qtbot.waitSignal(page.import_finished, timeout=5_000):
        assert page.begin_import_paths([source])
    qtbot.waitUntil(lambda: len(project.wells) == 2, timeout=5_000)

    assert all(well.spatial_scope == "reference" for well in project.wells)
    group = page.navigation_tree._reference_well_group_item
    assert group is not None
    assert group.childCount() == 2


def test_generic_named_witsml_import_creates_reference_well(qtbot, tmp_path):
    """Well-data semantics come from XML content, not filename hints."""
    from paleo_workbench.ui.pages.data_page import DataPage

    source = _witsml_well_xml(tmp_path / "regional_delivery.xml")
    project = _project_with_boundary()
    page = DataPage(project=project)
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.import_finished, timeout=5_000):
        assert page.begin_import_paths([source])
    qtbot.waitUntil(lambda: bool(project.wells), timeout=5_000)

    assert project.resources[0].type == "well_log"
    assert [(well.name, well.spatial_scope) for well in project.wells] == [
        ("XML-REF-01", "reference")
    ]
    group = page.navigation_tree._reference_well_group_item
    assert group is not None
    assert group.childCount() == 1
    reference_node = group.child(0)
    assert reference_node.childCount() == 1
    page.navigation_tree.setCurrentItem(reference_node)
    assert [
        page.asset_table.asset_at(row).name
        for row in range(page.asset_table.visible_asset_count())
    ] == [source.name]


def test_reimported_witsml_reference_links_and_visualizes_reused_catalog_asset(
    qtbot, tmp_path
):
    """A reused catalog row must retain its ResourceItem visualization contract."""
    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )
    from paleo_workbench.ui.pages.data_page import DataPage

    project_file = tmp_path / "reimport-reference.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    try:
        source = _witsml_well_xml(tmp_path / "regional_delivery.xml")
        existing = adapter.register_input(
            name=source.name,
            path=str(source),
            checksum=None,
            kind="well_log",
            format="xml",
            legacy_resource_id="res:previous-import",
        )
        project = _project_with_boundary()
        page = DataPage(project=project)
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.import_finished, timeout=5_000):
            assert page.begin_import_paths([source])
        qtbot.waitUntil(lambda: bool(project.wells), timeout=5_000)

        assert project.resources[0].id != "res:previous-import"
        assert project.resources[0].parsed_summary["catalog_asset_id"] == existing.asset_id
        assert [
            (link.entity_id, link.asset_id, link.role)
            for link in project.entity_asset_links
        ] == [(project.wells[0].id, existing.asset_id, "well_log")]
        reference_node = page.navigation_tree._reference_well_group_item.child(0)
        page.navigation_tree.setCurrentItem(reference_node)
        assert [
            page.asset_table.asset_at(row).name
            for row in range(page.asset_table.visible_asset_count())
        ] == [source.name]

        page.asset_table.table.selectRow(0)
        qtbot.waitUntil(lambda: page._selected_asset is not None, timeout=3_000)
        preview_resource = page._resource_for_preview(page._selected_asset)
        assert isinstance(preview_resource, ResourceItem)
        assert Path(preview_resource.path).is_file()
        assert Path(preview_resource.path).read_text(encoding="utf-8") == source.read_text(
            encoding="utf-8"
        )
        assert (preview_resource.type, preview_resource.format) == ("well_log", "xml")
        qtbot.waitUntil(
            lambda: page.reader_panel.current_mode == "well_log",
            timeout=5_000,
        )
        tabs = page.reader_panel.lazy_visualization_tabs
        tabs.setCurrentIndex(1)
        qtbot.waitUntil(
            lambda: page.reader_panel._geoviz_host is not None
            and tabs.visual_stack.currentWidget() is page.reader_panel._geoviz_host,
            timeout=5_000,
        )

        assert page._resource_for_preview(page._selected_asset) == preview_resource
        assert page.reader_panel._geoviz_host is not None
        assert tabs.visual_stack.currentWidget() is page.reader_panel._geoviz_host
    finally:
        reset_catalog()
        service.close()


def test_removing_reference_xml_resource_prunes_its_orphan_well_nodes(qtbot, tmp_path):
    from paleo_workbench.ui.pages.data_page import DataPage

    source = _external_well_xml(tmp_path / "regional_wells.xml")
    resource = import_files([source], []).added[0]
    project = _project_with_boundary()
    project.resources.append(resource)
    bind_resources(
        project,
        [resource],
        asset_id_by_legacy={resource.id: resource.id},
        path_resolver=lambda raw: Path(raw),
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)

    assert page.navigation_tree._reference_well_group_item.childCount() == 2
    assert page.remove_assets([resource]) is True

    assert project.resources == []
    assert project.entity_asset_links == []
    assert project.wells == []
    reference_group = page.navigation_tree._reference_well_group_item
    labels = [
        reference_group.child(index).text(0)
        for index in range(reference_group.childCount())
    ]
    assert labels == ["暂无其他参考井"]


def test_removing_one_xml_resource_keeps_reference_well_used_by_another(qtbot, tmp_path):
    from paleo_workbench.ui.pages.data_page import DataPage

    first_source = _external_well_xml(tmp_path / "first.xml")
    second_source = _external_well_xml(tmp_path / "second.xml")
    resources = import_files([first_source, second_source], []).added
    project = _project_with_boundary()
    project.resources.extend(resources)
    bind_resources(
        project,
        resources,
        asset_id_by_legacy={resource.id: resource.id for resource in resources},
        path_resolver=lambda raw: Path(raw),
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)

    assert page.remove_assets([resources[0]]) is True

    assert {resource.id for resource in project.resources} == {resources[1].id}
    assert {link.asset_id for link in project.entity_asset_links} == {resources[1].id}
    assert {well.name for well in project.wells} == {"REF-01", "REF-02"}


def test_removing_catalogued_xml_prunes_links_by_catalog_asset_id(qtbot, tmp_path):
    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )
    from paleo_workbench.ui.pages.data_page import DataPage

    project_file = tmp_path / "catalogued.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    try:
        source = _external_well_xml(tmp_path / "catalogued.xml")
        resource = import_files([source], []).added[0]
        project = _project_with_boundary()
        project.resources.append(resource)
        ref = adapter.register_input(
            name=resource.name,
            path=resource.path,
            checksum=resource.checksum,
            kind=resource.type,
            format=resource.format,
            legacy_resource_id=resource.id,
        )
        assert ref.asset_id != resource.id
        bind_resources(
            project,
            [resource],
            asset_id_by_legacy={resource.id: ref.asset_id},
            path_resolver=lambda raw: Path(raw),
        )
        page = DataPage(project=project)
        qtbot.addWidget(page)

        assert page.remove_assets([resource]) is True

        assert project.entity_asset_links == []
        assert project.wells == []
        assert service.get_asset(ref.asset_id).trashed is True
    finally:
        reset_catalog()
        service.close()
