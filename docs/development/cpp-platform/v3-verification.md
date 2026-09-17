# CPP-A v3 验证记录（平台线）

> 分支 `codex/cpp-v2-platform`；全部为门禁内真实命令与退出码。日期：2026-09-17。

## 1. 工具链与 SDK manifest（实测）

- GCC 16.2.1（`c++ --version`），CMake 4.4.3，Ninja 1.13.2。
- Qt 6.11.2 系统包：`find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Widgets Xml Svg PrintSupport)` 解析成功；`Qt6_DIR=/usr/lib/cmake/Qt6`；`PWB_QT_PREFIX=/usr` 前缀校验（`cmake_path(IS_PREFIX …)`）通过。
- QGIS 4.2.0 vendored：源码快照 `third_party/qgis`（UPSTREAM.md @ ca5812c8）；SDK `qgis-vendor/output/lib/libqgis_{core,gui,analysis,native}.so`（CMake 存在性检查进 configure，缺失即 FATAL_ERROR）；生成头 `qgis-vendor/{qgsconfig.h,src/*/qgis_*.h}`。
- 门禁：`scripts/cpp-migration/invoke-resource-gate.sh`（`Invoke-ResourceGate.ps1` 的 POSIX 等价；同锁文件 `cpp-migration-heavy.lock`、≥8 GiB、2 jobs、exit 75）。Probe 实测 `RESOURCE_READY free=53.26 GiB`；本轮真实 75 ×3（B 线持锁），无绕过。

## 2. 构建与测试命令（可复现）

```bash
# 平台模块（独立）
cmake -S . -B build/cpp-platform  -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPWB_BUILD_PLATFORM=ON -DPWB_BUILD_DATA=OFF -DPWB_BUILD_SCIENCE=OFF
# integrated（B/C/WLE 真实闭包）
cmake -S . -B build/cpp-integrated -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPWB_BUILD_PLATFORM=ON -DPWB_BUILD_DATA=ON -DPWB_BUILD_SCIENCE=ON \
  -DPWB_BUILD_INTEGRATION_TESTS=ON -DPWB_SCIENCE_BUILD_TESTS=ON \
  -DPWB_SCIENCE_BUILD_VIEWER=ON \
  -DPWB_WELL_LOG_ENGINE_ROOT=<C install tree>
# 测试
ctest --test-dir build/cpp-platform   -R '^platform\.'      # 9/9
ctest --test-dir build/cpp-integrated                        # 32/34（§4）
```

## 3. platform.*（模块级）— 9/9 通过

| 测试 | 断言要点 | 结果 |
|---|---|---|
| toolpolicy_matrix | 阶段 fail-closed/未知阶段白名单/checked 派生/QAction parity（含 Qt tooltip 回退语义） | Passed |
| toolpolicy_golden | 28 上下文 × 77 工具 vs Python golden（28×77 全等：enabled/visible/checked/reason） | Passed |
| qgis_smoke | 真 GPKG+GeoTIFF provider、EPSG 校验、QgsMapRendererParallelJob 真渲染非空白、树序读回、坏 URI 诚实诊断 | Passed |
| edit_cycle | 顶点移动→undo/redo→commit→staged GeoJSON 重读（几何+属性）；bowtie 阻止提交会话保留；修复后提交 | Passed |
| lifecycle_cycles | 20× 开/关+编辑+提交循环 0 crash（顶点交替方向防漂移越界） | Passed |
| export_layout | PNG/PDF/SVG 内容级（非空/魔数）断言 | Passed |
| adapters_substitutes | staged 协议、module-only 诚实错误、快照派生 | Passed |
| ui_wiring | 动作真实入栏入菜单（同对象）、已连接、触发实效（map tool 真换、编辑会话真开）、dirty-close 三态（cancel 保留/save 报告并取消/discard 终结） | Passed |
| qgis_smoke_app | `pwb-platform --self-check` 退出码 0（integrated 配置含 WLE dock 真 LAS 加载） | Passed |

## 4. integrated — 32/34 通过（详细见 v3-integration-verification.md）

`data.*` 17/19、`science.*` 4/4、`platform.*` 9/9、`integration.*` 2/2。唯二失败为 B 线 oracle fixture 内嵌绝对路径（checkout 相关，已移交 B；本线不重写他线 fixture）。

## 4a. main 增量（评审 P1 修复后，`e732678d` 之后）— integrated 44/44 通过 ×2

合并后按外部评审（status-after-pull-e732678d.md）修复三项 P1，并把 D/E 纳入同一 integrated 树：

