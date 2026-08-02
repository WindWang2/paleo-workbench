# Well Log Workstation

Standalone **log-first** desktop product (wayfinder #207).  
Not Paleo Workbench. Rendering uses **WellLogEngine** in later tickets.

## Run (#216)

```bash
# From monorepo root, with PySide6 installed (e.g. repo .venv)
# Prefer Wayland: do NOT set QT_QPA_PLATFORM=xcb
unset QT_QPA_PLATFORM
unset PALEO_FORCE_XCB
unset WLWS_FORCE_XCB

python -m well_log_workstation
```

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

## Phase-1 scope (locked)

| Decision | Choice |
|----------|--------|
| Shell | L — left tree · center tabs · right inspector |
| Workspace | F — directory + `workspace.json` |
| Templates | H — host JSON → Engine presentation (multi-track) |
| Documents | S1 — 单井多图道 + 对比-lite |

## Ticket chain

`#216` shell → `#217` workspace → `#218` LAS import → `#219` multi-track template → …
