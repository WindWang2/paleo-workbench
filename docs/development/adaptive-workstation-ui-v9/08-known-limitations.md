# 08 — Known Limitations (V9)

## Explicit scope exclusions (per goal §19)

No 100GB seismic-volume support, benchmarks, out-of-core architecture, cache architecture, GPU volume paging, or seismic LOD redesign. Current small/medium seismic UI is unchanged apart from dock-chrome behavior.

## Known limitations

1. **resizeDocks geometry is best-effort and platform-dependent.** First-run/reset pane sizing issues descriptor-sized requests; the offscreen test platform frequently ignores them (QMainWindow layout timing). Tests pin the request contract; geometry is verified on real platforms via visual QA. A hard guarantee would require replacing QMainWindow dock management — out of scope.
2. **Page-level legacy minimums still force hub h-scrollbar at narrow widths.** The home relationship diagram (980/1080px floors) and data/mapping pages (~561px) overflow a ~410px hub dock band at 960px windows. Scroll degradation is honest (no blocking), but the pages themselves are not yet fully responsive; the diagram should eventually scroll inside its own viewport instead of flooring the page.
3. **AdaptivePageStack granularity is per-hub, not per-submodule.** `HubPage`'s internal stack still reports the max over its submodules. Harmless under scroll degradation; noted in the docstring.
4. **Theme/density switch costs ~3.2s** on large widget trees (36KB QSS app-wide repolish; `app.setStyleSheet` is 2.8s of it). Pre-existing; fix direction: set only one stylesheet layer per flip and scope density deltas to a lighter selector set.
5. **~70-widget leak per shell rebuild** from the external `geoviz.SeismicView` (parentless combos/buttons), plus dead-shell command-registry closures pinned until the next rebuild. Upstream fix (parent the widgets / unregister `core:*` on shutdown) recommended; bounded in practice because project switches rebuild and re-register.
6. **Offscreen CI cannot validate GL-visual behavior.** GL-bearing docks are not floatable (crash-class prevention), but the EGL reparent hazard itself is only defended, not eliminated (Mesa EGL pin + paintGL guard remain defense-in-depth).
7. **Ratchet allowlists are snapshot-based.** 26 theme-drifted stylesheet sites (26 files) and several sizing exceptions remain allowlisted; they may only shrink. Non-literal sizing arguments (`setFixedWidth(var)`) escape the regex rules — review vigilance still applies.
8. **`toggle_inspector()` API** remains with no production caller (tests use it); user paths all go through the toggle action's attribution. Candidate for removal once the palette gains an inspector entry.
9. **Legacy min/max elastic bands** in three panel classes (boundary/evidence/result) are inert (all call sites lift the max) but still present as constructor defaults — landmines for the next consumer.

## Parallel workstreams

Two sibling V9 branches were active during development (`feat/geological-interpretation-workbench-v9`, `feat/qgis-geological-authoring-v9`, both from the same main base). No file-level overlap was observed at commit time; rebase conflicts, if any, are expected only if those branches also touch the workstation shell.
