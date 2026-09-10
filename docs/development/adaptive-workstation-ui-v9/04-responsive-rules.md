# 04 — Responsive Rules (V9)

## Supported envelopes

Window sizes (logical px): 1366×768 · 1600×900 · 1920×1080 · 2560×1440 · 3840×2160.
DPI: 100% / 125% / 150% / 200% (Qt logical-px model; 1366@125% ⇒ ~1093 logical px ⇒ COMPACT).

Hard floors (the whole constraint stack):

| Surface | Floor | Rationale |
|---|---|---|
| Main window | 960×600 | smallest supported envelope with all core docks docked |
| Central map canvas | 320 wide | the one document Qt must never starve |
| Inspector | 220 | form still usable; elides below |
| Explorer | 180 | tree still readable; elided footnote never locks it |
| Page side panels | 200 | panels resize freely above the floor; splitters collapse below |

## Viewport classes

`classify_viewport(width)`: COMPACT <1100 · NORMAL · WIDE ≥1600 · ULTRAWIDE ≥2200 (ui/dock_framework.py).

Policies (all evaluated on a 180ms debounce, never inside `resizeEvent`):

| Class | Policy |
|---|---|
| COMPACT | inspector folds responsively (restore ≥1200, hysteresis); app-bar command input floor 220; stage-bar horizon label hidden |
| NORMAL | defaults |
| WIDE / ULTRAWIDE | no forced changes; viewport never *adds* chrome |

Rules of the system:
1. **Viewport policy ≠ user preference.** Density/font is user-owned; viewport class only touches non-preference constraints. Responsive folds never invalidate the active layout preset (`_preset_tracking_paused` guard).
2. **No layout mutation in the resize hot path.** `resizeEvent` only (re)starts the debounce timer.
3. **Restore normalization.** After `restoreState`, an inspector that comes back hidden with neither flag (`_user_hid_inspector` / `_responsive_hid_inspector`) is normalized to responsive-hidden so wide viewports auto-restore it.
4. **Degradation ladder for content that can't shrink**: collapse side panel (splitter) → scroll (HubScrollArea/page scroll containers) → never block the dock handle.

## DPI

Icon factories render at `devicePixelRatioF` (workstation/common.py, components/states.py); map canvas uses DPR float; Wayland fractional-scale rounding opt-in via `PALEO_WAYLAND_INTEGER_SCALE`. Runtime screen-set changes (`screenAdded`/`screenRemoved`/`primaryScreenChanged`) re-clamp the host window and floating docks to the visible desktop.
