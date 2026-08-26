# ISSUE-009: PNG Canvas Export Coordinate Shrinkage to 25% Scale

- **Severity**: High
- **Subproject**: `well-log-engine` (`apps/wellplot-desktop/well_log_workstation`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/well-log-engine/apps/wellplot-desktop/well_log_workstation/export_dispatch.py#L478-L495`

---

## Defect Description & Root Cause Analysis

In `well_log_workstation/export_dispatch.py`, `_qt_paint_export()` handles high-resolution raster image rendering for PNG export:

```python
w_mm, h_mm = spec.width_mm, spec.height_mm
pm = QPixmap(int(w_mm * 4), int(h_mm * 4))  # ~4 px/mm (~100 dpi)
pm.fill(QColor("#ffffff"))
painter = QPainter(pm)
try:
    paint_fn(painter, QRectF(0, 0, w_mm, h_mm))
    if border_frame:
        _draw_qt_frame_border(
            painter,
            QRectF(0, 0, w_mm, h_mm),
            margin_mm=10.0,
            mm_per_unit=4.0,
        )
```

`QPixmap` operates strictly in device pixel coordinates without an automatic millimeter-to-pixel coordinate transform.
For an A4 page ($210\text{ mm} \times 297\text{ mm}$), the allocated `QPixmap` has pixel dimensions of $840 \times 1188$.
However, `painter.scale(4.0, 4.0)` is never called. `paint_fn` is invoked with `QRectF(0, 0, 210, 297)`.

As a result, the entire well plot is rendered into a tiny $210 \times 297$ pixel bounding box in the top-left corner of the $840 \times 1188$ image canvas. This occupies only $25\%$ of the width, $25\%$ of the height, and $6.25\%$ of the total exported pixel area, leaving $93.75\%$ of the canvas completely blank.

---

## Impact Analysis

- **Export Distortion**: All single-well, cross-section, and correlation PNG exports are rendered as miniature thumbnails in the upper-left corner with massive empty white borders.
- **Reporting Quality**: Exported PNG diagrams are unusable for professional publishing and technical reporting.

---

## Reproduction Scenario & Execution Proof

### Code Trace
1. Trigger PNG plot export for an A4 template ($210 \times 297\text{ mm}$).
2. The generated PNG has image dimensions $840 \times 1188$ px.
3. Open the output PNG file: the drawn plot only occupies pixel range $[0, 210] \times [0, 297]$. The remaining region $[210, 840] \times [297, 1188]$ is blank white.

---

## Concrete Suggested Fix

Scale the `QPainter` coordinate transform by `scale_factor = 4.0` so that 1 unit in `paint_fn` corresponds to $1\text{ mm}$ ($4\text{ px}$).

### Patch (`well-log-engine/apps/wellplot-desktop/well_log_workstation/export_dispatch.py`)
```python
# In _qt_paint_export():
w_mm, h_mm = spec.width_mm, spec.height_mm
scale_factor = 4.0
pm = QPixmap(int(w_mm * scale_factor), int(h_mm * scale_factor))
pm.fill(QColor("#ffffff"))
painter = QPainter(pm)
painter.scale(scale_factor, scale_factor)
try:
    paint_fn(painter, QRectF(0, 0, w_mm, h_mm))
    if border_frame:
        _draw_qt_frame_border(
            painter,
            QRectF(0, 0, w_mm, h_mm),
            margin_mm=10.0,
            mm_per_unit=1.0,
        )
```
