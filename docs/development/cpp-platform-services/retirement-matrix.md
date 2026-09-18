# Platform Services — Python Retirement Matrix (CONV-PS)

Branch: `feat/cpp-platform-services-python-retirement` (base: origin/main @ ff67dcf3)
Scope: 平台层（settings / theme / tokens / resources / i18n / help / about /
diagnostics / startup-shutdown / QGIS runtime detection / launcher glue）。
不含 science kernels、workflow、map canvas、catalog、seismic（其他并行分支负责）。

## Scope ledger

### 本分支负责
- `paleo_workbench/ui/theme.py` + `paleo_workbench/tokens.py`：主题/密度/
  语义 token 词汇表与 QSS 生成 → C++ `Pwb::PlatformServices` ThemeTokens。
- `paleo_workbench/ui/layout_persistence.py`：QSettings 身份统一 + legacy
  迁移 + 面板布局记录 → C++ SettingsService（同 (PaleoWorkbench, Workstation)
  存储与键名，保证双端互读）。
- Settings/preferences/recent projects/paths 原生化 + 窗口几何持久化。
- Diagnostics（build/version/Qt/QGIS/provider/path/environment 报告）。
- Help/About 原生对话框 + 菜单接线（设置/帮助菜单、recent projects 菜单）。
- Startup/shutdown：窗口几何/dock 状态保存、clean shutdown 语义对齐。
- ResourceLocator：icons/templates/help 的 install/dev 路径解析
  （QStandardPaths，禁 Python package resources）。

