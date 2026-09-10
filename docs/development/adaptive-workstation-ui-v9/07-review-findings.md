# 07 — Review Findings (V9)

Three review rounds; all P0/P1 fixed and regression-tested. P2s fixed unless noted in 08.

## Round 1 — Architecture / Correctness

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| P1-1 | P1 | `_restore_layout` normalization misclassified restored-hidden inspectors as responsive → wide viewports reopened panels the user closed across sessions (the save suppress hack guarantees responsive hides never persist hidden, so restored-hidden is always user intent) | Normalize to `_user_hid_inspector` + persist; two-session regression test |
| P1-2 | P1 | First-run map-dominant sizing was dead code under the production synchronous-show construction order (`_pending_default_sizes` set after showEvent had fired) — fresh installs opened with QMainWindow's even split (inspector column ~717px) | Consume the flag immediately when visible in `_restore_layout`; regression test |
| P2-* | P2 | Teardown dock-list duplication; agent panel id mismatch (`workstation:process` vs `:agent`); `PALEO_PAGE_FADE` documented but unimplemented; command-input floor constants local; dead `_FLOAT_MIN_SIZE`; unused import; brittle source-string test assertion; missed lifecycle threshold sync | All fixed; ratchet docstring self-contradiction fixed; `style.refresh()` added (repeated `bind` accumulated `destroyed` connections) |

## Round 2 — UX / Accessibility / Visual

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| P0-1 | **P0** | `float_all_panels` programmatically floated GL docks — `DockWidgetFloatable` only gates the *user's* title-bar affordance; programmatic `setFloating(True)` is unchecked. One menu click back into the documented EGL segfault class | Respect `can_float` from the descriptor registry; status message explains the restriction; regression test |
| P1-1 | P1 | Responsive inspector fold was silent; manual close while compact was un-attributed → wide viewport resurrected a user-closed panel (live path, persisted across restarts by the save suppress hack); `toggle_inspector()` dead code | Attribution rides `toggleViewAction().triggered` (user interaction only; programmatic setVisible/restoreState never trigger it — `visibilityChanged` proved unusable, asynchronously delivered after the policy flag reset). Fold/restore emit status messages; manual reopen clears both flags, manual close takes exclusive user semantics |
| P1-2 | P1 | HubScrollArea default `StrongFocus`: phantom tab stop, click-focus theft; focused children not scrolled into view | `NoFocus` + FocusIn → `ensureWidgetVisible` |
| P2-1/2/3 | P2 | GL docks' float button vanished without explanation; legacy page minimums force hub h-scrollbar at narrow widths; compact loses the 层位 caption | Status message on float-all; documented in 08; `accessibleName("层位")` on the combo |
| P3 | P3 | Leftover class-level min/max bands (boundary/evidence/result panels); ElidedFootnoteLabel stale elision after font change; app-bar project name clipping; 显示枢纽页 vs 功能页 naming | Documented in 08 (bands are inert — call sites lift the max) |

## Round 3 — Adversarial / Performance

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| P1-1 | P1 | Viewport policy blind when docks absorb the window shrink: only the central frame's `resizeEvent` triggered evaluation; with the canvas pinned at its floor the frame width never changes → zero policy evaluations at exactly the compact widths | Host-window `eventFilter` on `QEvent.Resize` feeds the same 180ms debounce; QA test-hermeticity contributor fixed (global settings sterile) |
| P1-2 | P1 | 「恢复默认布局」 never re-applied first-run sizes (docstrings claimed it did) — wrecked layouts unrecoverable without wiping QSettings | Deferred (50ms) re-application after the rearranged layout settles; request-level regression test (geometry is platform-dependent best-effort) |
| P2-1 | P2 | `integrated` preset triggered `resizeDocks` via the agent grow-only affordance — contradicted the B-3 "presets never resize" rule | Affordance removed from the preset path |
| P2-2 | P2 | Theme/density flip costs ~3.2s (36KB QSS app-wide repolish; `app.setStyleSheet` alone 2.83s) — pre-existing, user-visible via Ctrl+Alt+D | Documented in 08 (fix direction: single stylesheet layer + scoped density deltas) |
| P2-3 | P2 | ~70 widgets/cycle leak per shell rebuild (external `geoviz.SeismicView` combos/buttons without parents) + dead-shell command closures until next rebuild | Documented in 08 (upstream fix needed) |
| P2-4 | P2 | Layer-panel manage-row text buttons set a 360px right-column floor (pinning hub dock's practical minimum above the scroll host's 68px) | `Ignored` horizontal policy on the row buttons |

### State-machine hole found during R2 fix verification (fold/restore asymmetry)

Fold ignored `_user_hid_inspector` while restore checked it: a user-hidden panel that got folded in a polluted/edge state could never restore. Closed: fold requires `not user-hidden`; first-run defaults honor the persisted user preference instead of forcing the inspector open. Also surfaced: AppShell-showing tests were leaking the inspector preference through the **global** workstation QSettings across test files — dock-framework and visual-QA v9 modules now keep it sterile (autouse clear).

## Performance summary (R3 probes, offscreen)

- Resize storm 150× (960↔2560): 3.1s, 1 debounced evaluation, 0 saves mid-storm
- Dock show/hide 50×13: 3.7s, no errors; float/dock 30×: 5.2s, GL docks never float
- Preset apply 6×20: 5.0s; save-storm 200 toggles → 1 save (debounce collapses)
- Page switch 100×: 0.57s; navigate 60×: 0.79s
- Theme/density flip: ~3.2s per flip (pre-existing, see P2-2)
- Catalog scale + v8 goal perf suites: 15 passed (17m54s)
