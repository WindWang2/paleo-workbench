"""Lightweight import + native-extension probe for the Windows build.

Resource-conscious: no data processing, no Qt widgets instantiated, no GPU.
Reports which modules resolve and from where.
"""
import importlib
import sys
import traceback

MODULES = [
    "PySide6",
    "numpy",
    "shapely",
    "rasterio",
    "zarr",
    "pydantic",
    "lasio",
    "geoviz",
    "paleo_workbench",
    "grid_render_core",
    "layer_model_core",
    "seismic_3d_core",
    "well_log_core",
    "map_edit_core",
    "qgis_render_bridge",
]

NATIVE = {
    "grid_render_core",
    "layer_model_core",
    "seismic_3d_core",
    "well_log_core",
    "map_edit_core",
    "qgis_render_bridge",
}


def main() -> int:
    print(f"python: {sys.version.split()[0]}  ({sys.executable})")
    print("-" * 72)
    missing_native = []
    for name in MODULES:
        try:
            mod = importlib.import_module(name)
            origin = getattr(mod, "__file__", None) or "<namespace/builtin>"
            print(f"OK    {name:24s} {origin}")
        except Exception as exc:  # noqa: BLE001 - probe wants the real message
            tag = "NATIVE-MISSING" if name in NATIVE else "FAIL"
            print(f"{tag:15s} {name:24s} {type(exc).__name__}: {exc}")
            if name in NATIVE:
                missing_native.append(name)
    print("-" * 72)
    if missing_native:
        print("native extensions not importable: " + ", ".join(missing_native))
    else:
        print("all native extensions importable")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