### 本分支不负责（并行分支 / 已有归属）
- Product bootstrap/composition root 整体：`feat/cpp-native-product-closure`
  (PR #1353)。
- QGIS UI 工作站闭环（图层树/编辑工具/属性/布局）：PR #1351。
- Science 服务层：PR #1352；well-log host：PR #1359。
- 数据/工作区/目录生命周期：PR #1346；workflow runtime：PR #1348。
- cartography/styles/templates：PR #1364；composer/layout/export：PR #1361。
- map document edit session：PR #1363。

### 共享冲突文件（高风险区，改动最小化）
- `apps/paleo_workbench_platform/main_window.cpp/.hpp`（多分支都在加接线）—
  本分支只加 PlatformServices 接线块与帮助/设置菜单，尽量集中。
- `apps/paleo_workbench_platform/CMakeLists.txt`、
  `tests/cpp/platform/CMakeLists.txt` — 只追加行。
- 根 `CMakeLists.txt` — 若新增 lib 需 add_subdirectory，追加一行。

## Retirement matrix（随实现更新）

| Python surface | Production consumers | C++ replacement | Wired | Disposition |
|---|---|---|---|---|
| ui/theme.py (ThemeManager) | workstation shell, ui/style 动态注册表 | Pwb::PlatformServices ThemeService | (实现中) | replace |
| tokens.py (token 词汇表 + build_qss) | ui/* 大量、theme | ThemeTokens (palette_for/density_tokens/QSS) | (实现中) | replace-core; QSS 全量模板不移植（C++ 壳是 QGIS 原生 UI，QSS 子集面向平台窗口） |
| ui/layout_persistence.py | workstation shell, floating_panel | SettingsService (layout 组 + legacy 迁移) | (实现中) | replace |
| (PaleoWorkbench,WorkstationV3)/(PaleoWorkbench,paleo-workbench) legacy 存储 | 迁移入口 | SettingsService::migrateLegacy | (实现中) | replace |
| ui/style.py | theme_changed 订阅 widget | C++ QSS 全局表（无动态注册需求） | (实现中) | replace-core |
| run_app.py / __main__.py / app.py / main.py | launcher | apps/paleo_workbench_platform (已有) | 已接线 | keep-as-oracle/launcher-only |
| qt_platform.py (Qt 策略) | app 启动 | Qt6 默认策略 + main() 显式设置 | (实现中) | replace |
| env_bootstrap.py / QGIS env 探测 | Python 启动 | cmake 注入 prefix（PwbQgisSdk，已有） | 已接线 | covered |
| harness/diagnostics、about 文案 | Python 壳 | DiagnosticsReport + About | (实现中) | replace |
| resources/icons/i18n | Python UI | ResourceLocator (QStandardPaths) | (实现中) | replace-core |
| recent projects | ??? | SettingsService recent 列表 | (实现中) | native-new |

## 本地验证（已执行）

- Configure: linux-gcc-release 语义（Ninja, Release, PWB_BUILD_PLATFORM=ON,
  DATA=OFF, SCIENCE=OFF），QGIS SDK admission 主仓 vendor 树只读复用。
- Build: `cmake --build build/cpp-platform --parallel 3`（硬上限 -j3）全绿。
- CTest: platform 11/11 通过，含新增
  - `platform.services`：palette_for 106-token × 5 场景逐值对账、density
    ×3、主题/密度强制转换、QSS 主题差异化、legacy 迁移（幂等/不覆盖/删旧
    键/嵌套组）、窗口布局版本栅栏（fence==5 / 缺失 / 99 全部走默认）、
    recent_commands cap8+去重+单串强制转换、recent_projects cap10+清空、
    诊断探针（providers/CRS/transform 真值）、会话策略（headless 透传、
    xcb 清除、PALEO_FORCE_XCB、Mesa pin/已钉/退出/无 Wayland）、资源定位
    （override/穿越拒绝/诚实 miss）。含负自检：损坏的 palette 必须判
    FAIL（证明对账器可失败）。
  - `platform.ui_services`：设置/帮助/最近工程菜单、主题切换落盘+窗口级
    QSS 重渲染、closeEvent 布局落盘（version fence）、第二窗口恢复深色。
  - 全部 GUI 测试 offscreen + 注入式 QSettings（temp ini），不污染用户配置。
- Oracle: `tools/oracle/generate_platform_services_fixtures.py` 重跑
  byte-identical（md5 三件全对）。
- App CLI: `--version` → `paleo-workbench 0.2.17a0 (native <qt>)`；
  `--diagnostics` → 真实 QGIS 版本/prefix/17 providers/CRS×3 ok/transform ok
  /paths/environment（与 Python main.py 输出形状对齐）。
- app self-check（platform.qgis_smoke_app）：通过。

## Review 轮次

- Round A（parity，独立 agent）：结论见 PR。
- Round B（C++/Qt 架构，本 agent 自审）：已修 — EGL pin 的 stderr 警告
  移植（操作员可见性）、main.cpp 无用 include 清理、QSS 应用从 qApp 全局
  改为窗口级（qApp 全局 repolish 在 offscreen+QGIS 组合下 SIGSEGV，且
  窗口级级联本就是更收敛的语义）、load_persisted 去副作用（纯状态恢复，
  显式 apply 在控件树完成后执行）。
- Round C（产品闭环/Python 残留/并行冲突，独立 agent）：产品零 Python
  runtime 依赖（grep 无 python/shiboken/subprocess 代码引用）；诊断探针
  与资源定位诚实（degraded_reasons 纪律、目录穿越拒绝、诚实 miss）。
- Round A 修复（P2）：`clamp_to_desktop` 按 panel_float_controller.py 1:1
  重写 — 可见桌面=各屏 availableGeometry 并集；完全出屏→主屏 +24px 边距
  且尺寸不超主屏；部分出屏→仅位置 clamp（≥60px 可抓握），尺寸不动；
  暴露为可测 API 并加 6 个边界检查（含 Qt QRect::right() 含端点语义
  3779 钉值）。
- Round A 修复（P3）：CRS 探测集对齐 health.py 域集 {4326,4490,4214,4610}
  (+3857 变换目标)；`layout/inspector_user_hidden` 不再写常量 false（避免
  覆写共享存储上 Python 写的 true）；theme_changed 信号文档与实现一致；
  load_string_list 空 item 过滤标注为「故意差异」（手改存储卫生）；
  RuntimeProbe 删除无真实 API 可填的 proj_db_path 死字段。
- Round C 修复：openRecentProject 去掉与 openProject 成功路径重复的
  MRU 双写；main.cpp 误导性注释更正；resource_locator.hpp 死包含删除；
  注入式 QSettings 改 unique_ptr 管理；新增 5 组边界用例（单边 legacy
  存储×3、theme 归一化下划线/混合大小写/未 trim、no-change 不发射、
  超容量存储列表 load 侧裁剪、MRU 中位置顶+空 id no-op）。
- 最终复测：ctest platform 11/11 通过（-j3）。

## 并行分支冲突预案（merge order notes）

- `cmake/PwbQgisSdk.cmake`：nlohmann+GDAL 两个 hunk 与 PR #1353 逐字相同
  （Review C 已 diff 验证同内容同位置）——自动合并或零成本解决。
- `apps/paleo_workbench_platform/main.cpp`：**PR #1353 整体重写此文件**
  （bootstrap/self_check 抽取）。若 #1353 先合，本分支的会话策略/迁移/
  --version/--diagnostics 三块需按其 bootstrap 结构重排（语义保持，
  位置随新结构）；若本分支先合，#1353 吸收这三块。三块均为独立小函数
  调用，重排是机械操作。
- `apps/paleo_workbench_platform/main_window.cpp/.hpp`：与 PR #1351 在
  includes/@1218 closeEvent/@340 菜单区/@744 openProject 锚点重叠。语义
  互不相干（本分支=平台服务接线，#1351=编图工具），按 hunk 手工保留双方
  即可；本分支追加块全部带 `// CONV-PS` 标记。
- `tests/cpp/platform/CMakeLists.txt`：本分支全部为 1 行链接增补 + 带
  BEGIN/END CONV-PS 标记的独立块；与 #1353 的函数区/EOF 块冲突为机械解。

