# 07 — Performance & Lifecycle

## Rendering model (inherited from upstream pattern)

- `PwbPlotItem::paint` renders the owned `Qgs2DPlot` into a cached `QImage` at
  `devicePixelRatio`; cache invalidated only on data/range/rect change
  (`updateRect`/`updatePlot`/`setPlotData`). Pan/zoom invalidate; hover
  crosshair is a **separate overlay item** — hover never re-renders the plot.
- No O(N²) paths: series data is appended once per `setPlotData`; snap/hover
  uses a linear nearest scan per item over visible series — same asymptotics
  as the retired `PlotWidget` (its Python-oracle port intentionally uses the
  linear scan). Downsample/LOD stays a *consumer* concern via the existing
  `viz_charts` LTTB kernel — the canvas does not silently drop data.
- Multi-track pages: one `PwbPlotCanvas`, N items. `updatePlot` marks each
  item dirty once; one `scene()->update()` per nav step — not per track.

## Lifecycle rules (upstream-derived, verified against `qgsplotcanvas.cpp`)

1. `QgsPlotCanvas` destructor **does not delete scene items** — `PwbPlotCanvas`
   owns its items via `std::unique_ptr`… wait, no: items are parented into the
   scene; the scene outlives the canvas object only inside the member
   destruction window. To match upstream (elevation canvas keeps raw pointers,
   items die with the scene), `PwbPlotItem` is held by raw pointer, deleted by
   the scene destructor. Tools are `QObject`-parented to the canvas and
   self-unset via `unsetTool` — safe.
2. `willBeDeleted()` is emitted in the canvas destructor; tools null their
   `mCanvas` there. `PwbPlotCanvas` must not touch items after that.
3. `cancelJobs()` override: we run no background render jobs (plots render
   synchronously — upstream renders synchronously too; the async part in
   elevation is the *data gatherer*, which here is the consumer's choice via
   `QgsTaskManager`). `cancelJobs` = cancel nothing, but overridden to be
   explicit + future-proof.
4. Page teardown: `PwbPlotPanel` is a normal `QWidget`; canvas child-deleted
   by Qt parent chain. No singletons, no statics, no Python.
5. Rebind (`show_well_head` twice, `set_data` twice): item contents replaced
   in place — no item churn, no leak (QgsPlotData deep-copies series).

## Known perf caveats (recorded honestly)

- `Qgs2DXyPlot::render` redraws axes/labels each image-cache miss — fine at
  preview sizes; at >4k the image cache dominates. If profiling later shows
  label layout hot, upstream's `calculateOptimisedIntervals` is already the
  mitigation (intervals chosen to fit).
- Vector export re-runs `render` on a fresh `QgsRenderContext` — no image
  cache reuse; export is cold-path by definition.
- `QgsPlotData` deep-copies series on assignment; we `setPlotData` wholesale
  rather than mutating — documented cost, bounded by decimation upstream.
