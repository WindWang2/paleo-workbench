# 01 — Layout Architecture (V9)

## Layering rule (unchanged from V6/V7, restated)

```
Domain authority (mapping_workspace, catalog, selection coordination)
        ↓ consumed via seams
Presentation context (ui_context.UIContext, tool_surface availability)
        ↓
Adaptive workstation shell (WorkstationFrame + dock framework V2)
        ↓
Panels / Docks / Toolbars / Inspector (content widgets)
```

The UI never re-derives scientific/tool state. Docks are *chrome*, not state.

## What V9 changes

1. **Dock construction becomes declarative.** A `DockDescriptor` registry (dock_id, title, area, importance, default_visible, can_float, can_tabify, advisory sizes, workflow/context tags) replaces 13 scattered `_add_dock(...)` call sites with data. The shell reads descriptors; nothing else in the codebase hardcodes dock identity. (ui/dock_framework.py)
2. **One resize authority.** Programmatic dock resizing (`QMainWindow.resizeDocks`) is allowed in exactly two situations: (a) first run / explicit "reset default layout", (b) grow-only when an action opens a dock that would otherwise be unusably small. Presets change **visibility only** — never geometry. (DockResizePolicy)
3. **Responsive viewport policy is debounced and classified.** Window-width classification (compact <1100 / normal / wide ≥1600 / ultrawide ≥2200 logical px) drives panel policies on a 180ms debounce, outside the resize hot path. No layout mutation happens inside `resizeEvent`.
4. **Content minimums are advisory, not structural.** Large containers (dock content, trees, panels, pages) use `QSizePolicy` + scroll areas + proportional splitters. Hard minimums on large containers are forbidden by a structural ratchet test; the only sanctioned floors are the central map canvas (min 320 wide — the one document Qt must never starve) and the main window (min 960x600 logical — fits 1366x768@125% ≈ 1093 logical px).
5. **GL-bearing docks are not floatable.** `well`/`seismic` docks drop `DockWidgetFloatable`; `hub` drops it while a GL page is current. This removes the documented EGL reparent crash class at the source. (Defense-in-depth Mesa pin / paintGL guard stays.)

## Ownership map (post-V9)

- `ui/dock_framework.py` — DockDescriptor, DockRegistry (module-level, data-only, testable without Qt), DockResizePolicy helpers.
- `ui/workstation/shell.py` — consumes registry; keeps state machine (preset tracking, persistence, responsive policy via `ViewportPolicyController`).
- Page panels remain page-local; only their sizing contracts change (no fixed widths; min floors ≤180 with scroll fallback).
