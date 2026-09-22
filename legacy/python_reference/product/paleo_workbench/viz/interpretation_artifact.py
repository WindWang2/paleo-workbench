"""Immutable horizon interpretation artifact (NPZ + embedded descriptor).

Canonical scientific payload is the resolved Z grid — not a UI brush log.
Sparse patches remain in-session only (undo/redo).

Format:
* ``z`` float32 (H, W) — nodata as NaN
* ``__descriptor__`` JSON bytes — schema/metadata/lineage/fingerprints
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

INTERP_ARTIFACT_VERSION = 1
INTERP_ARTIFACT_SUFFIX = ".horizon_interp.npz"


def scientific_fingerprint(
    z: np.ndarray,
    *,
    shape: tuple[int, int],
    vertical_domain: str,
    crs: str | None,
    horizon_key: str,
) -> str:
    """SHA-256 of scientific content only (not display state)."""
    arr = np.ascontiguousarray(z, dtype=np.float32)
    # Hash array bytes + small canonical JSON header.
    h = hashlib.sha256()
    header = {
        "horizon_key": horizon_key,
        "shape": [int(shape[0]), int(shape[1])],
        "vertical_domain": str(vertical_domain),
        "crs": crs or "",
        "dtype": "float32",
        "schema": INTERP_ARTIFACT_VERSION,
    }
    h.update(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    h.update(arr.tobytes())
    return h.hexdigest()


def write_interpretation_artifact(
    z: np.ndarray,
    dest_dir: Path | str,
    name: str,
    *,
    descriptor: dict[str, Any],
) -> Path:
    """Atomically write managed ``.horizon_interp.npz`` under *dest_dir*."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    safe = name.strip().replace("/", "_").replace("\\", "_") or "horizon"
    target = dest / f"{safe}{INTERP_ARTIFACT_SUFFIX}"

    arr = np.ascontiguousarray(z, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"z must be 2-D, got {arr.shape}")
    desc = dict(descriptor)
    desc["artifact_version"] = INTERP_ARTIFACT_VERSION
    desc["shape"] = [int(arr.shape[0]), int(arr.shape[1])]
    desc_bytes = json.dumps(desc, ensure_ascii=False, sort_keys=True).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".npz",
        dir=str(dest),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        # Use file handle so numpy does not append a second ".npz".
        with open(tmp_path, "wb") as handle:
            np.savez(
                handle,
                z=arr,
                __descriptor__=np.frombuffer(desc_bytes, dtype=np.uint8),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target.resolve()


def read_interpretation_artifact(
    path: Path | str,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Load Z grid and descriptor from a managed artifact."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    with np.load(p, allow_pickle=False) as data:
        if "z" not in data:
            raise ValueError(f"interpretation artifact missing z: {p}")
        z = np.ascontiguousarray(data["z"], dtype=np.float32)
        desc: dict[str, Any] = {}
        if "__descriptor__" in data:
            raw = bytes(np.asarray(data["__descriptor__"], dtype=np.uint8).tobytes())
            desc = json.loads(raw.decode("utf-8"))
    return z, desc
