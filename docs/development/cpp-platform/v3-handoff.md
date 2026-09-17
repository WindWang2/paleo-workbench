# CPP-A v3 交接（codex/cpp-v2-platform → B/C/D/E 与下轮）

> 交付 SHA：`18ba6409`（分支头；基线 `53e22b67`）。
> 验证证据：`v3-verification.md`（模块）、`v3-integration-verification.md`（集成）。

## 1. D 线（地震二维 viewer）消费指南

1. 根构建开关：`PWB_BUILD_SEISMIC_VIEWER`（默认 OFF；ON 而 `libs/seismic_viewer/CMakeLists.txt` 缺失 → FATAL_ERROR，实测）。
2. ABI/SDK：`v3-runtime-manifest.md` §1——Linux 验证环境 Qt 6.11.2 系统单源 + vendored QGIS 4.2.0（`PwbQgis::Sdk` imported targets，头文件搜索集已含生成头目录）。`PWB_QT_PREFIX` 约束是 fail-closed 的。
3. 契约：C 线冻结头（`pwb/viz/seismic_volume.hpp` blob `a4f0bfd7…` 等）；A 侧 join key/编辑/导出见 `v3-contracts.md`。
4. 嵌入位：MainWindow 已有左右 dock 区（图层树左、测井右）；D 的 viewer dock 接 `apps/paleo_workbench_platform/main_window.cpp`（跟随 `PWB_WITH_*` 编译守卫模式，参考 WLE dock 的 22 行接线）。
5. 数据：A 经 `CatalogResultPublisher` 已把 C3 结果落成 **PWBVOL1**（`libs/application/include/pwb/application/adapters/volume_payload.hpp`：版本化头 shape/axes/units/布局 + float32 C-order，自带 reader）。D 重开产物即可用该 reader 取 volume（`integration.algorithm_chain` 是消费范例）。**PWBVOL1 是验证格式，不冒充 SEG-Y/Zarr**；D 如需行业格式输入走自己的线内实现。
6. 没有速度模型时禁止井深↔地震时间直接映射（C 契约；A 的选择转发用 origin/revision + 显式单位）。

## 2. E 线（地震属性）消费指南

1. `PWB_BUILD_SEISMIC_ATTRIBUTES` fail-closed 同 D。
2. E 提供公开 factory/register 函数；A 只在 `libs/application`/app 注册并投影参数（范例：`integration.algorithm_chain` 对 C3 的 registry 注册 + TaskRuntime 提交 + `CatalogResultPublisher` 发布全链）。
3. 结果发布：经 `CatalogResultPublisher`（宿主先 `set_request_context` 供给输入几何 + 输入版本 id）；单任务恰好一个结果 volume（B 本轮 publish 契约，多余/为零在写入前拒绝）。

## 3. B 线交接

1. 归还缺陷与修复位置：
   - **oracle fixture 绝对路径**（`tests/cpp/data/fixtures/*/oracle_resolve.json` 的 `resolved` 指向你方 worktree）→ `data.oracle_compare/readback` 在你的树外必失败；建议相对化或 compare 前预处理。A 树中该两测失败即此因（其余 17 项 data.* 全绿）。
   - `libs/catalog/CMakeLists.txt`：vendored `sqlite3.c` 已加 `-fvisibility=hidden`（非 MSVC）——集成进程符号抢占 GDAL 的系统 libsqlite3 导致堆损坏（`v3-integration-verification.md` §5 有根因栈）。请吸收。
2. A 消费面：`PwbDataStore`（`libs/application/src/adapters/data_store.cpp`）当前用 Manager+Repository+Coordinator 组合；你的 `WritableSession` 实现交付（`a228bafb`）后，切换点已注释在头文件（接口不变）。

## 4. C 线交接

1. WLE dock 已按你 handoff §1.2 方式 1 消费（`PWB_WELL_LOG_ENGINE_ROOT` → 你的只读 install tree；A 未重建 WLE）。
2. 归还缺陷：`WellLogHostWidget` 无 `Q_OBJECT`（`findChild`/`qobject_cast` 不可用，A 经 dock->widget() static_cast）——建议加 Q_OBJECT。
3. TaskRuntime v3 语义消费无异常（`integration.algorithm_chain` 全绿；取消/异常/发布失败路径均按你的 L0–L4 表现）。

## 5. 下轮（A 侧待办）

1. D/E 交付后的 integrated 接线（地震 dock、四属性注册）+ 对应 integration 测试扩展。
2. ProjectSession 接 PwbDataStore 常态化（app 打开真实 .paleo 工程的 UI 流：当前 loadFixtures/open* 为 shell 级，B 绑定经集成测试证明）。
3. “staged 未发布”作为 dirty-close 的第二级状态（本轮 module-only save 语义已在 ui_wiring 注释）。
4. Windows/MSVC/Qt6.8 环境的等价验证（manifest 已就绪，无法本机执行）。
5. 发布包 rpath（$ORIGIN）与干净机 smoke。

## 6. 运行入口（本 worktree）

```bash
# 平台交互窗口（offscreen 无显示时用 --self-check）
LD_LIBRARY_PATH=<vendor>/output/lib QT_QPA_PLATFORM=offscreen \
  ./build/cpp-integrated/apps/paleo_workbench_platform/pwb-platform --self-check
# 部署树受控自检
env -i PATH=/usr/bin:/bin QT_QPA_PLATFORM=offscreen PROJ_DATA=/usr/share/proj \
  LD_LIBRARY_PATH=build/cpp-integrated/deploy/lib \
  build/cpp-integrated/deploy/pwb-platform --self-check
```
