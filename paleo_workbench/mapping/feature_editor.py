"""FeatureEditor: Deep module for transactional, layer-level map geometry editing.

Encapsulates spatial hit testing, vertex snapping, coincident shared-node synchronized movement,
strict topology re-closure / non-self-intersection validation (TopologyError auto-rollback),
and transaction undo/redo history behind a clean 6-method interface.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from paleo_workbench.native_backend import native_backend


class TopologyError(Exception):
    """Raised when a geometry operation violates topology invariants."""
    pass


class FeatureEditor:
    """Stateful, transactional layer-level map geometry editor."""

    def __init__(self) -> None:
        self.features: dict[str, dict[str, Any]] = {}
        self.selected_feature_id: str | None = None
        self.selected_vertex_index: int | None = None
        self._undo_stack: list[dict[str, dict[str, Any]]] = []
        self._redo_stack: list[dict[str, dict[str, Any]]] = []
        self._uncommitted_base: dict[str, dict[str, Any]] | None = None

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def load_layer(self, feature_collection: dict[str, Any] | list[dict[str, Any]]) -> None:
        """Load GeoJSON FeatureCollection or list of feature dicts."""
        self.features.clear()
        self.selected_feature_id = None
        self.selected_vertex_index = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._uncommitted_base = None

        feat_list = []
        if isinstance(feature_collection, dict):
            feat_list = feature_collection.get("features", [])
        elif isinstance(feature_collection, list):
            feat_list = feature_collection

        for i, feat in enumerate(feat_list):
            feat_copy = copy.deepcopy(feat)
            feat_id = str(feat_copy.get("id") or f"feature_{i}")
            feat_copy["id"] = feat_id
            self.features[feat_id] = feat_copy

        self._uncommitted_base = copy.deepcopy(self.features)

    def commit(self) -> None:
        """Commit current transaction changes into Undo history stack."""
        if self._uncommitted_base is not None:
            self._undo_stack.append(self._uncommitted_base)
            self._redo_stack.clear()
            self._uncommitted_base = copy.deepcopy(self.features)

    def rollback(self) -> None:
        """Rollback current uncommitted changes to last committed transaction state."""
        if self._uncommitted_base is not None:
            self.features = copy.deepcopy(self._uncommitted_base)

    def undo(self) -> bool:
        """Undo last committed transaction."""
        if not self.can_undo:
            return False

        self._redo_stack.append(copy.deepcopy(self.features))
        self.features = self._undo_stack.pop()
        self._uncommitted_base = copy.deepcopy(self.features)
        return True

    def redo(self) -> bool:
        """Redo last undone transaction."""
        if not self.can_redo:
            return False

        self._undo_stack.append(copy.deepcopy(self.features))
        self.features = self._redo_stack.pop()
        self._uncommitted_base = copy.deepcopy(self.features)
        return True

    def select_at(self, x: float, y: float, tolerance: float = 5.0) -> dict[str, Any] | None:
        """Perform spatial hit testing to select nearest feature and vertex."""
        best_selection: dict[str, Any] | None = None
        min_dist = float("inf")

        for feat_id, feat in self.features.items():
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [])
            if not coords:
                continue

            ring = coords[0] if geom.get("type") == "Polygon" else coords
            for idx, pt in enumerate(ring):
                px, py = pt[0], pt[1]
                dist = math.hypot(px - x, py - y)
                if dist <= tolerance and dist < min_dist:
                    min_dist = dist
                    best_selection = {
                        "feature_id": feat_id,
                        "vertex_index": idx,
                        "distance": dist,
                        "point": (px, py),
                    }

        if best_selection is not None:
            self.selected_feature_id = best_selection["feature_id"]
            self.selected_vertex_index = best_selection["vertex_index"]

        return best_selection

    def _find_coincident_vertices(self, target_point: list[float], tol: float = 1e-4) -> list[tuple[str, int]]:
        """Find all (feature_id, vertex_index) tuples matching target_point."""
        coincident = []
        tx, ty = target_point[0], target_point[1]
        for fid, feat in self.features.items():
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [])
            if not coords:
                continue
            ring = coords[0] if geom.get("type") == "Polygon" else coords
            for idx, pt in enumerate(ring):
                if math.hypot(pt[0] - tx, pt[1] - ty) <= tol:
                    coincident.append((fid, idx))
        return coincident

    def move_selected_vertex(self, x: float, y: float, snap: bool = True) -> bool:
        """Move selected vertex and coincident shared vertices with ring closure and TopologyError auto-rollback."""
        if self.selected_feature_id is None or self.selected_vertex_index is None:
            raise ValueError("No vertex currently selected")

        feat = self.features[self.selected_feature_id]
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords:
            return False

        ring = coords[0] if geom.get("type") == "Polygon" else coords
        orig_point = list(ring[self.selected_vertex_index])

        # Snapshot for auto-rollback
        backup_features = copy.deepcopy(self.features)

        # Find all coincident shared vertices across adjacent polygons
        coincident_targets = self._find_coincident_vertices(orig_point)
        if not coincident_targets:
            coincident_targets = [(self.selected_feature_id, self.selected_vertex_index)]

        # Apply new coordinate to all coincident vertices
        touched_feature_ids = set()
        for fid, v_idx in coincident_targets:
            touched_feature_ids.add(fid)
            f_geom = self.features[fid].get("geometry", {})
            f_coords = f_geom.get("coordinates", [])
            f_ring = f_coords[0] if f_geom.get("type") == "Polygon" else f_coords
            n_pts = len(f_ring)

            f_ring[v_idx] = [float(x), float(y)]

            # Maintain ring closure (ring[0] == ring[-1])
            if v_idx == 0:
                f_ring[-1] = [float(x), float(y)]
            elif v_idx == n_pts - 1:
                f_ring[0] = [float(x), float(y)]

        # Topology Validation for all touched polygon rings
        for fid in touched_feature_ids:
            f_geom = self.features[fid].get("geometry", {})
            f_coords = f_geom.get("coordinates", [])
            f_ring = f_coords[0] if f_geom.get("type") == "Polygon" else f_coords
            errors = native_backend.dispatch("validate_ring", f_ring)
            if errors:
                # Auto-rollback on topology error
                self.features = backup_features
                err_msg = ", ".join(e.get("message", e.get("code", "invalid")) for e in errors)
                raise TopologyError(f"Invalid topology on feature '{fid}': {err_msg}")

        return True

    def add_vertex(self, feature_id: str, x: float, y: float, insert_index: int | None = None) -> bool:
        """Insert a new vertex into polygon ring."""
        if feature_id not in self.features:
            raise KeyError(f"Feature '{feature_id}' not found")

        feat = self.features[feature_id]
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords:
            return False

        ring = coords[0] if geom.get("type") == "Polygon" else coords
        backup_features = copy.deepcopy(self.features)

        idx = insert_index if insert_index is not None else len(ring) - 1
        ring.insert(idx, [float(x), float(y)])

        errors = native_backend.dispatch("validate_ring", ring)
        if errors:
            self.features = backup_features
            err_msg = ", ".join(e.get("message", e.get("code", "invalid")) for e in errors)
            raise TopologyError(f"Invalid topology after vertex insert: {err_msg}")

        return True

    def delete_vertex(self, feature_id: str, vertex_index: int) -> bool:
        """Delete vertex with >= 3 unique vertex protection and topology validation."""
        if feature_id not in self.features:
            raise KeyError(f"Feature '{feature_id}' not found")

        feat = self.features[feature_id]
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if not coords:
            return False

        ring = coords[0] if geom.get("type") == "Polygon" else coords
        unique_pts = len(ring) - 1 if ring[0] == ring[-1] else len(ring)

        if unique_pts <= 3:
            raise TopologyError("Polygon must have at least 3 unique vertices")

        backup_features = copy.deepcopy(self.features)
        ring.pop(vertex_index)

        # Maintain closure
        if ring[0] != ring[-1]:
            ring[-1] = list(ring[0])

        errors = native_backend.dispatch("validate_ring", ring)
        if errors:
            self.features = backup_features
            err_msg = ", ".join(e.get("message", e.get("code", "invalid")) for e in errors)
            raise TopologyError(f"Invalid topology after vertex deletion: {err_msg}")

        return True
