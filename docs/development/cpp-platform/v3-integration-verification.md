# CPP-A v3 集成验证（五线汇总，Linux 实测）

> 分支：`codex/cpp-v2-platform`；验证日期：2026-09-17；全部数字为门禁内真实运行结果。
> 环境：GCC 16.2.1 / Qt 6.11.2（系统单源）/ QGIS 4.2.0 vendored / glibc；见 `v3-runtime-manifest.md`。

## 1. 合入的其他线交付（普通 merge，SHA 可追溯）

| 线 | 合入 SHA | 内容 |
|---|---|---|
| B 数据 | `82430eca` → `a228bafb` → `50075fb0` + `2286b23b`（merge commit `1356c85a` 起连续吸收） | v3 契约（run 生命周期/单产物发布/显式恢复）+ 实现 + 只读零足迹修复 + 验证文档 |
| C 科学 | `410bd6b0` | TaskRuntime 发布/关闭语义 v3、WellLogHostWidget 公共头、WLE SDK install tree、四件套文档 |
| D 地震 viewer | **未交付** | 无 `libs/seismic_viewer/`；`PWB_BUILD_SEISMIC_VIEWER=ON` → configure FATAL_ERROR（fail-closed，实测） |
| E 地震属性 | **未交付** | 无 `libs/seismic_attributes/`；同上 fail-closed |

冲突处理：`libs/domain/src/support.cpp`、`libs/project/src/paths.cpp` 两处 B 与我的移植修复同内容冲突，**取 B 侧**（B 是 owner，且双方修复一致）。

## 2. integrated 配置（根 CMake）

```
cmake -S . -B build/cpp-integrated -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DPWB_BUILD_PLATFORM=ON -DPWB_BUILD_DATA=ON -DPWB_BUILD_SCIENCE=ON \
  -DPWB_BUILD_INTEGRATION_TESTS=ON \
  -DPWB_SCIENCE_BUILD_TESTS=ON -DPWB_SCIENCE_BUILD_VIEWER=ON \
  -DPWB_WELL_LOG_ENGINE_ROOT=<C 的只读 install tree>
```

- `pwb-platform` 真实链接闭包含 Pwb::Data/Science/Workflow/Visualization + `Pwb::VisualizationWellLog`（WLE adapter；C 是 WLE 唯一构建者，本线未重建第二份）。
- `PWB_BUILD_INTEGRATION_TESTS=ON` 在 platform/data/science 任一缺失时 configure 失败（all-or-nothing，实测代码在根 CMake）。

## 3. 实测结果（经 invoke-resource-gate.sh，exit 0/8 如实）

### integrated 树（build/cpp-integrated，2026-09-17）

```
34 tests: 32 Passed, 2 Failed
  data.*           17/19（oracle_compare/oracle_readback 失败 = B fixture 可移植性，见 §6）
  science.*         4/4（含 coherence_c3 oracle、task_runtime v3 语义）
  platform.*        9/9（含 ui_wiring、qgis_smoke_app）
  integration.*     2/2（project_chain、algorithm_chain）
```

### 纯平台树回归（build/cpp-platform，同日重建后）

```
platform.* 9/9 Passed（模块独立构建路径未因集成改动回归）
```

### 关键确定性链路（每条都在本轮复验）

1. **工程链**（`integration.project_chain`）：B typical fixture 副本 → PwbDataStore 打开（真实 ProjectManager+CatalogRepository+CommitCoordinator）→ join-key 绑定图层 → 顶点编辑 → undo/redo → staged GeoJSON → B commit → **版本恰好 +1、旧版本 sha256 不变、重开后绑定推进到新版本**；重复 operation_id → 幂等回执（不新增版本）；stale base → 拒绝。
2. **算法链**（`integration.algorithm_chain`）：冻结 oracle（tiny.sgy 实数据）→ C3 经 TaskRuntime（C v3 发布语义）→ CatalogResultPublisher → B register_run + publish_run_result（run 仅在 payload/目录/绑定全部 durable 后 complete）→ **重开 store 读回 PWBVOL1 与 oracle 期望体积 max_diff < 2e-3（C 冻结容差）**；取消 → durable `cancelled` 且零输出版本；kernel 异常 → durable `failed`；异常后后续任务继续执行。
3. **WLE 嵌入**：`pwb-platform --self-check` 在 integrated 配置加载真实 `A1.Las` 进测井 dock（`platform.qgis_smoke_app` 实测）。
4. **错误链**：拓扑拒绝（bowtie，`platform.edit_cycle`）、provider 失败诊断（`platform.qgis_smoke`）、module-only 诚实错误（`platform.adapters_substitutes`）、dirty-close 三态 + 保存失败不销毁编辑（`platform.ui_wiring`）。

