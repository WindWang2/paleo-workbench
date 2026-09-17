# C 线接口契约 v3（codex/cpp-v2-science）

> 基线：`53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`（data 14/14 + science 4/4 已验证）。
> 本文先于实现提交（接口先行）：冻结 D/E 消费的公共语义，公布 publisher/关闭语义的
> v3 必要扩展与迁移表。头文件仍是权威，本文是语义说明书 + 变更清单。

## 0. 冻结项（D/E 可立即消费，语义与基线一致）

以下公共头文件 blob SHA 为基线冻结版；本线承诺 **不改变其语义**（轴顺序、strides、
lifetime、数值契约、算法协议均不动）。任何必要修复先与消费方沟通，最小化变更。

| 头文件（`libs/…/include/` 下） | 基线 blob SHA |
|---|---|
| `pwb/science/algorithm.hpp`（IAlgorithm） | `30dba923a0a7dd28c832a11d0fd6db1d2fd330cb` |
| `pwb/science/types.hpp`（AlgorithmRequestV1/VolumeView 等） | `96a28dd39c0b4200222d66295ebda19ac7bff68c` |
| `pwb/science/outcome.hpp`（Result/Error/Cancelled） | `33e923bfa88e20e7f4163114b09be35f633377ec` |
| `pwb/science/publisher.hpp`（IResultPublisherV1） | `3fc63915259ba074426cb2ea9fbb862bf7332fa4` |
| `pwb/science/registry.hpp` | `2cfc21478e8ea08ab023b9dccb0fd0ce992fa8e3` |
| `pwb/viz/seismic_volume.hpp`（ISeismicVolume/VolumeGeometryV1） | `a4f0bfd70cc35daa388c1ee9bf7aa6b66ee79b04` |
| `pwb/viz/selection.hpp`（SelectionEventV1） | `ada4e583bbe4cfdea9dc44930c80965957896aa0` |

要点（与 02-contracts.md v1 一致，此处重申以免歧义）：

- `VolumeView`/`VolumeGeometryV1` 轴顺序固定 `(inline, crossline, sample)`；`strides`
  为元素步长，`{0,0,0}` 表示 packed C-order；permuted 布局允许，backend 不得为切片
  复制整卷。D 的二维 viewer 与 E 的属性库按此消费即可，不依赖本线 viewer 进度。
- `IAlgorithm::run` 不得让异常逃逸；终止态 value/Error/Cancelled 三分。
- `IResultPublisherV1`：每个 request 至多一次 `publish_*`；取消/失败必须以
  failure 形式发布（可见性），绝不发布 success。
- `SelectionEventV1`：`document_id` 是稳定领域 ID，绝不由指针/地址派生；
  `origin` 用于回环抑制；深度域与地震时间域是不同 `DepthDomainKind`，井深换算
  到地震时间需要宿主显式提供速度模型，本契约不暗示两者可直接互换。

## 1. TaskRuntime v3：发布/终态顺序（修复“先标成功再发布”）

**新不变量**（替换基线实现中“终态先于发布”的行为）：

1. 有 publisher 时，**先真实发布、后置终态**。`snapshot()` 里看到 `succeeded`
   当且仅当 `publish_success` 已完整返回。发布抛异常 → 终态 `failed`，稳定错误码
   `publisher.publish_threw`，诊断含异常消息；**不重试、不重复发布**。
2. 算法失败/取消路径同样先 `publish_failure` 后置终态；failure 发布抛异常时，
   算法结果状态（failed/cancelled）不变，追加稳定诊断码
   `publisher.publish_failure_threw`，同样不重试。
3. `wait()` 只在发布完成或发布失败已确定（诊断落盘进 snapshot）后返回。
4. worker 永不因 publisher/算法异常退出；后续任务继续执行。
5. 发布期间不持有任务状态锁：publisher 回调内可安全调用 `snapshot()`（重入）。
   快照此时可见新状态 `publishing`（见迁移表）。
6. **同 worker 对自身 wait 明确禁止并检测**：publisher（运行在 worker 线程上）
   对当前任务调用 `wait()`/`wait_idle()` 会抛 `std::logic_error`
   （`task.self_wait_detected` 语义），不得通过提前标成功规避死锁。

### 线性化边界（取消 × 持久化，全部确定语义）

| 边界 | 语义 |
|---|---|
| L0 排队中取消 | worker 取出 submission 后、置 `running` 前检查 stop：已请求 → 算法**从不运行**，发布 failure(cancelled)，终态 `cancelled`。 |
| L1 计算中取消 | stop_token 传递给算法；算法返回 `TaskCancelled` → 发布 failure(cancelled)，终态 `cancelled`。算法无视 stop 返回 value → 走成功路径（取消是 best-effort，结果确定性以 run() 返回值为准）。 |
| L2 结果已算完、尚未发布 | run() 返回即不可撤销：晚到的 cancel() 不改变结果归属，任务进入 `publishing` 并发布既有结果。快照可观测 `publishing`。 |
| L3 正在不可撤销发布 | publish_* 已进入后取消语义完全不适用；exactly-once：任何异常都不再触发第二次发布。**不会出现“数据库成功而任务报告取消”或“取消任务留下成功结果”**。 |
| L4 窗口关闭/运行时析构 | 析构 = drain（已接受任务全部跑到终态、发布完成）+ join，无 detached 回调；drain 前提是长任务被取消或自然结束（宿主责任，测试覆盖）。新增显式 `shutdown()`：幂等，置位后 submit 拒收（终态 `failed`/`runtime.shutdown`，**不发布**——从未接受），已排队任务仍跑完。 |

