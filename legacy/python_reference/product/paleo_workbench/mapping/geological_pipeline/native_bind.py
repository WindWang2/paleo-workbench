"""Optional C++ acceleration facade over the mapping_kernel cores (CONV-20).

The pybind11 module ``pwb_mapping_kernel`` (built from ``libs/mapping_bind/``,
see ``paleo_workbench/mapping/CPP_EXTENSION.md``) wraps the Qt-free kernel
that is frozen against the Python oracles. This module is the only seam that
dispatches to it:

* ``HAS_CPP`` is True only when ``import pwb_mapping_kernel`` succeeds.
* The three entry points keep the pure-Python signatures and return types;
  when the module is absent (or, for kriging, when the estimator would
  differ — see ``_cpp_kriging_ok``) they call the production pure-Python
  implementations, so behavior is identical with and without the extension.
* Known frozen-contract limits inherited from the kernel: IDW kNN neighbour
  sets are guaranteed identical to scipy cKDTree only for unique-distance
  neighbourhoods (exact ties at the k-th neighbour may select a different
  neighbour — see libs/mapping_kernel/include/pwb/mapping/interpolator.hpp),
  and extract string parsing uses the kernel's strtod full-consume rule
  (Python-float forms like "1_000" or bytes are not accepted).

Import this module directly; the product pipeline modules are untouched and
always run the pure-Python path. Example::

    from paleo_workbench.mapping.geological_pipeline import native_bind
    if native_bind.HAS_CPP:
        result = native_bind.interpolate_factor(dataset, options)
"""
from __future__ import annotations

import logging

import numpy as np

try:
    import pwb_mapping_kernel as _kernel
except ImportError:  # extension not built / not on sys.path
    _kernel = None

