# C 线 v3 交接（codex/cpp-v2-science → A / D / E）

> 交付基线：分支 `codex/cpp-v2-science` @ `a39b6281`（+ 本文档提交），基于
> `53e22b67`。接口语义见 `v3-contracts.md`，验证证据见 `v3-verification.md`。

## 1. A 线（平台/最终集成）消费指南

### 1.1 TaskRuntime 新语义（迁移表见 v3-contracts.md §2）

- `succeeded` 现在 = 计算 + 发布双成功：A 的 catalog publisher 适配器实现
  `IResultPublisherV1`，无需改动即可获得更强语义；UI 轮询 `snapshot()` 时新增
  可观测 `publishing` 阶段与 `published` 标记。
- publisher 内**不要**同步 `wait()`/`wait_idle()` 自身任务（会抛
  `std::logic_error`，这是防护而非支持）。
- 窗口关闭顺序建议：`runtime.shutdown()`（幂等，drain+join）→ 再拆 widget；
  shutdown 后 submit 立即失败 `runtime.shutdown` 且**不发布**。
- 端到端（算法 → B 的 SQLite catalog → viewer）仍由 A 验证；C 的 publisher
  测试替身不构成入库证明。

### 1.2 WLE SDK 消费（A 不得隐式重建第二份）

C 是 WLE 唯一构建者。两种消费方式（`libs/science_suite/CMakeLists.txt` 已实现）：

1. **预构建只读 install tree**：`-DPWB_WELL_LOG_ENGINE_ROOT=<install-prefix>` →
   `find_package(WellLog CONFIG REQUIRED)` 消费 `WellLog::QtWidgets` 等 imported
   targets（注意：该包**不声明 COMPONENTS**，直接判 TARGET）。
2. **源码 gitlink**：默认 `well-log-engine/` submodule（pinned `f845e7ab`），
   自动以产品选项（PYTHON/TEXT/TESTS/BENCHMARKS=OFF、QT_WIDGETS=ON）add_subdirectory。

Windows 权威 SDK 构建配方（A 在其 manifest 环境执行）：

```powershell
cmake -S well-log-engine -B build/wle-sdk -G Ninja `
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=<只读install前缀> `
  -DWELLLOG_BUILD_PYTHON=OFF -DWELLLOG_BUILD_TEXT=OFF `
  -DWELLLOG_BUILD_TESTS=OFF -DWELLLOG_BUILD_BENCHMARKS=OFF `
  -DWELLLOG_BUILD_QT_WIDGETS=ON
cmake --build build/wle-sdk -j2 ; cmake --install build/wle-sdk
# 附 manifest：WLE SHA/Qt/MSVC/CRT/config（Linux 参考件：
# build/wle-sdk-install/MANIFEST.md，Qt 6.11.2/GCC 16.2.1/glibc 2.44）
```

注：Windows 上 `WELLLOG_BUILD_TEXT=OFF`（无 harfbuzz/ICU pkg-config；视图无文字
标注也能工作，Linux 验证机 TEXT=ON 亦通过）。install tree 交付后 A 的根构建用
方式 1 消费，避免第二份 WLE。

### 1.3 WellLogHostWidget 接入

```cpp
#include <pwb/viz/well_log_host_widget.hpp>   // 公共头（已迁出源码私有路径）
auto* host = new pwb::viz::WellLogHostWidget(parent);
host->set_selection_callback([](const pwb::viz::SelectionEventV1& e){ /* 分发 */ });
QString err;
if (!host->load_las(path, &err)) { /* err 非空；旧文档保持可用 */ }
```

关闭安全：view(GL) 先于 session 析构、迟到 selectionChanged 经 alive-guard 无效化、
20 次加载/关闭实测无挂起。GUI 线程不得等待需要 GUI 的发布（v3 runtime 语义已把
发布放在 worker；发布里需要的 GUI 操作应由 A 的 adapter 投递回主线程）。

## 2. D 线（地震二维 viewer）

- 消费冻结接口：`ISeismicVolume`/`VolumeGeometryV1`（`pwb/viz/seismic_volume.hpp`，
  blob SHA `a4f0bfd7…`）+ `SelectionEventV1`。轴序 (inline, crossline, sample)、
  strides/lifetime 语义不变；`map_slice_to_indexed8` 数值 oracle 冻结。
- 本线 viewer 的 GL/关闭模式可参考 `libs/visualization/src/well_log/`（Qt 子属 +
  显式拆除顺序 + alive-guard），但 D 代码放自己的 `libs/seismic_viewer/`。
- 需要 C 侧公共 API 变更 → 提出缺陷与用例，C 做最小修复；勿自行改动公共库。

## 3. E 线（地震属性）

- 消费冻结接口：`IAlgorithm`/`AlgorithmRequestV1`/`VolumeView`/`Result`
  （`pwb/science/*.hpp`，blob SHA 见 v3-contracts.md §0）。descriptor 约定、
  provenance、诊断码规范沿用 `docs/development/cpp-science/02-contracts.md`。
- 运行 E 属性用本线 `TaskRuntime`：发布/取消/关闭语义即 v3-contracts §1
  （含 L0–L4 线性化表）；测试范式见 `tests/cpp/science/task_runtime_test.cpp`
  的屏障定序写法。

## 4. 已知边界 / 后续项

1. 引擎视图在当前呈现 spec 下不画深度标尺/文字（Linux TEXT=ON 亦然）——曲线与
   选择完整；如需标注，属 WLE 呈现 spec 演进，经 C 评估后升级 adapter。
2. Windows/MSVC/Qt6.8 构建与 B 入库端到端：A 验证（v3-verification §6）。
3. SelectionEventV1 的 `crs` 字段当前为空（纯深度选择）；井深↔地震时间换算需
   宿主显式速度模型，契约不做隐式换算。
4. D/E 消费中发现公共头缺陷 → 走最小修复流程，先沟通后改动。
