# Research: ResFormSTAR / ResForm GeoOffice — public workflow inventory

**Ticket:** [#208](https://github.com/WindWang2/paleo-workbench/issues/208) (map [#207](https://github.com/WindWang2/paleo-workbench/issues/207))  
**Date:** 2026-08-03  
**Scope:** User-visible primary workflows and document types from **public** Chinese oilfield software materials only. No reverse-engineering of binaries, private formats, or dongle/UI pixels.  
**Goal:** Enough inventory to draft a parity checklist for an independent **WellLogEngine-backed Well Log Workstation**.

---

## 1. Product lineage (public naming)

| Name | Role in public materials |
|------|---------------------------|
| **卡奔** | Prior-generation desktop geology drafting tool; ResForm is discussed as its upgrade/successor in user forums. |
| **ResForm** | Application framework from 西安海卓石油信息技术有限公司 (HaiZhuo / petrohd.com). |
| **ResForm GeoOffice / 《地质研究工作室》** | Primary desktop product: daily geological analysis, research, and drafting under ResForm. |
| **ResForm GeoOffice R.E.** | Reservoir-engineering edition: GeoOffice figure suite **plus** static/dynamic production analysis charts. |
| **ResFormSTAR** | Market/version branding used in later software-catalog pages (e.g. “ResFormSTAR最新版2023”) whose body copy restates GeoOffice capabilities; forum feature posts also use “ResFormSTAR软件特色功能-…”. Treat as **same product family UX surface**, not a separate public architecture. |
| **GeoWorkings for ResForm** | Multi-client enterprise shell on ResForm; remote data service + template-driven plot generation. |
| **SinoLog Pro** | Related HaiZhuo log-processing product; out of scope for workstation shell parity except as adjacent product line. |

**Vendor first-party claim (homepage / product pages):** ResForm GeoOffice is a general desktop tool for daily geological analysis, research, and drafting; solves resource integration, document compatibility, geological analysis & drafting, and building network applications under a unified architecture; supports **workspace management** (local + network workspaces) and direct open/create of **单井图、地层对比图、剖面图、平面图、栅状图、综合图**.

Sources: [petrohd.com](https://www.petrohd.com/), [petrohd.com/resformgeooffice](https://www.petrohd.com/resformgeooffice), [petrohd.com/resformgeoofficeRE](https://www.petrohd.com/resformgeoofficeRE), [oilsofts ResFormSTAR 2023](http://www.oilsofts.com/?p=4011), [oilsofts GeoOffice 3.2/3.5 blurb](http://www.oilsofts.com/?p=2154).

---

## 2. Workspace / project model

Public materials consistently describe a **工区 (workspace / study area)** as the top container:

| Concept | Public description |
|---------|-------------------|
| **本地工区** | Local workspace; local data service typically backed by **Microsoft Access**. |
| **网络工区** | Network workspace; multi-site data services over **SQL Server / Oracle** (and custom DBs). |
| **数据服务** | Configurable local and/or multi-site network data services bridging to E&P databases. |
| **组织层级** | Data prepared by **油田 → 区块 → 井** (field → block → well). |
| **井筒数据准备** | Explicit UI path to prepare wellbore data after configuring a data service; per-well folders under the field. |
| **文档目录** | Within a workspace, document lists for 单井图 / 地层对比图 / 剖面图 / 栅状图 / 平面图 / 综合图表 — i.e. **document-centric**, not page-of-a-map-app. |
| **UI style** | “Office操作风格”; task pane actions such as open/close workspace. |
| **运行形态** | Framework blurbs mention local, C/S, and B/S run modes (enterprise GeoWorkings path). |

**Well identity / catalog fields (data-management tutorials):** well name, X/Y, KB (补心高), TD (完钻井深); batch import of well locations; continuous append of new materials.

**Import/bootstrap paths called out publicly:**

- Batch load of drilling / mud log / core / well log / testing / lab / formation / tops.
- Import from legacy **卡奔** databases.
- Build database from existing plot documents (e.g. copy well positions from a section wizard; “复制全井数据” from a figure).

Sources: [oilsofts module blurb](http://www.oilsofts.com/?p=2154), [Baidu experience: ResForm数据管理](https://jingyan.baidu.com/article/335530da48d34b58ca41c330.html), [agoil guide thread titles](https://bbs.agoil.cn/read-htm-tid-194283.html), vendor homepage.

**Implication for Workstation:** phase-1 needs a **local workspace + well catalog + figure documents**, not necessarily multi-site Oracle/SQL Server. Network workspace is product-family feature, not phase-1 log MVP.

---

## 3. Primary document types (user-visible)

Public materials converge on a small set of **first-class figure documents**:

| # | Document type | Chinese terms | Role |
|---|---------------|---------------|------|
| 1 | **Single-well plot** | 单井图 / 单井分析图 | Foundation of the product; many specialized plot recipes. |
| 2 | **Stratigraphic correlation** | 地层对比图 / 地层对比 (剖面工作方式) | Multi-well tops/links research; produces correlation results. |
| 3 | **Reservoir / well-tie section** | 剖面图 / 油藏剖面图 / 油藏连井剖面图 | Presentation-quality section; richer edit than pure correlation. |
| 4 | **Planar map** | 平面图 | Point/line/area layers with geological semantics; structure, lease, OIP area, attribute contours. |
| 5 | **Fence / grid diagram** | 栅状图 / 油层栅状图 | Rotatable 3D-ish display of OWC/fluid relationships; often **generated from correlation results**. |
| 6 | **Composite chart** | 综合图 / 综合图表 | Arbitrary collage of the above; embedded figures can refresh dynamically. |

**Derived / secondary chart types** (from base documents or data):

- 油气藏剖面图 (when listed separately from generic 剖面图)
- 属性等值线图
- 对比数据表 / 油层解释数据表
- 样点频率分布图、数据交会图、三角图 (frequency, cross-plot, ternary)

Sources: oilsofts blurbs, Baidu data-management article, petrohd product claims, ResFormSTAR catalog page.

---

## 4. Workflow inventory by concern

### 4.1 Data load

Publicly listed well-log load methods (extensible):

- **Txt**, **Excel**, multi-format **716**, **LAS**, **Forward**, **Wis**, **List**

Also: bulk well-location load; multi-domain wellbore tables (drilling, mud log, core, log, test, lab, formation, **分层** tops). User tutorials emphasize intelligent column mapping for batch load.

**Not claimed as required for basic drafting in public blurbs:** reverse-engineering proprietary ResForm workspace files. CONTEXT.md already scopes Paleo import to **public formats + ResForm-compatible semantics** (`resform-compatible-v1`), not private 工区 files.

### 4.2 Templates / tracks (单井图)

- **≥20 track types** (图道类型) with rich fill colors.
- Track composition supports specialized single-well recipes, e.g.:
  - 地层综合柱状图
  - 录井图
  - 岩芯综合图
  - 四性关系图
  - 沉积储层评价图
  - 油气水解释成果图
  - 典型曲线图
- Dual modes on the single-well document:
  - **绘图模式** (default): drafting-oriented.
  - **解释模式**: header fixed; tracks scroll with depth (quick-start guide language).
- Macro / script editor for advanced automation.
- Enterprise path (GeoWorkings): **graphic templates** that auto-load well-track data from remote services for fast plot/preview.
- Marketed ResFormSTAR refinements (forum/catalog feature titles only — treat as existence signals, not full specs): step/square-wave curves, single-well screenshot, statistics tables driving plots.

User forums also refer to **fluid/interpretation templates** that style fill by log interpretation conclusion (left/right fill patterns on sections).

### 4.3 Single-well plot workflow (central)

1. Open/create 工区 → prepare/select 井.
2. Load curves + ancillary intervals.
3. Create **单井分析图** document; apply multi-track layout / template.
4. Work in 绘图 or 解释 mode; pan/zoom depth; edit track content/styles.
5. Pick/edit **分层** and interpretation annotations as needed.
6. Export/print/screenshot or embed into 综合图.

### 4.4 Multi-well correlation (central to product; phase decision for Workstation)

Public product language:

- 剖面图 has **two independent work modes**: **地层对比** vs **油藏剖面图**.
- **地层对比:** focus on inter-well **对比连接关系** (correlation links) and correlation results; can **switch into single-well interpretation** mid-flow so single-well and multi-well stay one loop.
- Correlation results feed generation of reservoir sections, fence diagrams, attribute contours, and correlation tables.

User-facing link/tops vocabulary from product + forum discussion:

- 分层 / 分层对比
- 对比连接 / 连层编辑
- Curve-segment guided auto-correlation (feature posts: select a curve interval on one well → auto-match on others)
- Lithology connection styles (straight vs jagged), fluid contacts with control points

### 4.5 Reservoir / cross-section (central to full GeoOffice; heavier than pure log view)

- Rich interactive editing aimed at **presentation-quality** reservoir sections.
- Faults, fluid interfaces, fill styles, trajectory/depth correction topics appear in public user discussion (quality of 卡奔 migration, multi-file trajectories, etc.).
- Not the same UX as “just several single-well tracks side by side” — correlation research mode vs polished section mode are separated by design.

### 4.6 Planar maps, fence, composite (peripheral for log workstation phase-1)

- **平面图:** point/line/polygon layers, multi-layer management, kriging and other grids, contour fill modes; well-spot batch load.
- **栅状图:** rotation and interactive control for OWC intuition; often produced from correlation products.
- **综合图:** collage + dynamic refresh from source figures + free graphics.

### 4.7 Export / deliverables

Public materials emphasize:

- High-quality **drawing** as first-class outcome (Office-style editing).
- Generation of **tables** (对比数据表, 油层解释数据表) from correlation.
- **Screenshot** of single-well plots (ResFormSTAR feature marketing).
- Composite assembly for reports.
- Enterprise: exchange data / store documents against remote services.

Explicit PDF/SVG/print pipeline details are **not** richly documented in the free public blurbs reviewed; treat “export publication figure + tables” as the user-visible requirement, implementation free.

---

## 5. Central vs peripheral for a phase-1 log workstation

Framing: **independent Well Log Workstation**, engine-backed (map #207), **not** cloning GeoOffice’s full geology studio or Paleo Workbench multi-module shell. Reference is **user-visible workflow density**, not pixels or private formats.

### 5.1 Central (should appear on a phase-1 parity checklist)

| Area | Minimum user-visible parity |
|------|-----------------------------|
| **Workspace / catalog** | Open local workspace; well list; field/block optional; add wells; attach log documents. |
| **Data load** | LAS (+ engine-supported formats already in WellLogEngine IO); well head; tops/intervals import; clear diagnostics. ResForm-compatible curve/unit/null **semantics** per CONTEXT.md / ADR 0049 — not ResForm private files. |
| **Single-well multi-track plot** | Apply multi-track template; pan/zoom depth; track width/order; curve style/scale; null gaps. |
| **Template library** | Ship usable track templates for common Chinese log recipes (GR-SP-CAL / resistivity / porosity suite, etc.); full template *author* may be thinner than ResForm. |
| **Tops** | View/pick/edit formation tops on single-well; persist in workspace. |
| **Export** | Image and vector (PDF/SVG per engine) + simple table export of curves/tops. |
| **Shell IA** | Log-first: workspace → wells → figure documents; **not** “测井 as side page of map compilation”. |

### 5.2 Strongly recommended in early phase (or phase-1.5) if Engine multi-well is ready

| Area | Notes |
|------|--------|
| **Multi-well correlation** | Shared display depth; link/tops bands; enter single-well from correlation. Engine already has multi-well session surface (ADR 0012) and correlation-related domain concepts — product shell still needs IA. |
| **Basic well-tie section** | Ordered wells + shared tops links without full reservoir “beauty” editing. |

Map #207 explicitly leaves open “single-well only vs correlation in v1”; this research **recommends treating correlation as near-central** because public ResForm product language treats 地层对比 as co-equal with 单井图, but **MVP can ship single-well + tops first** if delivery risk is high.

### 5.3 Peripheral for phase-1 log workstation (defer)

| Area | Why defer |
|------|-----------|
| Planar maps / kriging contours | Map/cartography product; not log-engine core. |
| Fence / 栅状图 | Downstream of correlation + 3D layout; later. |
| Full 油藏剖面 “presentation studio” (fault kinematics, fluid fill art, jagged lithology connectors) | High interaction cost; not required to prove log workstation. |
| Composite multi-document report canvas | Nice-to-have after primary figures work. |
| Network workspace / Oracle-SQL multi-site data services | Enterprise; local workspace first. |
| Macro/script language | Power-user; after core plots. |
| GeoOffice R.E. production/dynamic analysis charts | Different persona (reservoir engineering). |
| SinoLog-class log processing / multi-mineral inversion | Separate product line. |
| Legacy 卡奔 DB binary import | Compatibility project, not phase-1. |

---

## 6. Suggested phase-1 cut line (checklist-ready)

**Phase-1 “ResFormSTAR-class log workstation” = log-first shell that covers the ResForm *spine* without the full geology office.**

### In (phase-1)

1. **Local workspace** with well catalog and document list (at least: single-well figures; optionally correlation figures).
2. **Load** LAS/engine formats + well headers + tops; ResForm-compatible normalization semantics.
3. **Single-well plot document:** multi-track template apply, depth navigation, scale/style, interpretation-friendly header behavior as UX goal.
4. **Tops pick/edit** on single-well; save with workspace.
5. **Export** publication figure + table snapshot.
6. **Template pack** (library-first; full visual template editor can be phase-2).

### Boundary decision for #210

- **Option A (minimal):** phase-1 = items 1–6 only; multi-well correlation is phase-2.
- **Option B (recommended if Engine multi-well is stable):** phase-1 also includes **地层对比-lite**: N wells, shared depth datum, manual tops links, jump-to single-well; **exclude** fence, planar, full reservoir section polish.

### Explicitly out of phase-1

平面图、栅状图、综合图 collage、网络工区、宏脚本、油藏工程动态分析、私有工区格式读写、像素级 UI clone.

---

## 7. Mapping to WellLogEngine / CONTEXT (non-implementation notes)

| ResForm public workflow | Existing Paleo / Engine footing |
|-------------------------|----------------------------------|
| 单井多图道显示 | WellLogSession + tracks / presentation; CurveTrack etc. |
| 整文件曲线导入语义 | CONTEXT ResForm Compatibility Model; ADR 0049 LIS profile (formats via IO adapters). |
| 多井共享深度 / 对比 | ADR 0012 multi-well scene; FormationTopCorrelator / StratigraphicCorrelationEngine domain concepts. |
| 导出 PDF/SVG | Engine export backends consuming prepared scene. |
| 工区 / 井目录 / 图件文档 | **Not** engine core — host/workstation shell (this map). |
| 平面图 / 栅状图 | Outside WellLogEngine phase-1 product cut. |

---

## 8. Sources (public)

| URL | What it contributes |
|-----|---------------------|
| https://www.petrohd.com/ | Vendor homepage: GeoOffice positioning, document types, workspace local/network. |
| https://www.petrohd.com/resformgeooffice | Product page for GeoOffice. |
| https://www.petrohd.com/resformgeoofficeRE | GeoOffice R.E. (adds dynamic analysis). |
| https://www.petrohd.com/geoworkings | Enterprise multi-client + template/remote data path. |
| http://www.oilsofts.com/?p=2154 | Detailed public module blurb (工区, data services, load formats, 单井 20 图道, 绘图/解释模式, 对比 vs 油藏剖面, 平面, 栅状, 综合). |
| http://www.oilsofts.com/?p=4011 | “ResFormSTAR最新版2023” catalog text restating GeoOffice document suite. |
| https://jingyan.baidu.com/article/335530da48d34b58ca41c330.html | Data source/service tutorial; five base figure types; Access/SQL/Oracle; well catalog fields; 卡奔 import; copy-from-plot bootstrap. |
| https://bbs.agoil.cn/read-htm-tid-194283.html | Quick-start guide discussion (workspace document tree). |
| http://bbs.sunpetro.club/thread-58331-1-1.html | User discussion: 分层对比 strength; section fluid fills; trajectories; 卡奔 migration friction (workflow signals only). |
| In-repo `CONTEXT.md` | ResForm Compatibility Model (import semantics only — not UI scope). |

**Caveats:** Vendor site pages are partly JS-rendered; richest free text is the oilsofts product blurbs + Baidu data-management tutorial + forum titles/bodies. This inventory intentionally does **not** use installers, manuals behind paywalls, or binary inspection.

---

## 9. One-page parity checklist draft (for #210)

- [ ] Local 工区 open/create/close  
- [ ] Well catalog (name, XY optional, KB, TD)  
- [ ] Load LAS (+ listed engine formats) with diagnostics  
- [ ] Load/edit 分层 tops  
- [ ] Create 单井分析图 from template (≥ common track types)  
- [ ] Depth pan/zoom; track order/width; curve scale/style  
- [ ] 绘图 vs 解释-like header behavior (UX goal)  
- [ ] Export figure (raster + vector) and curve/tops table  
- [ ] *(Optional phase-1)* 地层对比-lite: multi-well layout, links, single-well jump  
- [ ] *Later* 油藏剖面 polish, 平面图, 栅状图, 综合图, network 工区, macros  

---

*End of research note. No product UI implemented under this ticket.*
