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
- D/E 集成：未交付，未发生。
