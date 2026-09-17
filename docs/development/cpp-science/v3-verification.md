# C 线 v3 验证记录（codex/cpp-v2-science）

> 分支：`codex/cpp-v2-science`（基线 `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`）
> 交付提交：`03ff8155`（契约）→ `86d8b38c`（TaskRuntime v3）→ `a39b6281`（viewer 装配 + 消费程序）→ 本文档提交（见 ledger）
> 验证机：Linux x86_64（kernel 6.18.50-2-lts），16 核，验证期间可用内存 ≥ 33 GiB（峰值观察 53 GiB）
> 本文所有命令为实际执行命令；退出码为实测。

## 1. 环境与依赖 manifest（实测）

| 项 | 值 |
|---|---|
| WLE SDK 源 | submodule `well-log-engine` @ `f845e7abbbdc3133d28738975d72b2159a2d30f6`（= 主仓 gitlink，工作区 clean） |
| Qt | 6.11.2（系统 `/usr`，qmake6 实测），`Qt6::Widgets/OpenGLWidgets` |
| 编译器 | g++ (GCC) 16.2.1 20260800，target x86_64-pc-linux-gnu |
| CRT 等价物 | glibc 2.44 |
| CMake / Ninja | 3.24 最低要求；实测 cmake 4.4.3 + ninja 1.13.2 |
| GL | X 显示 `:1` 直连（glxinfo: direct rendering Yes, 16 GiB GPU），viewer 测试用真实 QOpenGLWidget 上下文 |
| Python oracle | 未使用（本轮无新数值算法；既有 coherence fixture 为基线冻结件） |

**与 A 线 manifest 的差异（如实声明）**：本环境为 Linux 验证机，无 MSVC/CRT，
Qt 为 6.11.2 而非 A 线候选 Qt 6.8.0；A 的 Windows ABI manifest 在本环境不存在。
所有 Qt 依赖代码仅要求 `find_package(Qt6 6.8 ...)`（与 A 线候选兼容的最低版本）。
**未验证配置**：Windows/MSVC/Qt 6.8.0 下的编译与链接（需 A 在其环境按 §6 配方复验）。

**资源门禁偏差（如实声明）**：`scripts/cpp-migration/Invoke-ResourceGate.ps1` 为
PowerShell 脚本，本机无 `pwsh`，无法执行。本轮重型构建/测试为本机唯一重型任务、
串行执行（`-j2`），全程可用内存 ≥ 33 GiB（> 12 GiB 全量构建门槛）；未自建第二把锁。

## 2. Qt-free 核心组（基线 4 组，必选）

```
$ cmake -S libs/science_suite -B build/cpp-science -G Ninja -DCMAKE_BUILD_TYPE=Release
  → exit 0（Configuring done / Generating done）
$ cmake --build build/cpp-science -j2        → exit 0（15/15 步）
$ ctest --test-dir build/cpp-science
  → 100% tests passed, 4/4：science.contracts / science.algorithms.coherence_c3_oracle
    / science.workflow.task_runtime / science.seismic.slice 全 Passed，0 失败 0 skip
（TaskRuntime v3 改动后同组复验一遍 → 4/4 Passed）
```

`science.workflow.task_runtime` 单独连跑 6 遍（exit 0 ×6，含 7 个新增 v3 用例共
15 用例）：慢发布 / 发布抛错 / 失败发布再抛错 / snapshot 重入 / 自等待防护 /
wait_idle 自等待 / 不可撤销发布期取消 / 显式 shutdown 排空 + 拒收。全部屏障
（std::latch）定序，无固定 sleep。

## 3. Viewer 构建/测试（修复装配后的验收）

### 3.1 WLE SDK 唯一构建者：只读 install tree + manifest

```
$ cmake -S well-log-engine -B build/wle-sdk -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PWD/build/wle-sdk-install" \
    -DWELLLOG_BUILD_PYTHON=OFF -DWELLLOG_TEXT=ON -DWELLLOG_BUILD_TESTS=OFF \
    -DWELLLOG_BUILD_BENCHMARKS=OFF -DWELLLOG_BUILD_QT_WIDGETS=ON
  → exit 0
$ cmake --build build/wle-sdk -j2            → exit 0（82/82，后 TEXT=ON 追加 8/8）
$ cmake --install build/wle-sdk              → exit 0
```

install tree 内容：`lib/libwelllog-{core,table,scene,export-*,session,io,render-gl,arrow,qtwidgets}.a`
+ `include/welllog/**` + `lib/cmake/WellLog/WellLogConfig.cmake|WellLogTargets.cmake|*-version.cmake`
+ `MANIFEST.md`（WLE SHA / Qt / 编译器 / glibc / config / options / 平台，生成于
2026-09-17T04:37Z，TEXT=ON 后同步）。**该树为本机验证产物；A 在 Windows 按同配方
重建即得权威 SDK**（见 v3-handoff §2）。

### 3.2 install-tree 消费 + viewer 测试注册与执行

```
$ cmake -S libs/science_suite -B build/cpp-science-viewer -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPWB_SCIENCE_BUILD_VIEWER=ON -DPWB_SCIENCE_VIEWER_TESTS=ON \
    -DPWB_WELL_LOG_ENGINE_ROOT="$PWD/build/wle-sdk-install"
  → exit 0
$ ctest --test-dir build/cpp-science-viewer -N
  → Total Tests: 5（含 Test #5: science.viewer.well_log —— 基线缺陷“先 add tests
    再建 WLE target 导致测试未注册”已修复，显式开启即注册）
$ cmake --build build/cpp-science-viewer -j2 → exit 0
$ ctest --test-dir build/cpp-science-viewer
  → 100% tests passed, 5/5；science.viewer.well_log Passed（0 失败 0 skip）
  → 再跑一遍：100% tests passed, 5/5（确定性复验）
```

