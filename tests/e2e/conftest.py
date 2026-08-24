"""Shared fixtures, synthetic dataset generators, and environment mocks for E2E tests."""

from __future__ import annotations

import os
import stat
import struct
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
)


@pytest.fixture
def synthetic_seismic_cube() -> dict[str, Any]:
    """Provides a synthetic 3D seismic volume with known gradients and dimensions."""
    inlines = np.arange(100, 150, dtype=np.int32)
    crosslines = np.arange(200, 260, dtype=np.int32)
    times = np.linspace(0, 1000, 100, dtype=np.float32)

    # 3D sinusoidal synthetic wavefield: (n_inlines, n_crosslines, n_times)
    ni, nx, nt = len(inlines), len(crosslines), len(times)
    i_grid, x_grid, t_grid = np.meshgrid(
        np.linspace(0, 4 * np.pi, ni),
        np.linspace(0, 4 * np.pi, nx),
        np.linspace(0, 8 * np.pi, nt),
        indexing="ij",
    )
    volume = np.sin(i_grid) * np.cos(x_grid) * np.sin(t_grid)

    return {
        "volume": volume.astype(np.float32),
        "inlines": inlines,
        "crosslines": crosslines,
        "times": times,
        "shape": (ni, nx, nt),
    }


@pytest.fixture
def synthetic_descending_cube() -> dict[str, Any]:
    """Provides a seismic cube with strictly decreasing inline/crossline ordering."""
    inlines = np.arange(500, 450, -1, dtype=np.int32)  # descending
    crosslines = np.arange(300, 250, -1, dtype=np.int32)  # descending
    times = np.linspace(0, 1000, 50, dtype=np.float32)

    ni, nx, nt = len(inlines), len(crosslines), len(times)
    volume = np.ones((ni, nx, nt), dtype=np.float32)

    return {
        "volume": volume,
        "inlines": inlines,
        "crosslines": crosslines,
        "times": times,
        "shape": (ni, nx, nt),
    }


@pytest.fixture
def synthetic_well_log_data() -> dict[str, Any]:
    """Provides synthetic multi-curve well log data including non-positive and edge values."""
    depth = np.linspace(1000.0, 2000.0, 500, dtype=np.float64)
    gamma_ray = np.clip(np.random.normal(60.0, 15.0, 500), 0.0, 150.0)

    # Resistivity with some negative/zero null readings (-999.25, 0.0)
    resistivity = np.exp(np.random.normal(2.0, 0.5, 500))
    resistivity[10:15] = -999.25
    resistivity[50] = 0.0
    resistivity[100:105] = -1.0

    # Sonic log
    sonic = 200.0 + 30.0 * np.sin(depth / 50.0)

    return {
        "well_name": "WELL-CN-01_塔里木井",
        "depth": depth,
        "curves": {
            "GR": gamma_ray,
            "RT": resistivity,
            "DT": sonic,
        },
        "units": {
            "GR": "API",
            "RT": "OHMM",
            "DT": "US/M",
        },
        "headers_chinese": "井号: 塔深1井, 构造位置: 塔里木盆地, 测量日期: 2026-08-24",
    }


@pytest.fixture
def synthetic_kriging_points() -> dict[str, Any]:
    """Provides observation points for spatial Kriging and factor mapping."""
    np.random.seed(42)
    n = 25
    x = np.random.uniform(100.0, 500.0, n)
    y = np.random.uniform(200.0, 600.0, n)
    z = 10.0 + 0.05 * x + 0.02 * y + np.random.normal(0.0, 2.0, n)

    # Include duplicate points and collinear points for boundary testing
    return {
        "x": x,
        "y": y,
        "values": z,
        "grid_bounds": (100.0, 200.0, 500.0, 600.0),
        "grid_resolution": (50, 50),
    }


@pytest.fixture
def synthetic_map_geometries() -> dict[str, Any]:
    """Provides rich GIS geometries including GeometryCollections for vector rendering."""
    pt1 = Point(10.0, 10.0)
    pt2 = Point(20.0, 20.0)
    line1 = LineString([(0.0, 0.0), (10.0, 10.0), (20.0, 5.0)])
    line2 = LineString([(5.0, 15.0), (15.0, 25.0)])
    poly1 = Polygon([(0.0, 0.0), (0.0, 30.0), (30.0, 30.0), (30.0, 0.0), (0.0, 0.0)])
    poly2 = Polygon([(5.0, 5.0), (5.0, 10.0), (10.0, 10.0), (10.0, 5.0), (5.0, 5.0)])
    multi_poly = MultiPolygon([poly1, poly2])
    geom_col = GeometryCollection([pt1, line1, poly2, multi_poly])

    return {
        "point": pt1,
        "linestring": line1,
        "polygon": poly1,
        "multipolygon": multi_poly,
        "geometry_collection": geom_col,
    }


@pytest.fixture
def read_only_file(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates a temporary read-only file on disk to test Windows NTFS safe unlinking."""
    fpath = tmp_path / "locked_artifact.dat"
    fpath.write_text("protected content", encoding="utf-8")
    os.chmod(fpath, stat.S_IREAD)  # remove write permission
    yield fpath
    try:
        os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
        if fpath.exists():
            fpath.unlink()
    except Exception:
        pass


@pytest.fixture
def read_only_tree(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates a nested directory tree with read-only files and folders."""
    root = tmp_path / "locked_tree"
    root.mkdir()
    sub = root / "sub_dir"
    sub.mkdir()
    f1 = sub / "file1.txt"
    f1.write_text("read only text", encoding="utf-8")
    os.chmod(f1, stat.S_IREAD)

    yield root

    # Cleanup helper
    def _force_rm(path: Path):
        if not path.exists():
            return
        for child in path.rglob("*"):
            try:
                os.chmod(child, stat.S_IWRITE | stat.S_IREAD)
            except Exception:
                pass
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            import shutil
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    _force_rm(root)
