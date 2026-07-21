"""AI-powered data consistency analysis for borehole and fault datasets.

Uses BoreholeRecord / FaultRecord dataclasses from models.py instead
of raw dicts, eliminating Primitive Obsession smell.
"""
from __future__ import annotations

import numpy as np

from .models import BoreholeRecord, FaultRecord


def check_boreholes(boreholes: list[BoreholeRecord]) -> dict:
    """Analyze borehole records for overlaps, invalid coordinates, or depth mismatch.

    Also accepts raw dicts for backward compatibility — they are converted on-the-fly.
    """
    records = _ensure_borehole_records(boreholes)
    issues: list[dict] = []

    for bh in records:
        # Check invalid coordinates
        if not np.isfinite(bh.x) or not np.isfinite(bh.y):
            issues.append({
                "type": "error",
                "borehole": bh.name,
                "message": f"Invalid coordinates: X={bh.x}, Y={bh.y}"
            })

        # Check negative total depth
        if bh.total_depth <= 0:
            issues.append({
                "type": "error",
                "borehole": bh.name,
                "message": f"Non-positive total depth: {bh.total_depth}"
            })

        # Check layers
        last_bottom = 0.0
        for idx, layer in enumerate(bh.layers):
            if layer.top > layer.bottom:
                issues.append({
                    "type": "error",
                    "borehole": bh.name,
                    "message": f"Layer {idx} ({layer.lithology}) has inverted depths: top={layer.top} > bottom={layer.bottom}"
                })

            if layer.top < last_bottom - 1e-5:
                issues.append({
                    "type": "warning",
                    "borehole": bh.name,
                    "message": f"Layer {idx} ({layer.lithology}) top={layer.top} overlaps with previous bottom={last_bottom}"
                })
            last_bottom = max(last_bottom, layer.bottom)

        # Check total depth matching
        if last_bottom > bh.total_depth + 1e-5:
            issues.append({
                "type": "warning",
                "borehole": bh.name,
                "message": f"Layers extend to bottom={last_bottom}, exceeding total depth={bh.total_depth}"
            })

    return {
        "checked_boreholes": len(records),
        "issues": issues,
        "status": "PASS" if not any(x["type"] == "error" for x in issues) else "FAIL"
    }


def check_coplanar_faults(faults: list[FaultRecord]) -> dict:
    """Analyze faults to check if any are coplanar (similar orientation and offset).

    Also accepts raw dicts for backward compatibility.
    """
    records = _ensure_fault_records(faults)
    issues: list[dict] = []

    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            f1, f2 = records[i], records[j]

            n1 = np.array(f1.normal, dtype=np.float64)
            n2 = np.array(f2.normal, dtype=np.float64)

            n1 /= np.linalg.norm(n1)
            n2 /= np.linalg.norm(n2)

            dot = np.dot(n1, n2)
            is_parallel = abs(abs(dot) - 1.0) < 0.05

            if is_parallel:
                d2_adj = -f2.d if dot < 0 else f2.d
                dist_diff = abs(f1.d - d2_adj)
                if dist_diff < 15.0:
                    issues.append({
                        "type": "warning",
                        "faults": [f1.name, f2.name],
                        "message": f"Faults {f1.name} and {f2.name} are coplanar. "
                                   f"Angle diff: {np.degrees(np.arccos(min(abs(dot), 1.0))):.2f}°, "
                                   f"Distance diff: {dist_diff:.2f}"
                    })

    return {
        "checked_faults": len(records),
        "issues": issues,
        "status": "PASS" if not issues else "WARNING"
    }


# ---------------------------------------------------------------------------
# Backward-compat helpers: accept either dataclasses or raw dicts
# ---------------------------------------------------------------------------

def _ensure_borehole_records(data: list) -> list[BoreholeRecord]:
    """Convert raw dicts to BoreholeRecord if needed."""
    from .models import Layer
    out = []
    for item in data:
        if isinstance(item, BoreholeRecord):
            out.append(item)
        elif isinstance(item, dict):
            layers = [
                Layer(
                    top=l.get("top", 0.0),
                    bottom=l.get("bottom", 0.0),
                    lithology=l.get("lithology", "Unknown"),
                    color=l.get("color", (0.5, 0.5, 0.5, 0.8)),
                )
                for l in item.get("layers", [])
            ]
            out.append(BoreholeRecord(
                name=item.get("name", "Unknown"),
                x=item.get("x", 0.0),
                y=item.get("y", 0.0),
                total_depth=item.get("total_depth", 0.0),
                layers=layers,
            ))
        else:
            raise TypeError(f"Expected BoreholeRecord or dict, got {type(item)}")
    return out


def _ensure_fault_records(data: list) -> list[FaultRecord]:
    """Convert raw dicts to FaultRecord if needed."""
    out = []
    for item in data:
        if isinstance(item, FaultRecord):
            out.append(item)
        elif isinstance(item, dict):
            out.append(FaultRecord(
                name=item.get("name", "Unknown"),
                normal=item.get("normal", (1.0, 0.0, 0.0)),
                d=item.get("d", 0.0),
                color=item.get("color", (0.9, 0.2, 0.2, 0.65)),
            ))
        else:
            raise TypeError(f"Expected FaultRecord or dict, got {type(item)}")
    return out
