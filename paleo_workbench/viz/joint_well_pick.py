"""Well pick for joint 3D: two-click + draw-snap fence state (#123 / #124).

Pure logic (no GL). Hosts project wells to screen space, then call
``pick_well_name`` / ``WellPickController``. Fence creation still goes through
``WellSeismicJointHost.add_well_to_well_fence``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Sequence

PickMode = Literal["pick", "draw"]


@dataclass(frozen=True)
class WellScreenGeom:
    """One well projected to 2D screen pixels for hit-testing."""

    name: str
    head: tuple[float, float]
    traj: tuple[tuple[float, float], ...] = ()


@dataclass
class WellPickController:
    """Well-pair interaction: pick (two-click) or draw (drag-snap) modes."""

    mode: PickMode = "pick"
    half_select: str | None = None
    draw_from: str | None = None
    status: str = ""

    def set_mode(self, mode: str) -> str:
        m: PickMode = "draw" if str(mode).lower().startswith("draw") else "pick"
        self.mode = m
        self.half_select = None
        self.draw_from = None
        if m == "draw":
            self.status = "模式：画线吸附 — 从井头拖到另一口井"
        else:
            self.status = "模式：选井两点"
        return self.status

    def clear_half(self, reason: str = "已取消半选") -> str:
        had = self.half_select is not None or self.draw_from is not None
        self.half_select = None
        self.draw_from = None
        if not had:
            self.status = ""
            return ""
        self.status = reason
        return self.status

    def on_escape(self) -> str:
        return self.clear_half("Esc — 取消半选")

    def on_blank_click(self) -> str:
        return self.clear_half("点空白 — 取消半选")

    def on_well_click(self, name: str) -> tuple[str, tuple[str, str] | None]:
        """Process a well hit in **pick** mode.

        Returns
        -------
        status :
            Human-readable status for chrome.
        fence_pair :
            ``(a, b)`` when a pair is complete; else ``None``.
        """
        if self.mode != "pick":
            self.status = "当前为画线模式 — 请拖线或切换到选井两点"
            return self.status, None
        well = (name or "").strip()
        if not well:
            self.status = "未命中井"
            return self.status, None
        if self.half_select is None:
            self.half_select = well
            self.status = f"已选 {well} — 再点另一口井（Esc 取消）"
            return self.status, None
        if self.half_select == well:
            self.status = "同一口井 — 请选另一口"
            return self.status, None
        a, b = self.half_select, well
        self.half_select = None
        self.status = f"建 fence {a}–{b}"
        return self.status, (a, b)

    def on_draw_press(self, name: str | None) -> str:
        """Start drag-line from a well (draw mode)."""
        if self.mode != "draw":
            return ""
        well = (name or "").strip()
        if not well:
            self.draw_from = None
            self.status = "画线：请在井头按下"
            return self.status
        self.draw_from = well
        self.status = f"拖线：从 {well} …"
        return self.status

    def on_draw_release(self, name: str | None) -> tuple[str, tuple[str, str] | None]:
        """Finish drag-line; snap to well head preferred."""
        if self.mode != "draw":
            return "", None
        origin = self.draw_from
        self.draw_from = None
        if not origin:
            self.status = "画线未开始"
            return self.status, None
        well = (name or "").strip()
        if not well:
            self.status = "未吸附到另一口井"
            return self.status, None
        if well == origin:
            self.status = "同一口井 — 请拖到另一口"
            return self.status, None
        self.status = f"建 fence {origin}–{well}"
        return self.status, (origin, well)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dist_point_to_segment(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return _dist(p, a)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _min_traj_dist(p: tuple[float, float], traj: Sequence[tuple[float, float]]) -> float:
    if not traj:
        return float("inf")
    if len(traj) == 1:
        return _dist(p, traj[0])
    best = float("inf")
    for i in range(len(traj) - 1):
        best = min(best, _dist_point_to_segment(p, traj[i], traj[i + 1]))
    return best


def pick_well_name(
    sx: float,
    sy: float,
    wells: Sequence[WellScreenGeom],
    *,
    head_radius_px: float = 16.0,
    traj_radius_px: float = 10.0,
    head_only: bool = False,
) -> str | None:
    """Hit-test: well **head preferred**, then trajectory (#123).

    head_only:
        If True, only snap to well heads (draw-mode release snap, larger radius).
    Returns well name or None. Free-screen pick (not timeslice-locked).
    """
    p = (float(sx), float(sy))
    # Heads first — closest within radius wins
    head_best: tuple[float, str] | None = None
    for w in wells:
        d = _dist(p, w.head)
        if d <= head_radius_px and (head_best is None or d < head_best[0]):
            head_best = (d, w.name)
    if head_best is not None:
        return head_best[1]
    if head_only:
        return None
    # Trajectories second
    traj_best: tuple[float, str] | None = None
    for w in wells:
        d = _min_traj_dist(p, w.traj)
        if d <= traj_radius_px and (traj_best is None or d < traj_best[0]):
            traj_best = (d, w.name)
    if traj_best is not None:
        return traj_best[1]
    return None


def project_render_xyz_to_screen(
    x: float,
    y: float,
    z: float,
    *,
    view_matrix,
    projection_matrix,
    width: float,
    height: float,
) -> tuple[float, float] | None:
    """Project render-space XYZ to widget pixel coords (OpenGL NDC).

    Matrices are Qt ``QMatrix4x4`` (or duck-typed with ``map`` + ``inverted``).
    """
    if width <= 0 or height <= 0:
        return None
    try:
        from PySide6.QtGui import QVector4D

        vpm = projection_matrix * view_matrix
        clip = vpm.map(QVector4D(float(x), float(y), float(z), 1.0))
        if abs(clip.w()) < 1e-8:
            return None
        ndc_x = clip.x() / clip.w()
        ndc_y = clip.y() / clip.w()
        # Outside clip frustum still OK for hit (allow generous)
        sx = (ndc_x + 1.0) * 0.5 * width
        sy = (1.0 - ndc_y) * 0.5 * height
        return float(sx), float(sy)
    except Exception:
        return None


def build_well_screen_geoms(
    trajectories: dict,
    *,
    world_to_render,
    view_matrix,
    projection_matrix,
    width: float,
    height: float,
    traj_stride: int = 4,
) -> list[WellScreenGeom]:
    """Project scene trajectories to screen for hit-testing.

    trajectories:
        name → object with ``.points`` ndarray (N, 3) world XYZ.
    world_to_render:
        callable(x, y, z) → (rx, ry, rz) render space.
    """
    out: list[WellScreenGeom] = []
    for name, traj in (trajectories or {}).items():
        pts = getattr(traj, "points", None)
        if pts is None:
            continue
        import numpy as np

        arr = np.asarray(pts, dtype=np.float64)
        if arr.size == 0 or arr.ndim != 2 or arr.shape[1] < 3:
            continue
        # Head = first sample
        hx, hy, hz = world_to_render(float(arr[0, 0]), float(arr[0, 1]), float(arr[0, 2]))
        head_s = project_render_xyz_to_screen(
            hx, hy, hz,
            view_matrix=view_matrix,
            projection_matrix=projection_matrix,
            width=width,
            height=height,
        )
        if head_s is None:
            continue
        traj_s: list[tuple[float, float]] = []
        step = max(1, int(traj_stride))
        for i in range(0, len(arr), step):
            rx, ry, rz = world_to_render(float(arr[i, 0]), float(arr[i, 1]), float(arr[i, 2]))
            sc = project_render_xyz_to_screen(
                rx, ry, rz,
                view_matrix=view_matrix,
                projection_matrix=projection_matrix,
                width=width,
                height=height,
            )
            if sc is not None:
                traj_s.append(sc)
        # Always include last point
        if len(arr) > 1:
            rx, ry, rz = world_to_render(float(arr[-1, 0]), float(arr[-1, 1]), float(arr[-1, 2]))
            sc = project_render_xyz_to_screen(
                rx, ry, rz,
                view_matrix=view_matrix,
                projection_matrix=projection_matrix,
                width=width,
                height=height,
            )
            if sc is not None and (not traj_s or traj_s[-1] != sc):
                traj_s.append(sc)
        out.append(WellScreenGeom(name=str(name), head=head_s, traj=tuple(traj_s)))
    return out