### 纯计算模式 vs 生产持久化模式

`submit(..., publisher=nullptr)` 为纯计算模式：无发布阶段（不经过 `publishing`），
终态 `succeeded` 只表示计算成功。生产模式（publisher 非空）终态 `succeeded` 表示
**计算 + 发布双双成功**。区分在快照上可见：新增 `TaskSnapshot::published`
（仅 publisher 存在且发布调用完整返回时为 true）。

## 2. v3 API 增量与迁移表（A/D/E 适配）

| 变更 | 旧（基线） | 新（v3） | 消费方动作 |
|---|---|---|---|
| `TaskStatus::publishing` | 无 | `running` 与终态之间的可观测阶段（有 publisher 时） | 视为非终态；进度 UI 可显示“发布中” |
| `TaskSnapshot::published` | 无 | bool，见上 | 可选；区分计算成功与入库成功 |
| `wait()` 返回时机 | 终态先于发布（bug） | 发布完成/失败确定后 | 无需改动，语义变强 |
| `wait()`/`wait_idle()` 自等待 | 死锁 | 抛 `std::logic_error` | publisher 内不要同步等待自身任务 |
| publisher 抛异常 | 任务仍显 succeeded（bug） | 终态 failed（`publisher.publish_threw`）或保持算法态 + 诊断（failure 发布） | publisher 端仍应自行捕获可预期错误 |
| `TaskRuntime::shutdown()` | 仅析构 | 显式关闭 API：幂等、drain、join、拒收 | A 关闭窗口时先 `shutdown()` 再拆 widget |
| 冻结的七头 | — | blob SHA 见 §0 | D/E 基线兼容，无动作 |

## 3. CMake 消费契约（viewer 构建与测试分离）

基线缺陷：`libs/science_suite` 先 add tests 再建 WLE adapter，`TARGET` 判断恒假，
`science.viewer.well_log` 从未注册。v3 修复后：

- `PWB_SCIENCE_BUILD_TESTS`（默认 ON）：Qt-free 4 组测试，语义不变。
- `PWB_SCIENCE_BUILD_VIEWER`（默认 OFF，**新增**）：构建固定 gitlink 的 WLE SDK
  （本线是唯一构建者）+ 生产 adapter `Pwb::VisualizationWellLog`。
  `-DPWB_SCIENCE_BUILD_TESTS=OFF` 时仍可构建（独立消费程序路径）。
  WLE 来源二选一：源码子模块（默认 `well-log-engine/`，pinned `f845e7ab`）或
  预构建只读 install tree（`-DPWB_WELL_LOG_ENGINE_ROOT=<install-prefix>`，
  消费其导出 target，不重复构建）。
- `PWB_SCIENCE_VIEWER_TESTS`（默认 OFF）：要求 BUILD_VIEWER+BUILD_TESTS，在
  adapter target 存在**之后**注册 `science.viewer.well_log`；开启但缺
  target/Qt≥6.8/WLE/LAS fixture → configure `FATAL_ERROR`（fail-closed，不静默跳过）。
- 公共头迁移：`well_log_host_widget.hpp` 从 `libs/visualization/src/well_log/`
  移至公共 include——`#include <pwb/viz/well_log_host_widget.hpp>`。旧源码私有
  路径 include 不再需要（测试与消费程序一律走公共头）。

`Pwb::VisualizationWellLog` 链接：`Pwb::Visualization` + `WellLog::QtWidgets` +
`Qt6::Widgets`；宿主只需 link 该 target，不得引用 WLE 源码私有路径。

## 4. WellLogHostWidget 契约（v3 修复范围）

- `load_las(const QString&, QString*)`：真实 LAS 引擎解析；重复加载在同一 widget
  上完整替换文档/呈现（旧 track/curve 不残留）；空数据（无采样轴/无曲线/全空值）
  返回 false 且 `*error` 非空；Unicode 路径可用。基线的 `const class QString&`
  前置声明改为显式 `#include <QString>`。
- 选择：`select_depth_range/clear_selection/reset_viewport` 语义不变；
  `SelectionEventV1` 的 `document_id/origin/revision/unit/domain` 来自引擎文档
  真值，指针永不入库。
- 关闭：view（GL 上下文）先于 session 析构；迟到的 selectionChanged 信号经
  alive-guard 变 no-op；20 次加载/关闭循环无挂起、无悬空回调（测试覆盖）。

## 5. WLE SDK 交付物（给 A）

固定 SHA `f845e7ab`；本线构建的只读 install tree 携带 manifest
（WLE SHA / Qt / 编译器 / CRT 等价物 / build config），并给出 imported-target
消费方案；A 不得隐式重建第二份 WLE。本机（Linux 验证环境）与 A 的 Windows
manifest 差异在 `v3-verification.md` 如实列出。

## 6. 边界重申

- D/E 消费 §0 冻结头 + `Pwb::Visualization`/`Pwb::Science`，不需要等本线 viewer。
- 跨域转换（volume→QGIS 图层等）在 A 的 `libs/application`；本线不做。
- publisher 的模块测试替身不代表 B 真入库通过；端到端由 A 验证。
- 本线不改：数据库、地震二维 viewer（D）、属性库（E）。
