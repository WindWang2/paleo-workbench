# 09 — Verification Report（V14-COMPILATION-PUBLISH）

日期：2026-09-21。Base：`412d8baf`。分支：`feat/v14-integrated-compilation-publish`（4 commits，44 files，+14504/−22）。

## 构建与测试环境

- 工具链：`/home/kevin/pwb-sdks/root/usr/bin`（cmake 4.4.3 + LD_LIBRARY_PATH），ninja 1.13.2，系统 Qt 6.11.2，vendor QGIS 4.2.0 只读复用主工作区。
- 资源纪律：全程 `scripts/cpp-migration/invoke-resource-gate.sh`（flock + 内存门槛）；build `-j2`；test `-j2`（CTEST_PARALLEL_LEVEL=2）；未重建 QGIS vendor；本 worktree build 目录隔离（`build/presets/linux-ninja`、`build/closure-tests`）。
- 配置：`linux-ninja` preset（PLATFORM/DATA/SCIENCE/MAPPING_KERNEL/CONV_01/CONV_16）+ `PWB_BUILD_CPP_CLOSE_02=ON` + `PWB_BUILD_CONV_17=ON`（closure_workflow 电池需要；CONV-17 提供 `pwb::mapping::area_unit_label/is_geographic_crs`）。

## A/B 基线归因（干净 main 复现）

三个 configure/link 失败在**干净 main@412d8baf worktree 同机同命令复现**，确认非本线引入：

| 失败 | 复现 | 本线修复 |
|---|---|---|
| `tests/cpp/well_crosswell` FATAL（VIZ_B 默认 ON、WLE 缺席时根 guard 与子目录 guard 不一致） | 是 | 根 guard 增加 `TARGET Pwb::UiWorkersWleLoad`（具名块） |
| `platform_closure_mapping` / `platform_closure_review_install` 链接缺 `shell_project_actions`（#1421 后 main_window.cpp 引用） | 是 | 两个测试目标源列表补 `shell_project_actions.cpp`（具名块） |
| `PWB_BUILD_CPP_CLOSE_02=ON` configure 碰撞（`libs/workflow_graph` 双 add） | 是 | CONV-25 块改 `pwb_add_subdirectory_once`（具名块） |

## 测试结果（本地，最终态）

```
ctest -R "closure_workflow|closure_review|mapping_document|platform.closure|ui_seqviz|cartography"
100% tests passed out of 25  (3.05s)
```

| 测试 | 结果 |
|---|---|
| `mapping_document.composer_oracle` | **1351/1351 checks**（63 渲染用例、20 模板文档、2 导出用例、模板库逐字段、实例化、拒绝路径、确定性 id） |
| `mapping_document.composer_scale` | **30/30**（线性缩放、图例线性、确定性、预算、格式拒绝） |
| `closure_workflow.grid_seams` | **22/22**（decode/catalog/生产融合路径/missing pin/no-catalog） |
| `closure_review.provenance_sink` | **5/5** |
| `closure_workflow.{fusion,map_product,e2e,resolve}` | 14 / 24 / 49 / … 全过（回归） |
| `mapping_document.{roundtrip,edit_session,bridge_session}` | 全过（回归） |
| `platform.closure_mapping` | 通过（含 composition battery：9 模板、模板开档、预览渲染、真实 SVG 导出） |
| `platform.closure_review_install` | 通过 |
| `ui_seqviz.{core_state,qt_widgets_smoke,composition_panel}` | 通过 |
| `cartography.*`（8） | 通过 |
| `tools/oracle/generate_composer_fixtures.py --check` | fixture 与冻结 Python 参考同步；两次生成 byte 一致 |

`closure_workflow` 电池同时经直接 g++ 编译（02 线同款方式）验证过：grid_seams 22/22、fusion 14/14、map_product 24/24、e2e 49/49。

## 性能证据

结构断言（非 wall-time 门禁）：100/1000 元素输出字节比 8–12×；100 图例 = 100 swatch（线性）；模板实例化 <50ms；渲染 byte 级确定；grid 20000 线上界。详见 06-performance-baseline.md。

## 两轮独立 review

架构/正确性 + 对抗/性能/生命周期各一轮（subagent，独立上下文）。发现 2×P0 + 15×P1 + 14×P2；P0/P1 全部修复并回归（见 07-review-findings.md），P2 剩余项登记于 08。

## 未验证（诚实声明）

- 真机 QGIS 执行器路径的端到端导出（需活 MapSession 注入 install seam）；QGIS 链本身由既有 `platform.composition_export` 覆盖。
- Windows/macOS；ASan/UBSan。
- 全平台逐像素 parity（仅语义 parity：bounds/layers/legend/chrome/text/scale/z-order 经共享 spec 与结构断言守护）。

> Local verification completed; online CI was not required or awaited for this development goal.
