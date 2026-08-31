"""Offscreen-safe tests for the QSettings-backed panel layout store (M4)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QSettings

from paleo_workbench.ui.layout_persistence import LayoutPersistence, PanelLayoutRecord


@pytest.fixture()
def settings_path(tmp_path):
    return tmp_path / "panel_layout.ini"


@pytest.fixture()
def persistence(settings_path) -> LayoutPersistence:
    return LayoutPersistence(QSettings(str(settings_path), QSettings.Format.IniFormat))


def test_empty_store_loads_defaults(persistence):
    record = persistence.load("mapping:layer_tree")
    assert record == PanelLayoutRecord()
    assert record.is_empty
    assert record.floating is False
    assert record.geometry is None
    assert record.docked_sizes is None
    assert record.visible is True


def test_save_float_round_trip(persistence, settings_path):
    geometry = QRect(12, 34, 560, 400)
    persistence.save_float("mapping:layer_tree", geometry)

    # A fresh store bound to the same ini file must read the record back —
    # this is the restore-on-relaunch path.
    reopened = LayoutPersistence(
        QSettings(str(settings_path), QSettings.Format.IniFormat)
    )
    record = reopened.load("mapping:layer_tree")
    assert record.floating is True
    assert record.geometry == geometry
    assert record.visible is True
    assert not record.is_empty


def test_save_dock_round_trip(persistence):
    persistence.save_dock("mapping:layer_tree", [220, 480, 300])
    record = persistence.load("mapping:layer_tree")
    assert record.floating is False
    assert record.docked_sizes == (220, 480, 300)
    assert record.visible is True


def test_dock_clears_float_state(persistence):
    persistence.save_float("w1", QRect(0, 0, 420, 320))
    persistence.save_dock("w1", [100, 200])
    record = persistence.load("w1")
    assert record.floating is False
    assert record.docked_sizes == (100, 200)


def test_save_visibility_only_touches_visible_flag(persistence):
    persistence.save_float("w1", QRect(1, 2, 3, 4))
    persistence.save_visibility("w1", False)

    record = persistence.load("w1")
    assert record.visible is False
    assert record.floating is True
    assert record.geometry == QRect(1, 2, 3, 4)

    persistence.save_visibility("w1", True)
    assert persistence.load("w1").visible is True


def test_clear_removes_entry(persistence):
    persistence.save_float("w1", QRect(0, 0, 10, 10))
    persistence.clear("w1")
    assert persistence.load("w1").is_empty


def test_keys_are_namespaced_independently(persistence):
    persistence.save_float("mapping:layer_tree", QRect(0, 0, 10, 10))
    persistence.save_dock("mapping:map_tools", [50, 50])

    assert persistence.load("mapping:layer_tree").floating is True
    assert persistence.load("mapping:map_tools").floating is False
    assert persistence.load("well_log:crossplot").is_empty


def test_corrupt_values_fall_back_to_defaults(settings_path):
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    settings.setValue("panel_layout/broken/geometry", "not,a,rect")
    settings.setValue("panel_layout/broken/docked_sizes", "x,y")
    settings.setValue("panel_layout/broken/floating", True)
    settings.sync()

    record = LayoutPersistence(settings).load("broken")
    assert record.geometry is None
    assert record.docked_sizes is None
    assert record.floating is True  # the valid flag survives


def test_default_constructor_binds_lazily_without_writes():
    # Constructing the default store must not touch QSettings until a save or
    # load is requested (offscreen CI stays inert).
    store = LayoutPersistence()
    assert store._settings is None