viewer 测试覆盖：真实 `tests/fixtures/realdata/A1.Las` 引擎解析（DEPT.M
100.0–109.5 m、GR/DT 双曲线）、真实 GL ≥3.3 上下文、曲线像素非空、
SelectionEventV1（document_id=引擎 UUID、unit="m"、top/bottom=102/106、
revision=文档版本、origin、measured_depth 域）、viewport 重置/清除选择、
PNG 导出（见 §3.4）、Unicode 路径加载、缺失/损坏/空文件负例（失败且保留旧文档）、
原地重载、**20 次全新加载/显示/关闭循环**（真实 GL 上下文反复建拆，无挂起/无悬空回调）。

### 3.3 不构建测试的独立消费程序（两条配置路径均验证）

```
# 路径 A：install-tree 消费（同 3.2 build 目录）
$ build/cpp-science-viewer/well_log_adapter/pwb-well-log-consumer \
    tests/fixtures/realdata/A1.Las consumer_render.png
  → exit 0；输出: loaded A1.Las (document 979083e9-… rev 1), selection 102-106 m,
    rendered 840x1200 → consumer_render.png（PNG 实存）

# 路径 B：源码 gitlink 消费 + 测试全关
$ cmake -S libs/science_suite -B build/cpp-science-srcviewer -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DPWB_SCIENCE_BUILD_TESTS=OFF -DPWB_SCIENCE_BUILD_VIEWER=ON
  → exit 0；build 93/93 exit 0；ctest -N → Total Tests: 0（无测试，纯生产消费）
$ build/cpp-science-srcviewer/well_log_adapter/pwb-well-log-consumer …/A1.Las
  → exit 0（document 39091880-… rev 1, selection 102-106 m, 840x1200）
```

消费程序仅 `#include <pwb/viz/well_log_host_widget.hpp>` 公共头 + 链接
`Pwb::VisualizationWellLog`，不依赖任何源码私有路径或测试目录。

### 3.4 图像证据与可见视图检查

- `build/cpp-science-viewer/science_tests/well_log_viewer_test.png`（525×750 RGBA，
  sha256 前缀 e20c44bc827924cc）——像素级核验：蓝色曲线 (31,119,180) 与红色曲线
  (214,39,40) 恰为 adapter 调色板前两色（GR/DT 各一 track），两条折线覆盖全部
  750 行（密集非空曲线），背景白。**如实记录**：该呈现 spec 下引擎视图未绘制
  深度标尺/文字标注（灰阶文字像素为 0；track 边框为 WLE 呈现层样式，非本线
  adapter 契约）——曲线本体与选择交互完整，标注增强留给 WLE 呈现 spec 后续项。
- `consumer_render.png` / `well_log_consumer.png`（840×1200，消费程序导出）。

## 4. fail-closed 负例（实测均为 configure FATAL_ERROR）

| 配置 | 实测错误 |
|---|---|
| `-DPWB_SCIENCE_VIEWER_TESTS=ON -DPWB_SCIENCE_BUILD_VIEWER=OFF` | `PWB_SCIENCE_VIEWER_TESTS=ON requires PWB_SCIENCE_BUILD_VIEWER=ON` |
| `-DPWB_SCIENCE_BUILD_VIEWER=ON -DPWB_WELL_LOG_ENGINE_ROOT=/tmp/nonexistent-sdk` | `…is set but not a WLE install tree (missing lib/cmake/WellLog/WellLogConfig.cmake)` |
| `-DPWB_SCIENCE_BUILD_VIEWER=ON -DPWB_WELL_LOG_ENGINE_DIR=/tmp/no-wle-here` | `…well-log-engine not found at …（initialize the submodule … or point PWB_WELL_LOG_ENGINE_ROOT …）` |

## 5. 实现过程中实测发现并修复的真实缺陷清单

1. `TaskRuntime::execute` 先置 `succeeded` 再 publish、publisher 异常被 worker 吞
   （基线代码注释自认）→ v3 发布前置 + 稳定错误码（`publisher.publish_threw` /
   `publisher.publish_failure_threw`）+ 快照 `published` 标记。
2. science_suite 先 add tests 后建 WLE target → `science.viewer.well_log` 从未注册
   → 顺序倒转 + 选项拆分 + fail-closed。
3. `welllog::DepthDomain::time` 不存在（引擎枚举无 time 成员）→ 按
   source_index+单位映射；基线仅做过 MSVC /Zs 解析检查，未实测编译。
4. `WellLogView::grab()` 返回 QPixmap 而非 QImage → `grabFramebuffer()`。
5. 引擎 LAS 单位 token 原样透传（"M"）与契约小写词表（"m"）不一致 → adapter
   规范化为小写。
6. `LasSourceAdapter` 在 `WellLog::IO` 而基线 adapter 未链接 → 补 PRIVATE 链接。
7. 加载失败时 host state 先于 session 命令被改写 → 状态仅在两条命令均被接受后应用。

## 6. 限制与未执行项（如实）

- Windows/MSVC/Qt 6.8.0 构建、QGIS 侧、与 B 线真实 SQLite 入库的端到端：**未执行**
  （归 A 线汇总验证）。publisher 模块测试替身 ≠ B 真入库通过。
- `Invoke-ResourceGate.ps1` 未运行（无 pwsh）；以单任务串行 + 内存实测代替。
- WLE 引擎视图的深度标尺/文字标注未随当前呈现 spec 绘制（§3.4）。
- 平台 GL 差异：viewer 测试依赖真实 X/GL；无头 CI 需虚拟显示（本机 `:1` 直连）。
- 地震二维 viewer（D）与属性库（E）不在本线范围；本线未改数据库与根构建。