from paleo_workbench.mapping.geological_pipeline.interpolator import (
    interpolate_factor as _py_interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import (
    GeologicalMappingPipeline,
)
from paleo_workbench.mapping.well_prediction_surface import (
    nearest_neighbor_class_grid as _py_nearest_neighbor_class_grid,
)
from paleo_workbench.workflow.crs_policy import resolve_distance_policy
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = [
    "HAS_CPP",
    "extract_factors",
    "interpolate_factor",
    "nearest_neighbor_class_grid",
]

HAS_CPP = _kernel is not None

# Deliberately the pipeline module's logger: the facade's mixed-family
# warning must be text- and origin-identical to pipeline.py's own
# (tests pin the "mixed coordinate key families" message on this logger).
logger = logging.getLogger(
    "paleo_workbench.mapping.geological_pipeline.pipeline")

_GEOVIZ_AVAILABLE: bool | None = None


def _geoviz_available() -> bool:
    """True when the geoviz engine import the pure path performs would succeed.

    Mirrors interpolator.py's ``from geoviz import fit_variogram, ...`` probe
    (ImportError only — a geoviz that fails in any other way propagates on
    both paths). Cached; the failed import is the common (accelerated) case,
    so the probe cost is one failed import per process.
    """
    global _GEOVIZ_AVAILABLE
    if _GEOVIZ_AVAILABLE is None:
        try:
            from geoviz import (  # noqa: F401
                fit_variogram,
                kriging_grid,
                leave_one_out_predictions,
            )
        except ImportError:
            _GEOVIZ_AVAILABLE = False
        else:
            _GEOVIZ_AVAILABLE = True
    return _GEOVIZ_AVAILABLE


def _neighborhood_requested(options: InterpolationOptions) -> bool:
    if options.max_neighbors is not None and int(options.max_neighbors) > 0:
        return True
    return options.search_radius is not None and float(options.search_radius) > 0.0


def _cpp_kriging_ok(options: InterpolationOptions) -> bool:
    """Kriging may dispatch to the kernel only when both paths share an estimator.

    The C++ kernel is the numpy-grid-OLS fallback port. When geoviz is
    importable and no moving-neighbourhood knobs are set, the pure-Python path
    uses the geoviz WLS engine — a different estimator — so kriging stays on
    Python there (interpolator.py runs the numpy path under exactly the other
    two conditions).
    """
    return not _geoviz_available() or _neighborhood_requested(options)


def _dataset_points(dataset: GeologicalFactorDataset) -> list[dict]:
    return [
        {"x": p.x, "y": p.y, "value": p.value, "qc_flag": p.qc_flag}
        for p in dataset.points
    ]


def _options_dict(dataset: GeologicalFactorDataset,
                  options: InterpolationOptions) -> dict:
    # Every field is passed explicitly: the C++ struct defaults (method="idw")
    # intentionally differ from the Python dataclass defaults ("kriging").
    return {
        "method": options.method,
        "grid_n": int(options.grid_n),
        "power": float(options.power),
        "min_neighbors": int(options.min_neighbors),
        "max_neighbors": (
            int(options.max_neighbors)
            if options.max_neighbors is not None else None),
        "search_radius": (
            float(options.search_radius)
            if options.search_radius is not None else None),
        "variogram_model": options.variogram_model,
        "boundary": (
            [[float(x), float(y)] for x, y in options.boundary]
            if options.boundary else None),
        # The distance policy resolves from the DATASET crs only
        # (interpolate_factor: resolve_distance_policy(dataset.crs or None,
        # ...)); options.crs only feeds the result.crs fallback.
        "crs": dataset.crs,
        "distance_policy": options.distance_policy,
    }


def _cpp_interpolate_factor(
    dataset: GeologicalFactorDataset,
    options: InterpolationOptions,
) -> FactorGridResult:
    from paleo_workbench.mapping.geological_pipeline.interpolator import (
        _neighborhood_disclosure,
    )

    raw = _kernel.interpolate_factor(
        _dataset_points(dataset), _options_dict(dataset, options))
    grid_n = len(raw["grid_y"])
    grid_z = np.array(raw["grid_z"], dtype=np.float32).reshape(
        (grid_n, len(raw["grid_x"])))
    variance = (
        None if raw["variance_grid"] is None else
        np.array(raw["variance_grid"], dtype=np.float32).reshape(grid_z.shape))

    sample_points = [
        {"well": p.well_name or p.well_id, "x": p.x, "y": p.y, "value": p.value}
        for p in dataset.valid_points
    ]
    if raw["algorithm_id"] == "idw":
        params: dict = {
            "method": "idw",
            "power": float(raw["power"]),
            "grid_n": int(raw["grid_n"]),
            "n_samples": int(raw["n_samples"]),
            "search_radius": options.search_radius,
            "min_neighbors": options.min_neighbors,
            "max_neighbors": options.max_neighbors,
            "sample_points": sample_points,
        }
    else:
        params = {
            "method": raw["method"],
            "model": raw["model"],
            "range": float(raw["range"]),
            "sill": float(raw["sill"]),
            "nugget": float(raw["nugget"]),
            "n_samples": int(raw["n_samples"]),
            "duplicates_merged": int(raw["duplicates_merged"]),
            "variogram_bins": int(raw["variogram_bins"]),
            "variogram_fit": raw["variogram_fit"],
            "sample_points": sample_points,
            # Same disclosure the numpy fallback records: this surface is the
            # grid-OLS estimator, NOT the geoviz WLS engine, and no engine
            # LOO R² exists on this path.
            "degraded": True,
            "degraded_reason": (
                "mapping_kernel C++ kernel used the numpy-grid-OLS "
                "estimator (geoviz WLS engine bypassed by the native "
                "facade); r_squared not computed (engine LOO unavailable)"
            ),
            "r_squared": None,
        }
    if _neighborhood_requested(options):
        # Same disclosure block the numpy path records (kernel numerics are
        # identical; the block describes the neighbourhood contract).
        params["neighborhood"] = _neighborhood_disclosure(
            options.max_neighbors, options.search_radius,
            options.min_neighbors, len(dataset.valid_points))
        if raw["algorithm_id"] == "kriging":
            # Constant-field check on the raw values, like the numpy path's
            # z_var guard. (The kernel additionally dedups before its own
            # check; a dataset whose variance collapses only after dedup is
            # below the tolerance noise floor for both paths.)
            values = dataset.to_arrays()[2]
            if len(values) <= 1 or float(np.var(values)) <= 1e-12:
                # Mirror the numpy path's constant-field note: the disclosure
                # above needs the "every estimate is the sample mean" caveat.
                params["neighborhood"]["note"] = (
                    "constant field: every estimate is the sample mean"
                    + (
                        f"; {params['neighborhood'].get('note')}"
                        if params["neighborhood"].get("note") else ""
                    )
                )

    result = FactorGridResult(
        grid_z=grid_z,
        grid_x=np.asarray(raw["grid_x"], dtype=np.float64),
        grid_y=np.asarray(raw["grid_y"], dtype=np.float64),
        factor_name=dataset.factor_name,
        algorithm_id=raw["algorithm_id"],
        algorithm_parameters=params,
        crs=dataset.crs or options.crs,
        unit=dataset.unit,
        variance_grid=variance,
    )
    if options.boundary:
        result.boundary = [(float(x), float(y)) for x, y in options.boundary]
        result.algorithm_parameters["domain_mask"] = "user_boundary"
        result.algorithm_parameters["domain_masked_cells"] = int(
            raw["domain_masked_cells"])
    # The Python resolver is authoritative for the annotation (pyproj-aware);
    # it also emits the geographic-CRS upgrade warning exactly like the pure
    # path. The kernel resolved the same policy with its builtin table.
    policy = resolve_distance_policy(dataset.crs or None, options.distance_policy)
    result.algorithm_parameters["distance_policy"] = policy["policy"]
    result.algorithm_parameters["distance_policy_annotation"] = policy["annotation"]
    return result


def interpolate_factor(
    dataset: GeologicalFactorDataset,
    options: InterpolationOptions | None = None,
) -> FactorGridResult:
    """`interpolator.interpolate_factor` with the C++ kernel when available."""
    if options is None:
        options = InterpolationOptions()
    is_kriging = options.method.lower() in ("kriging", "ordinary_kriging", "ok")
    if _kernel is not None and (not is_kriging or _cpp_kriging_ok(options)):
        return _cpp_interpolate_factor(dataset, options)
    return _py_interpolate_factor(dataset, options)


def extract_factors(
    records,
    factor_name: str,
    *,
    target_horizon: str = "",
    unit: str | None = None,
    crs: str = "",
) -> GeologicalFactorDataset:
    """`GeologicalMappingPipeline.extract_factors` with the C++ kernel when available."""
    if _kernel is None:
        return GeologicalMappingPipeline().extract_factors(
            records, factor_name, target_horizon=target_horizon,
            unit=unit, crs=crs)
    raw = _kernel.extract_factors(
        list(records), factor_name, target_horizon, unit, crs)
    points = [
        GeologicalFactor(
            name=p["name"],
            value=p["value"],
            unit=p["unit"],
            well_id=p["well_id"],
            well_name=p["well_name"],
            x=p["x"],
            y=p["y"],
            crs=p["crs"],
            formation=p["formation"],
            qc_flag=p["qc_flag"],
            metadata=dict(p["metadata"]),
        )
        for p in raw["points"]
    ]
    metadata = dict(raw["metadata"])
    if metadata.get("coordinate_key_family_mixing"):
        logger.warning(
            "extract_factors(%r): records mixed coordinate key families %s "
            "(possible merge of two different CRSs into one dataset)",
            factor_name,
            metadata.get("coordinate_key_families_used"),
        )
    return GeologicalFactorDataset(
        factor_name=raw["factor_name"],
        unit=raw["unit"],
        target_horizon=raw["target_horizon"],
        crs=raw["crs"],
        points=points,
        metadata=metadata,
    )


def nearest_neighbor_class_grid(
    points,
    *,
    extent: tuple[float, float, float, float],
    grid_n: int = 80,
    clip_ring=None,
):
    """`well_prediction_surface.nearest_neighbor_class_grid` with the C++ kernel when available."""
    if _kernel is None:
        return _py_nearest_neighbor_class_grid(
            points, extent=extent, grid_n=grid_n, clip_ring=clip_ring)
    raw = _kernel.nearest_neighbor_class_grid(
        [{"x": p.x, "y": p.y, "facies": p.facies} for p in points],
        [float(v) for v in extent],
        int(grid_n),
        [[float(x), float(y)] for x, y in clip_ring] if clip_ring else None,
    )
    grid_z = np.array(raw["grid_z"], dtype=np.float32).reshape(
        (len(raw["grid_y"]), len(raw["grid_x"])))
    return (
        grid_z,
        np.asarray(raw["grid_x"], dtype=np.float64),
        np.asarray(raw["grid_y"], dtype=np.float64),
        tuple(raw["facies_names"]),
    )
