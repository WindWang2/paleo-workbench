# THROW AWAY — Well Log Workstation shell chrome prototype

**Not production.** Answers wayfinder [#214](https://github.com/WindWang2/paleo-workbench/issues/214):
does **L** chrome (left tree · center tabs+canvas · right inspector) feel like a log-first ResFormSTAR-class shell?

## Run (Wayland)

```bash
cd /path/to/paleo_project
# Do NOT set QT_QPA_PLATFORM=xcb — use session Wayland
unset QT_QPA_PLATFORM
unset PALEO_FORCE_XCB
# optional software GL if GPU path is flaky:
# export LIBGL_ALWAYS_SOFTWARE=1
# optional welllog wheel:
# export PYTHONPATH=.../site-packages

python prototypes/well-log-workstation/shell_chrome_throwaway.py
```

If `welllog` is importable, the center host tries a real `WellLogView`; otherwise a painted mock multi-track canvas is used.