## 4. 链接与部署审计

- `ldd pwb-platform`：**0** 个 python/pyside/shiboken/qgis_render_bridge Python 扩展依赖（grep 命中 5 项为路径名 `qgis_render_bridge/` 目录字样，非库名）。Qt 全部解析到 `/usr/lib`（单源）。
- 最小部署树 `build/cpp-integrated/deploy/`（二进制 + qgis/protobuf .so 闭包）在 `env -i PATH=/usr/bin:/bin` 受控环境下 `--self-check` **退出码 0**。限制：二进制内嵌 BUILD_RPATH 指向构建期 vendor 目录（dev 树部署；发布包需 $ORIGIN 相对 rpath，未做，如实记录）。

## 5. 集成中发现并修复的真实缺陷

| 缺陷 | 定位 | 修复 |
|---|---|---|
| 双 sqlite3 符号抢占（静态 vendored 符号被主程序导出，抢占 GDAL 动态 libsqlite3 内部调用 → 堆损坏/SEGV，glibc `corrupted double-linked list`） | `libs/catalog/CMakeLists.txt` | vendored `sqlite3.c` `-fvisibility=hidden`（A 侧修复，归还 B） |
| MainWindow 析构顺序 UAF（`actions_` 先于 `session_` 销毁，MapSession::close 的 mapToolSet 信号回调使用已销毁成员） | `apps/.../main_window.cpp` | 析构函数体内先做有序 close（成员全存活时）；integrated 堆布局下稳定复现后修复 |
| QAction 所有权缺失（ToolActionSet 不删除其动作） | `libs/ui/tool_actions.*` | 析构删除 |
| 编辑后动作状态不刷新（undo/redo/dirty 判定过期，禁用态 action 触发无效） | vertex tool / refresh 链 | `refreshActionStates` public + 顶点移动后调用 |
| `MapSession::layerById` 关闭后解引用空 project | `libs/qgis/map_session.cpp` | 空守卫 |

## 6. 移交其他线的缺陷（未在本分支修，已定位+复现）

| 缺陷 | 归属 | 证据 |
|---|---|---|
| oracle fixture 内嵌 checkout 绝对路径（`oracle_resolve.json` 的 `resolved` 指向 B worktree），`data.oracle_compare`/`data.oracle_readback` 在 B 自己的树外必失败 | **B** | 我树 32/34，仅此两项失败；B 树内 19/19（其 v3-verification 记录）。建议：oracle 相对化或测试期预处理 |
| `libs/project/src/paths.cpp` windows.h/gmtime 等移植（B 已自行同修，无需动作） | B | 双方提交一致 |
| `WellLogHostWidget` 无 Q_OBJECT（findChild/qobject_cast 不可用，宿主只能 static_cast 经 dock 取） | **C**（低优先，建议加 Q_OBJECT） | `apps/.../main_window.cpp` loadLasIntoDock 注释 |

## 7. 本轮未完成 / 未验证（诚实清单）

1. **D/E 未交付** → 五线集成的地震二维 viewer 嵌入、E 四属性注册运行未发生；对应开关 fail-closed。**A 轮完整验收条件未全部满足**，本报告为准完成态（B/C 侧全绿）。
2. 可见桌面交互截图：headless 环境未执行（offscreen 断言替代）。
3. Windows/MSVC/Qt6.8 全链（无环境）；Linux 为唯一验证平台。
4. 500-cycle soak、ASan/UBSan、性能基准：未执行。
5. D 的 ISeismicVolume 真实显示、井深↔地震时间换算（需速度模型，契约禁止隐式换算）：D 线交付后接线。
