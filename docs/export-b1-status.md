# Export B1 status (T16 / #304)

Closeout summary of **WellPlot Desktop export B1** core slices delivered under
issue **#304** (track T16). Selection ADRs and implementation slices below are
**shipped**; items listed under [Not claimed](#not-claimed) must not appear as
product promises.

## Selection ADRs

| ADR | Decision |
|-----|----------|
| [0053](adr/0053-searchable-pdf-b1-path.md) | Searchable PDF is an **explicit** optional path; default remains glyph-outline (ADR 0047) |
| [0054](adr/0054-cgm-export-backend-b1.md) | CGM is a **standalone** export backend (self-written CGM V3 Binary subset), not a silent plugin |

## Shipped slices

### B1.PDF.1–3 (searchable PDF)

| Slice | Delivered |
|-------|-----------|
| **B1.PDF.1** | Host dual option `outline` / `searchable`; product mode names and disclosures |
| **B1.PDF.2** | Engine `searchable_text`: Base-14 Helvetica Latin/ASCII band overlay; `export_scene_pdf(..., searchable_text)`; fallback to Qt if binding lacks the flag |
| **B1.PDF.3** | Latin-1 (WinAnsi Helvetica) + UTF-8 decode; CJK dropped from searchable layer with counters (`SearchableTextStats` / `non_latin_codepoints_dropped`) |

**Searchable PDF scope:** Latin-1 extractable text layer. Visual outlines still
come from glyph paths. Full embedded-font **ToUnicode / CJK subset** is
**deferred** (see below).

### B1.CGM.1–3 (CGM backend)

| Slice | Delivered |
|-------|-----------|
| **B1.CGM.1** | `CgmBinaryWriter` + `CgmSceneExporter` (polylines, track frames, Latin TEXT); headless `welllog.cgm-spike` |
| **B1.CGM.2** | Interval/crossover fill → solid POLYGON + `CgmExportDiagnostics`; `export_scene_cgm` binding; host **导出 → CGM…** + degradation disclosure |
| **B1.CGM.3** | Fixed page-height multi-PICTURE pagination; pattern ≈ solid + diagonal hatch + diagnostics; `cgm_scene_to_vdc`; host golden entry tol `TOL_MM_CGM=0.5` |

### B1.GEOM (multi-format geometry matrix)

| Metric | Tolerance |
|--------|-----------|
| Primary layout / page box / SVG viewBox / pure CGM VDC↔mm / cross-format layout | **0.1 mm** |
| CGM track-left (export-path proxy) | **0.5 mm** entry (ADR 0054) |
| Fixed pagination page count | exact |

Fixture and matrix: `well-log-engine/apps/wellplot-desktop/well_log_workstation/testdata/geometry_golden/`,
`well-log-engine/apps/wellplot-desktop/well_log_workstation/geometry_golden.py`, and related tests.

## Not claimed

Do **not** advertise these as delivered B1:

- Full technical-plan **§16** multi-well / full export geometry matrix
- Full engine PDF **CJK ToUnicode** font-subset searchable path
- Engine PDF band-text anchors at 0.1 mm (deferred golden dimension)
- Full CGM scene-clip vs host layout at 0.1 mm (entry remains 0.5 mm on the
  export-path proxy)
- CGM as default engineering delivery format; WebCGM / import

## Related docs

- Host export UI table: [`well_log_workstation/README.md`](../well-log-engine/apps/wellplot-desktop/well_log_workstation/README.md)
- Geometry golden notes: [`well_log_workstation/testdata/geometry_golden/README.md`](../well-log-engine/apps/wellplot-desktop/well_log_workstation/testdata/geometry_golden/README.md)
- Domain vocabulary: [`CONTEXT.md`](../CONTEXT.md) — Export B0 / B1