| 项 | 内容 | 验证 |
|---|---|---|
| P1 发布假成功 | `CatalogResultPublisher` 全部失败路径（outputs≠1/shape 空/register_run/payload 写/publish_run_result/状态异常）改为记录 outcome + 已注册 run 尽力 `finish_run(Failed)`（再失败即显式 recovery-pending）+ 抛 `CatalogPublishError`；C 的 TaskRuntime 契约将抛异常的 publish_success 判为 `publisher.publish_threw` 失败 | `integration.algorithm_chain` 新增两段失败注入：staged_dir 指向普通文件（payload 写失败）→ 任务 failed + run 终态 failed + 无成功版本；双输出内核 → 任务 failed 且 run 行完全不存在 |
| P1 保存顺序 | `EditController` 拆 `stage()`（活编辑缓冲导出 staged GeoJSON，不写源 provider）/`finalize()`（commitChanges+交付完整 delta+推进 base revision）；`ProjectSession::stage_commit` 重排为 stage → B commit → finalize；B 拒绝时缓冲保留、源文件未动（可修复重试）；B 接受后 finalize 失败则明确“catalog 版本已权威，重载工作副本” | `platform.adapters_substitutes` 新增：B 拒绝后第二个图层读同一 GPKG 文件证实源未写 + 缓冲存活；接受后源已写 |
| P1 operation ID 复用 | ID = `pwb-edit-<layer>-r<base_revision>-<sha256[0:8]>`（layer id 净化为安全段）；同内容重试复用同 ID（B 幂等），内容变化即新 ID；`base_revisions_` 在每次成功 finalize 推进；base_version 冻结为 B 绑定版本 | 同测试新增：连续两轮提交 ID 必不同；同内容重试 ID 必相同 |
| fixture 绝对路径 | `data.oracle_compare` 改为语义比较（resolved == canonical(fixture dir)/stored + oracle 自洽尾缀校验），不再比对生成机器的绝对路径 | `data.*` 19/19（原 17/19 的两个 oracle 失败清零） |
| D/E 入 integrated 门禁 | `PWB_BUILD_SEISMIC_VIEWER/ATTRIBUTES=ON` 与 A/B/C 同树构建 | `seismic_viewer.*` 5/5、`seismic_attributes.*` 4/4 同树通过 |
| 五线真实链 | 新增 `integration.attribute_chain`：真 E 内核（rms_amplitude window=21 / envelope，tiny_sgy_real 冻结 oracle）经 C TaskRuntime → A CatalogResultPublisher → B catalog → 重开读回 PWBVOL1 与 oracle 对账（<1e-5）；E 的显式注册由 host 调用（4/4 入 registry）。E 原套件仅用基线 runtime+收集型 publisher，此测试补上生产链证据 | Passed（含 run 行 complete 仅经 publish 达成、provenance/version/payload 存在性断言） |

实测命令（main 工作区，GCC 16.2.1 / Qt 6.11.2 系统 ABI / vendored QGIS 4.2.0）：

```bash
cmake -S . -B build/cpp-integrated -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPWB_BUILD_PLATFORM=ON -DPWB_BUILD_DATA=ON -DPWB_BUILD_SCIENCE=ON \
  -DPWB_BUILD_INTEGRATION_TESTS=ON -DPWB_BUILD_TOOLS=ON \
  -DPWB_BUILD_SEISMIC_VIEWER=ON -DPWB_BUILD_SEISMIC_ATTRIBUTES=ON \
  -DPALEO_QGIS_SOURCE_DIR=$PWD/third_party/qgis \
  -DPALEO_QGIS_SDK_DIR=$PWD/native/qgis_render_bridge/build/qgis-vendor/output \
  -DPALEO_QGIS_BUILD_DIR=$PWD/native/qgis_render_bridge/build/qgis-vendor
cmake --build build/cpp-integrated -j 8        # exit 0
ctest --test-dir build/cpp-integrated -j 4     # 44/44 Passed，两轮
MALLOC_CHECK_=3 ctest --test-dir build/cpp-integrated -R "platform.|integration."  # 12/12
```

仍属未完成（如实）：正常 .paleo 工程 UI 会话（set_store 生产调用）、D viewer/E 算法在主程序内的装配、Windows 回归——评审建议的后续顺序第 2/3 步。

## 5. 关键修复的技术根因（供审计）

1. `QgsApplication::instance()` 为 `qobject_cast`——进程必须以 QgsApplication 为应用对象（全部 8 个入口替换，3 参构造）。
2. `QgsVectorLayer::getFeature` 返回值式（QGIS 4.x）；`Qgis::VectorProviderCapability` flags `testFlag`。
3. offscreen 下未显示窗口 `canvas->grab()` 尺寸不确定 → 并行渲染 job + 显式图层 extent。
4. 集成双 sqlite3 符号抢占 → vendored amalgamation `-fvisibility=hidden`（glibc 堆校验 `MALLOC_CHECK_=3` 下复现与验证）。
5. MainWindow 成员逆序析构 UAF（`actions_` vs `session_`）→ 析构内先有序 close。
6. lifecycle 测试顶点单调漂移 17 轮后越界产生 Self-intersection（测试缺陷；同时确证 commit 持久化进工作副本的语义）。

## 6. 未执行（如实）

- 可见 UI 交互记录/截图：headless 环境无显示服务器，**未执行**（以 ui_wiring 动作触发断言替代）。
- 500-cycle soak / sanitizers / 性能基准：未执行。
- Windows 构建：无环境，未执行。
- D/E 主程序装配（viewer 实例、算法注册 UI）：未执行（§4a 仅覆盖同树构建+模块测试；评审后续第 3 步）。
