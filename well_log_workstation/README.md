# Well Log Workstation

Standalone **log-first** desktop product (wayfinder #207).  
Not Paleo Workbench. Rendering uses **WellLogEngine** in later tickets.

## Run

```bash
# From monorepo root, with PySide6 installed (e.g. repo .venv)
# Prefer Wayland: do NOT set QT_QPA_PLATFORM=xcb
unset QT_QPA_PLATFORM
unset PALEO_FORCE_XCB
unset WLWS_FORCE_XCB

python -m well_log_workstation
```

### Workspace (#217)

**文件 → 新建工区…** / **打开工区…** 选择目录。

```
<workspace>/
  workspace.json   # catalog (not engine Manifest)
  wells/
  plots/
  templates/
```

### Import LAS (#218)

With a workspace open: **文件 → 导入 LAS…**

- Copies file under `wells/<id>/`
- Updates `workspace.json` catalog
- Loads curves into the host session store (readable via `session.sample_value`)

### Multi-track template (#219)

1. Select a well in the left tree  
2. Choose a template in the right list (e.g. **标准三轨 GR-RT-DEN**)  
3. **应用到选中井** / 图版 → 应用当前图版  

Center canvas shows **one well, multiple tracks** (depth + GR/RT/DEN when present).

Depth viewport (host): **scroll wheel zoom**, **drag pan**, **double-click** reset to full range (same gestures on 对比-lite).

### 单井分析图文档 (#220)

- **图件 → 新建单井分析图…** — writes `plots/<id>.json` + catalog entry, opens multi-track view  
- **Double-click** a plot under 图件 in the left tree — reloads well from `wells/` and re-applies template

### 导出 SVG/PDF (#221)

With an active multi-track presentation (apply template or open 单井分析图):

- **导出 → 导出 SVG…** / **导出 PDF…**
- Host paints the same multi-track layout via Qt `QSvgGenerator` / `QPdfWriter` (engine scene export lands later)

### 地层对比图-lite (#222)

Need **≥2 wells** in the workspace catalog:

1. Choose a template in the right list  
2. **图件 → 新建地层对比图…** — multi-select wells → `plots/<id>.json` type `correlation`  
3. Center tab **地层对比图-lite**: side-by-side columns, **shared depth** pan (drag) / zoom (wheel)  
4. Double-click catalog entry under 图件 to reopen

### 层位 / Formation tops (#223)

Tops are host JSON next to the well LAS (`wells/<id>/tops.json`):

```json
{
  "schemaVersion": 1,
  "well_id": "…",
  "tops": [
    { "name": "T1", "depth": 1001.0, "unit": "m", "color": "#c0392b" }
  ]
}
```

- Right pane **层位** list for the selected well  
- Dashed depth markers on **单井** multi-track and **对比** columns  
- **层位 → 导入层位 JSON…** / **生成示例层位**  
- **层位 → 拾取层位（单击图道）** / **按深度添加层位…** (#226)  
  - Pick mode: click on multi-track canvas (or **Shift+click** without mode)  
  - Name dialog → save `tops.json` + inspector + markers  
- Missing or corrupt files → empty list + diagnostics (no crash)

Headless / CI:

```bash
QT_QPA_PLATFORM=offscreen python -m well_log_workstation
# or tests:
QT_QPA_PLATFORM=offscreen pytest tests/test_well_log_workstation_shell.py -q
```

XWayland debug only:

```bash
WLWS_FORCE_XCB=1 QT_QPA_PLATFORM=xcb python -m well_log_workstation
```

### WellLogEngine primary canvas (#224 / #225 / #227)

When the `welllog` package is on `PYTHONPATH` / installed, **applying a multi-track
template** prefers native `WellLogView` (`submit_multi_track`) as the single-well
surface. Host `MultiTrackCanvas` remains automatic fallback.

```bash
export PYTHONPATH="build/well-log-engine-python/python:well-log-engine/python${PYTHONPATH:+:$PYTHONPATH}"
# Force host canvas:
# export WLWS_DISABLE_ENGINE=1
# export WLWS_FORCE_HOST_CANVAS=1
python -m well_log_workstation
# 图件 → 优先使用引擎画布   (toggle; single-well + correlation-lite)
# 图件 → 刷新/打开引擎视图… / 引擎对比预览…
# 层位拾取 switches to host canvas for click hit-testing, then can return to engine
```

Correlation-lite (#228): with prefer-engine, create/open 对比图 calls
`submit_multi_well_section` (shared depth); host `CorrelationCanvas` is fallback.

Horizon links (#229): tops with the **same name** on adjacent wells auto-link
when opening a contrast plot (also **图件 → 按层位名自动连线**). Links draw on
the host canvas and become `horizon_line` overlays on the engine path; stored
in `plots/<id>.json` as `links[]`.

Gap notes: `docs/research/2026-08-03-welllogengine-python-bindings-225.md`

## Phase-1 scope (locked)

| Decision | Choice |
|----------|--------|
| Shell | L — left tree · center tabs · right inspector |
| Workspace | F — directory + `workspace.json` |
| Templates | H — host JSON → Engine presentation (multi-track) |
| Documents | S1 — 单井多图道 + 对比-lite |

## Ticket chain

`#216`–`#223` host workstation vertical slice complete (shell → tops).  
`#224` optional engine preview; `#225` multi-track/session Python bindings.
