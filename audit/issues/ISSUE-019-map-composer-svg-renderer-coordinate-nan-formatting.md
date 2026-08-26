# ISSUE-019: Map Composer SVG Renderer Coordinate Formatting & Scale Bar Zero-Division

- **Severity**: Medium
- **Subproject**: `paleo_workbench` (`paleo_workbench/mapping/composer`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/mapping/composer/renderer.py#L48-L82`
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/mapping/composer/renderer.py#L103-L113`

---

## Defect Description & Root Cause Analysis

In `paleo_workbench/mapping/composer/renderer.py`:
1. In `MapComposerRenderer._render_element_svg()`:
```python
pts_str = " ".join(
    f"{_map_pt(p[0], p[1])[0]:.2f},{_map_pt(p[0], p[1])[1]:.2f}"
    for p in ring if len(p) >= 2
)
```
When vector layer vertices contain non-finite numbers (`float('nan')` or `float('inf')` originating from unprojectable geometries or null features), Python formats the coordinate string as `"nan,nan"` or `"inf,inf"`.
This produces invalid SVG polygon coordinates (e.g. `<polygon points="100.00,200.00 nan,nan 150.00,300.00"/>`). Standard SVG parsers (such as web browsers, Adobe Illustrator, Inkscape, or QtSvg) reject or fail to render the document.

2. In `ElementType.SCALE_BAR` rendering (lines 103-113):
```python
length_km = elem.properties.get("length_km", 50)
f'<text x="{x + w/2}" y="{y + h - 1}" ...>{length_km//2}</text>'
```
If `length_km <= 0` or width `w <= 0`, scale bar division and text formatting produce broken zero-extent graphics.

---

## Impact Analysis

- **Corrupted SVG Exports**: Vector map exports contain invalid SVG syntax when spatial layers include null/NaN coordinates.
- **Cartographic Defects**: Corrupted scale bars in exported map compositions.

---

## Reproduction Scenario & Execution Proof

### Code Trace
```python
ring = [[10.0, 20.0], [float("nan"), float("nan")], [30.0, 40.0]]
pts_str = " ".join(f"{p[0]:.2f},{p[1]:.2f}" for p in ring if len(p) >= 2)
print("Generated SVG points:", pts_str)
# Output: '10.00,20.00 nan,nan 30.00,40.00' (Invalid SVG syntax)
```

---

## Concrete Suggested Fix

Filter vertices with `math.isfinite()` prior to formatting coordinate pairs into SVG attributes:

### Patch (`paleo_workbench/mapping/composer/renderer.py`)
```python
# In MapComposerRenderer._render_element_svg():
import math

def _valid_pt(p: Any) -> bool:
    return len(p) >= 2 and math.isfinite(float(p[0])) and math.isfinite(float(p[1]))

pts_str = " ".join(
    f"{_map_pt(float(p[0]), float(p[1]))[0]:.2f},{_map_pt(float(p[0]), float(p[1]))[1]:.2f}"
    for p in ring if _valid_pt(p)
)
```
