"""Programmatic, small fixtures for the interchange compatibility matrix.

Everything here generates bytes in-process — no binary blobs are committed.
"""

from __future__ import annotations

import json
from pathlib import Path


def valid_las_text(
    *,
    curves: tuple[tuple[str, str], ...] = (("DEPT", "M"), ("GR", "GAPI")),
    rows: int = 20,
    start: float = 100.0,
    step: float = 0.5,
    well_name: str = "W-001",
    null: float = -999.25,
) -> str:
    lines = [
        "~VERSION INFORMATION",
        "VERS. 2.0 : CWLS LOG ASCII STANDARD",
        "WRAP. NO : ONE LINE PER DEPTH STEP",
        "~WELL INFORMATION",
        f"STRT.M {start}",
        f"STOP.M {start + step * (rows - 1)}",
        f"STEP.M {step}",
        f"NULL. {null}",
        f"WELL. {well_name}",
        "~CURVE INFORMATION",
    ]
    lines.extend(f"{name}.{unit} : curve" for name, unit in curves)
    lines.append("~A")
    for i in range(rows):
        depth = start + step * i
        values = " ".join(f"{depth * 0.1 + j}" for j in range(len(curves) - 1))
        lines.append(f"{depth:.3f} {values}".rstrip())
    return "\n".join(lines) + "\n"


def write_valid_las(path: Path, **kwargs) -> Path:
    path.write_text(valid_las_text(**kwargs), encoding="utf-8", newline="")
    return path


def write_duplicate_mnemonic_las(path: Path) -> Path:
    text = valid_las_text(curves=(("DEPT", "M"), ("GR", "GAPI"), ("GR", "GAPI")), rows=5)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def write_nonmonotonic_las(path: Path) -> Path:
    text = valid_las_text(rows=6)
    lines = text.splitlines()
    header = [ln for ln in lines if not ln[0:1].isdigit() and not ln.startswith("~A")]
    depths = [100.0, 100.5, 101.0, 100.5, 100.0, 101.5]
    body = [f"{d:.3f} {d * 0.1}" for d in depths]
    path.write_text("\n".join(header + ["~A"] + body) + "\n", encoding="utf-8", newline="")
    return path


def write_malformed_rows_las(path: Path) -> Path:
    text = valid_las_text(rows=4)
    lines = text.splitlines() + ["not-a-number oops", "100.5"]
    path.write_text("\n".join(lines), encoding="utf-8", newline="")
    return path


def write_truncated_las(path: Path) -> Path:
    text = valid_las_text(rows=50)
    path.write_text(text[: len(text) // 2], encoding="utf-8", newline="")
    return path


def write_non_utf8_las(path: Path) -> Path:
    text = valid_las_text(rows=3).replace("W-001", "井W-001")
    path.write_bytes(text.encode("gb18030"))
    return path


def write_gbk_encoded_las(path: Path) -> Path:
    text = valid_las_text(rows=3, well_name="井位测试-01")
    path.write_bytes(text.encode("gb18030"))
    return path


def write_csv(
    path: Path,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
    rows: int = 10,
    header: tuple[str, ...] = ("Well", "Depth", "X", "Y", "Value"),
    decimal: str = ".",
) -> Path:
    lines = [delimiter.join(header)]
    for i in range(rows):
        depth = f"{100 + i * 0.5:.2f}".replace(".", decimal)
        value = f"{i * 1.5:.3f}".replace(".", decimal)
        cells = (f"W-{i % 2}", depth, f"{116000 + i}", f"{39000 + i}", value)
        lines.append(delimiter.join(cells))
    path.write_text("\n".join(lines) + "\n", encoding=encoding, newline="")
    return path


def write_duplicate_header_csv(path: Path) -> Path:
    lines = ["Well,Depth,Depth,X", "W-1,1,2,3", "W-1,2,3,4"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    return path


def write_shift_jis_ish_csv(path: Path) -> Path:
    text = "井名,深度,值\nW-1,1.5,2.5\nW-2,2.5,3.5\n"
    path.write_bytes(text.encode("gb18030"))
    return path


def write_geojson(
    path: Path,
    *,
    features: int = 5,
    crs: str | None = None,
    mixed: bool = False,
) -> Path:
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.0 + i, 39.0 + i]},
                "properties": {"name": f"P{i}", "相": ["砂岩", "泥岩"][i % 2]},
            }
            for i in range(features)
        ],
    }
    if mixed and features >= 2:
        collection["features"][1]["geometry"] = {
            "type": "Polygon",
            "coordinates": [[[116, 39], [117, 39], [117, 40], [116, 39]]],
        }
    if crs:
        collection["crs"] = {"type": "name", "properties": {"name": crs}}
    path.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    return path


def write_truncated_geojson(path: Path) -> Path:
    text = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                    "properties": {},
                }
            ],
        }
    )
    path.write_text(text[: len(text) // 2], encoding="utf-8")
    return path


def write_project_json(path: Path, name: str = "demo") -> Path:
    path.write_text(json.dumps({"schema_version": 1, "meta": {"name": name}}), encoding="utf-8")
    return path


def geotiff_available() -> bool:
    try:
        import rasterio  # noqa: F401
    except Exception:
        return False
    return True


def write_geotiff(path: Path, *, width: int = 32, height: int = 24, nodata: float = -9999.0,
                  epsg: int | None = 4326, dtype: str = "float32") -> Path:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    data = np.arange(width * height, dtype=dtype).reshape(height, width)
    if nodata is not None:
        data[0, :3] = nodata
    transform = from_origin(116.0, 40.0, 0.001, 0.001)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype=dtype,
        crs=f"EPSG:{epsg}" if epsg else None,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


def ogr_available() -> bool:
    try:
        from osgeo import ogr  # noqa: F401
    except Exception:
        return False
    return True


def write_point_shapefile(path: Path, *, count: int = 6, epsg: int = 4326,
                          with_prj: bool = True) -> Path:
    from osgeo import ogr, osr

    driver = ogr.GetDriverByName("ESRI Shapefile")
    datasource = driver.CreateDataSource(str(path))
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(epsg)
    layer = datasource.CreateLayer("points", spatial_ref, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("name", ogr.OFTString))
    for i in range(count):
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetField("name", f"P{i}")
        geometry = ogr.Geometry(ogr.wkbPoint)
        geometry.AddPoint_2D(116.0 + i, 39.0 + i)
        feature.SetGeometry(geometry)
        layer.CreateFeature(feature)
    datasource = None
    if not with_prj:
        path.with_suffix(".prj").unlink(missing_ok=True)
    return path


def segy_generator():
    """Load the shared synthetic SEG-Y generator from benchmarks/."""
    import importlib.util
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    gen_path = repo_root / "benchmarks" / "generate_synthetic_segy.py"
    spec = importlib.util.spec_from_file_location("generate_synthetic_segy_io", gen_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("generate_synthetic_segy_io", module)
    spec.loader.exec_module(module)
    return module


def write_tiny_segy(path: Path) -> Path:
    gen = segy_generator()
    spec = gen.PRESETS["tiny"]
    gen.generate_volume(spec, path, progress=False)
    return path


def write_f3grid(path: Path, nx: int = 3, ny: int = 2, nz: int = 2) -> Path:
    from paleo_workbench.viz.geomodel.exporters import export_to_flac3d

    export_to_flac3d(str(path), nx=nx, ny=ny, nz=nz)
    return path
