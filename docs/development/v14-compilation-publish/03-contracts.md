# 03 — Contracts（V14-COMPILATION-PUBLISH）

本线新增/接线的契约面。所有契约均为 additive；既有权威的语义零改动（见 01）。

## 1. Composer 模板库（`mapping_document/composer_templates.hpp`）

| 契约 | 语义 |
|---|---|
| `composer_template_library()` | Python `TEMPLATE_LIBRARY.values()` 的注册顺序（= 模板菜单顺序），9 个内建模板 |
| `find_composer_template(id)` | 未知 id → nullptr（调用方决定降级） |
| `template_base_map_frames(w,h)` | `_base_map_frames`：(margin, top, w-2·margin-88, h-top-bottom)，margin=min(12, w·0.05), top=24, bottom=34 |
| `instantiate_composer_template(factory, id, title?, paper?, orientation?, dpi?)` | Python `instantiate_template`：`title or label`/`paper or template.paper`/`dpi or 300.0` 的 falsy 回退；metadata 写 `template_id`/`template_category`；按 z_index 稳定排序物化；显式 title 覆写首个 TITLE 元素 text；未知 id → `std::invalid_argument`（Python KeyError 语义） |

模板数据 = Python 逐字段冻结（element_definitions 的 type/geometry/z/properties、style_bindings、data_bindings）。oracle 逐项比对（`mapping_document.composer_oracle`）。

## 2. Composer 渲染器（`composer_renderer.hpp`）

| 契约 | 语义 |
|---|---|
| `render_composition_to_svg(doc, seams)` | Python `MapComposerRenderer.render_to_svg`：mm viewBox、96DPI px 宽高、白页底、visible 元素按 z 稳定序、locked 角标 |
| 输出文本契约 | 所有用户文本 html.escape；几何 `%.2f`；值标签 `:g`；浮点 repr = Python 最短往返表示（[1e-4,1e16) 内定格 + ".0"，界外科学计数） |
| 未知元素类型 | 灰色虚线框（`composition.hpp` 的 TEXT 载体负责 round-trip） |
| `ComposerRenderSeams::frame_content(elem)` | 宿主提供活地图内容：`{bound, png_b64, svg_fragments, extent, has_extent}`。`bound=false` = 未绑定 → 内核走 dict-layer 矢量路径或诚实占位符。**永不伪造** |
| `ComposerRenderSeams::legend_entries(elem)` | 活图层图例条目（顺序 = 宿主 canonical layer order）；空 vector → 显式 items → 文档化两条缺省项 |
| `ComposerRenderSeams::palette_stops(name)` | 色带名→stops；缺席 → 文档化 2-stop 缺省（`#053061`→`#67001f`） |
| 确定性 | 梯度/pattern id 用 FNV-1a(id)%N（Python `hash()` 进程随机 → 文档化分歧，oracle 归一化后比对） |
| `reanchor_composition_svg(svg,w,h)` | `export.py _composition_svg`：width/height 改为 `"{repr(mm)}mm"`，viewBox 不变 |

## 3. 组图导出（`composer_export.hpp`）

| 契约 | 语义 |
|---|---|
| `export_composition_page(doc, path, format?, dpi?, render_seams, replay)` | `export_composition` 分派：format 空 → 扩展名（小写）→ "png"；svg/pdf/png 以外 → ok=false + Python 文案 `unsupported composition export format '<fmt>'` |
| SVG | 原子写（document_io `write_atomic`：temp→fsync→replace）+ 回读校验（非空且含 `</svg>`） |
| PNG/PDF | 经 `ComposerReplaySeams::replay`（Qt 端 `ui_seqviz_qt::make_composition_replay_seams`）；缺席 → ok=false `no composition replay device available`；失败 → 清理部分文件 |
| 失败清理 | 任何失败路径不留半成品文件 |
| DPI | `dpi` 缺省 = `doc.dpi`（0 也是有效值，Python `dpi if dpi is not None else doc.dpi` 语义） |

## 4. 面板 seam（`ui_seqviz/qt/composition_panel.hpp`）

既有 seam（08 线定义）本线全部注入生产实现：`template_library` / `instantiate_template` / `render_svg` / `export_fn` / `project_provider` / `record_export` / `main_map_bind_fn`。新增 `export_to(path, format, dpi)`（headless 导出，无文件对话框；批量导出/测试入口）。

## 5. 导出编排（install 适配层）

```text
check_pixel_budget（超限 = caller error，ok=false）
  → layout_export seam（平台绑定的 QGIS CompositionLayoutService；engine="qgis_layout"）
  → composer 引擎（原生 SVG + Qt replay；engine="composer_svg"）
```
报告 `engine` 标签如实反映产出路径；hybrid 元素在 QGIS 路径被 itemized 为 warnings，composer 路径真实渲染它们（修订 layout_export D-03，见 02 D-V14-03）。

## 6. 融合 grid seams（`closure_workflow/grid_seams.hpp`）

| 契约 | 语义 |
|---|---|
| `decode_grid_artifact(payload)` | `encode_grid_artifact` 的逆；artifact_kind≠"factor_grid"、数组 ragged、非法 cell、轴缺失、宽高 ≤0 → nullopt（拒绝，不猜测） |
| `load_grid_from_version(catalog, version_id)` | 目录版本 payload → 网格；nullptr catalog / 未知版本 / 非网格 payload → nullopt |
| `make_production_grid_seams(catalog, live_resolver?)` | `grid_from_version` = 目录装载；`grid_for_task` = ① 任务 `grid_artifact_version_id` → 目录装载 ② live resolver ③ nullopt（Python npz→live→inline 三级解析的 C++ 形态） |

`run_integrated_fusion` 的既有语义不变：seam nullopt = 拒绝，绝不静默替换输入。

## 7. QC provenance（`closure_review`）

| 契约 | 语义 |
|---|---|
| `run_map_qc_on_document(..., provenance?)` | 可选 registrar；返回非空 run id → `provenance_registered=true` + `provenance_run_id`；空/异常/缺席 → false（H14：永不声称不存在的 run） |
| `ProjectReviewActions::Delegates::provenance` | 宿主绑定；生产实现 = workflow provenance rail（FileCatalogRepository，`PWB_WITH_CLOSURE_WORKFLOW` 门控）；无 slice → seam 未绑定 → 诚实 false |

## 8. 与并行线的边界（重申）

- Prompt3 layer order：只读 `MapSession::layerIdsTopFirst()`（预览图例顺序的唯一来源）；不建第二棵层树。
- Prompt4 factor compute：只消费 frozen factor products（目录版本/live resolver）。
- Prompt1 catalog：经 seam/适配器，不直写库。
- #1436 map_compile：不重复实现；本线只在其四周接线（grid seams / 产品阶梯）。
