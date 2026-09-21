# V14-CONSTRAINT-FACTOR — 09 验证报告

- 分支：`feat/v14-constraint-single-factor-native`
- Base：`412d8baf22a6a928c860e2e3d6c1108a9c035c78`（执行时 origin/main）
- 本机 linux-ninja Release；Qt 6.11.2 系统前缀；QGIS vendor SDK 只读复用主工作区；WLE 源码复用主工作区（gitlink 未签入本 worktree）。
- 资源纪律：全程 `CMAKE_BUILD_PARALLEL_LEVEL=2` / `CTEST_PARALLEL_LEVEL=2`（资源门给 2；从未超过 j4 上限；高峰期检测到其他并行线资源门活动时保持 -j2）。

## 配置

```text
cmake --preset linux-ninja \
  -DPWB_SCIENCE_BUILD_VIEWER=ON -DPWB_BUILD_CONV_22=ON \
  -DPWB_WELL_LOG_ENGINE_DIR=<主工作区>/well-log-engine \
  -DPWB_BUILD_CONV_05=ON -DPWB_BUILD_CONV_18=ON
```

（05/18 = constrained_idw 引擎 + factor_grid_io envelope codec——真核门控条件；无它们时安装保持诚实降级。）

## 新增测试

- `platform.factor_prepare`（Qt-free 内核/commit/staleness/持久化/井表/crosswell/对抗用例）：**ALL GREEN**。
  - IDW/kriging/constrained 正路径 + 确定性（byte-equal grid_z）；
  - 退化：少点/NaN/duplicate=error 隔离/样条+方向趋势诚实失败/plain+break、kriging+direction fail-closed/constrained <3 井、缺边界、共线 hull 拒绝；
  - 分类复用：CLEAN 重跑、values-only→DIRTY_VALUES、grid_n→DIRTY_GEOMETRY、direction→DIRTY_CONSTRAINTS；
  - commit：代际不匹配、stale-input 守卫、取消 #881、默认任务 bootstrap + #1159、未知 id、未知字段存活；
  - catalog：run/asset/version 登记 + domain_task_id + input_snapshot_hash + null-catalog 降级 + sidecar payload 契约；
  - 持久化：重开 runs/versions 完整、corrupt 拒绝打开、多窗口 drift 拒绝覆写；
  - 井表：value_key 别名、MAD QC、选择性 sync；
  - crosswell provider：live cache 腿与 catalog payload 腿数值一致、范围外 NaN。
- `platform.closure_mapping` Part 3（PWB_WITH_FACTOR_KERNEL E2E）：**PASS**。
  - 打开真实工程 → 批量生成（真 WorkerHost 线程 + 调度器 + 内核）→ 等值线初稿推送 drafts + map documents → 生产保存路由 → 全复用重跑（复用 2 · 计算 0）→ 改一个任务的值 → 选择性重算（复用 1 · 计算 1）→ 新窗口重开：任务版本、drafts、provenance rail 完整。

## 全量回归

- `ctest -E viz_e.pa_flow`：**175/175 通过**（54 s）。
- `viz_e.pa_flow` 排除：基线编译失败（`DataAssetTable` 前向声明不完整，A/B 于干净 412d8baf worktree 以基线 `worker_common.hpp` 复现；属 04/09 线区域，未跨线修改）。
- `ui_pages_data.preparation_page`：ctest 环境缺 libodbc（SDK 路径未注入）；补 `LD_LIBRARY_PATH=<sdk>/usr/lib` 后 PASS（环境问题，非回归）。
- 受影响回归族全绿：`platform.*`、`ui_workers.*`、`factor_host.*`（3397 checks）、`viz_b.*`、`well.*`、`data.catalog_closure`、`ui_pages_data.*`（with SDK path）。

## 基线链接修复（A/B 证实为基线问题）

- `platform_closure_mapping` 与 `platform_closure_review_install` 在 412d8baf 无法链接（main_window.cpp 引用 `shell_project_actions::*`，测试目标源列表缺该 TU；`PWB_WITH_DATA_INTEGRATION` 经 Pwb::Application PUBLIC 传播）。干净 origin/main worktree 同配置复现同样失败。本线最小 additive 修复：`if(TARGET Pwb::Data)` 补源。

## 性能

见 `06-performance-baseline.md`（100/1k 井、grid 50/200、4/20 任务、取消 <1 ms 探测、commit 6.7-136 ms、store O(T) 写放大）。

## 在线 CI

**未使用也未等待。** 本地验证即门（prompt 约定）。若远端出现 unrelated failure 不据此改本线代码。

## 声明差量

见 `08-known-limitations.md`（地理 CRS barrier buffer、样条/方向趋势核、NPZ 容器、set_run_ports、双 catalog 实现等 13 项，均登记并有后续依据）。
