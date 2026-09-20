# 04 — Implementation Plan（V14-COMPILATION-PUBLISH）

执行顺序与完成状态。基线 `412d8baf`，三个提交。

## 已交付

### 提交 1 — composer 内核 + 面板接线（`8d4bcce0`）
| 项 | 内容 | 证据 |
|---|---|---|
| 模板库 | `composer_templates.{hpp,cpp}`：9 模板库 + instantiate | oracle 逐字段比对 |
| 渲染器 | `composer_renderer.{hpp,cpp}`：24 元素类型 + 8 图表 + dict-layer 矢量路径 + 诚实占位 | 57→63 oracle 用例 |
| 导出 | `composer_export.{hpp,cpp}`：SVG 原子写 + 分派 + Qt replay seam | oracle 2 用例 + 平台测试 |
| Qt replay | `ui_seqviz_qt/composition_replay.{hpp,cpp}`（PNG/PDF） | 平台测试导出 SVG；PNG/PDF 走同 seam |
| 面板接线 | 模板/预览/导出/provenance/main_map seam + 默认模板开档 | `platform.closure_mapping` composition battery |
| oracle 工具 | `tools/oracle/generate_composer_fixtures.py` + numpy/PySide6 stub | 两次运行 byte 一致 |
| 基线修复 | well_crosswell 挂载 guard；platform_closure_mapping 补 shell_project_actions.cpp | A/B（干净 main 同命令复现） |

### 提交 2 — 融合 seam + provenance（`bc9093d7`）
| 项 | 内容 | 证据 |
|---|---|---|
| grid seams | `closure_workflow/grid_seams.{hpp,cpp}`：decode + catalog pin + current 三级解析 | 22 检查 |
| provenance seam | `closure_review` registrar + `ProjectReviewActions` 委托 + app 生产绑定（workflow rail） | 5 检查 |
| 规模测试 | `composer_scale_test.cpp`：线性缩放/确定性/预算 | 30 检查 |
| 基线修复 | platform_closure_review_install 补 shell_project_actions.cpp | 同上 A/B |

### 提交 3 — review 修复（`0723d4f2`）
| 项 | 内容 |
|---|---|
| P0 | dict-layer well/annotation/label 渲染器移植 + registry 解析对齐 + 6 个新 oracle 用例 |
| P1 | 导出异常护栏（内核/面板/编排三层）；inset 不再贴主图；stale pin 拒绝；rail 按值返回；record_export 真实格式/时间/指针 any_cast；subtitle falsy 语义；标签 strip；labels 缺席=无标签；grid 循环上界 |
| 基线 | workflow_graph once-guard（CPP_CLOSE_02 可配置）；closure_workflow 测试链接 MappingKernel |

## 未交付（诚实登记，见 08-known-limitations.md）
- `compile_map_draft/production` 编图菜单（#1436 租约）：本线不复制实现；`map_compile` 合入后经 install 的 optional seam 接线。
- 深核 catalog 适配器（`workflow_runtime::CatalogRepository` over `CatalogClosureAdapter`）：#1436 已声明为独立子史诗；生产登记当前走 workflow rail。
- cartographic QA 15 规则移植（`mapping/cartographic_qa.py`）：超出本线预算，seam 已存在（`CartographicQaDelegate`），默认几何委托保持真实。
- Stage3 factor reference 卡片的内容模型（§13）：descriptor 服务未实现（Prompt2 布局/Prompt4 数据均为跨线依赖）。
- 编图→发布全链 UI（shelf 按钮 → assemble → review → freeze → publish）：库级阶梯已在 main 且有 oracle；UI 动作面未接线（`map_product_requested` 信号仍悬空——已登记为后续线）。
