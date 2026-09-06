# Verification — QGIS 地质编图生产线 v5

本文件随开发推进持续追加。测试命令统一：`/home/kevin/projects/paleo_project/run_env.sh /home/kevin/projects/paleo-wt-qgis-geology-production-v5 <pytest args>`（offscreen + 软件 GL + -p no:randomly）。

## 环境事实

- vendored QGIS build（复用，未重编）：`/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor`（4.2.0）
- 桥扩展构建：待记录（D8 流程）

## 分层验证记录

命令：`/home/kevin/projects/paleo_project/run_env.sh <worktree> tests/...`（offscreen、软件 GL、-p no:randomly、无 xdist）。

| 层 | 套件 | 结果 |
|---|---|---|
| 1-2 科学+管线（review 修复前） | 27 个文件 | 599 passed |
| 3-6 桥+导出+合成（review 修复前） | 14 个文件 | 79 passed |
| review 修复回归 | evaluation/crs/fusion/lifecycle/factor_map + QC/panel/page 消费方 | 112 passed |
| **终验：科学+管线+QA+面板** | 34 个文件 | **668 passed, 0 failed** |
| **终验：桥+导出+合成+e2e** | 15 个文件 | **81 passed, 0 failed** |

终验合计 **749 passed / 0 failed**（commit 70cb3dab）。

桥扩展构建：`PALEO_WITH_QGIS_RENDERER=1 PALEO_QGIS_REUSE_VENDOR=1 PALEO_QGIS_BUILD_DIR=<main>/build/qgis-vendor PALEO_QGIS_CMAKE_PREFIX=/usr/lib/cmake/Qt6 pip install --user -e native/qgis_render_bridge`（零 QGIS 重编；增量修复期间共 4 次重编桥本体，单次 ~3 分钟）。
附带修复两个环境级前置缺陷：setup.py `resource_database` NameError（89601913）；`layer_model_core`/`grid_render_core` setup.py `python_requires<3.13` 与全链 3.13 矛盾（放宽 <3.14，二进制此前在 3.13 环境从未可装）。

## 三轮 Review 与修复

三轮独立 review（correctness / architecture / adversarial-performance）于 20cdfe14 后执行，全部发现当场修复并补回归测试：

- [R1-P1] CV 折叠索引错位（非有限样本使留出集整体平移）→ 过滤后折叠 + 回归测试
- [R3-P1] 孪生井虚高 CV 精度（实测 RMSE 0.46→0.33 虚降）→ 折叠前坐标合并 + detail 计数
- [R1/R3-P2] crs_policy 对不可解析 CRS 误标 "verified" → unverified 注记 + 警告
- [R1-P2] 规则 `==` 算子对数组崩溃 → np.isclose
- [R1-P2] 含人工修正产品永久 stale → record 记录 adjustments，staleness 全量重建
- [R1-P2] frozen 可被 supersede / 双重 supersede 覆盖 → 状态机防护
- [R1-P2] compare 未标记因子视图来源 → factor_source: run_snapshot|live_fallback
- [R3-P2] 布局导出无像素预算（A0@1200dpi 实测 8.7GB）→ MAX_EXPORT_PIXELS=2e8
- [R3-P2] FactorMapSpec bounds/mask 残缺静默接受 → 显式校验
- [P3 批] 融合单因子 sensitivity、FusionRule.from_dict 校验、大小写折叠查找、
  attach CV 陈旧指标、apply_filter 清选发信号、QA export_fallback 词表统一
  （兼容 composer_fallback/degraded）、fold n_skipped 键冲突、engine 置位时机、
  北针 SVG 走 tempfile、早退分支 qc 元数据、adapter 折叠方案委托权威、
  run_map_qc 生产接线（review_export_page）、面板导出接报告版

## 资源约束遵守

- vendored QGIS 零重编（REUSE_VENDOR + main worktree vendor，UPSTREAM commit 校验）
- 全部 C++ 编译串行/≤-j2；pytest 无 xdist；qgis-marked 套件小批运行
- 未运行 100GB seismic benchmark；性能证据来自 review 代理的受控探针（kriging LOO 亚二次、fusion 500×500×50 fuse 0.18s）

## 三轮 Review 与修复

（待填）

## 资源约束遵守

（待填）
