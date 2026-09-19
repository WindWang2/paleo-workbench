# 12 — progress

<!-- 每轮：候选SHA、目标、范围差量、真实命令/退出码、测试数据、资源租约、发现/处理、下一步 -->

## R1 盘点（2026-09-20，候选基线 origin/main 06211541ae1ccce22b0d5ba9258ce722170ca98b）

- `git fetch origin`（退出 0）；`git rev-parse origin/main` → 06211541（与任务
  书锚点一致）。开放 PR：#1413(14线)/#1414(01线)/#1415(02线)/#1412(mapping)。
- 平台 /goal、/goal-loop：不存在（`which goal` 空；技能清单无）→ 文件持久化
  循环，预算 360M tokens 上限不可运行时核验 → 如实记录，不宣称生效。
- worktree：`/home/kevin/project/worktrees/cpp-close-12-product-integration`，
  分支 `codex/cpp-close-12-product-integration-20260920`（自 origin/main），
  `--unset-upstream`。协调登记 `.git/codex-coordination/cpp-close-wave/12-line.json`。
- 环境探测：系统无 cmake；共享工具链 `/tmp/pwb-oracle-venv/bin`（cmake 4.4.3，
  ninja 1.13）。vendored QGIS SDK 中断于 2660/3000（output/ 已有 4 个 .so）。
- 审计完成：UI-17 deferred 全清单 + viz A–E 安装点核实 + 占位宿主属主
  归属（见 findings.md R1–R2）。

## R2 实现（2026-09-20）

- 新增 `apps/paleo_workbench_platform/shell_project_actions.{hpp,cpp}`：
  save_open_project（#1126 编辑提交门 + ProjectManager 三阶段）、
  project_properties_text、bootstrap_sample_project（newProject 生命周期 +
  内置 8 井 run publish + workspace 绑定持久化）。
- `main_window.{hpp,cpp}`（12 线独占组合面）：四信号生产接线、File 菜单
  保存工程/样例/属性入口、properties responder seam、noteDomainLayerFacts、
  showPreviewSettingsRequested（UI-07 store/panel，window-modal open）、
  palette 双 provider 注入（session snapshot → CommandContext；
  explain/format_details → 详情）。
- `libs/ui_shell command_palette.{hpp,cpp}`：additive
  `set_context_provider`（具名租约 CPP-CLOSE-12，镜像既有 details setter；
  UI-01 属主经协调登记告知）。
- 根 `CMakeLists.txt`：BEGIN/END CPP-CLOSE-12 装配块（shell_project_actions
  入 pwb-platform 与 platform_app_shell；UiPagesPreviewQt 链接 +
  PWB_WITH_UI_PAGES_PREVIEW_QT；新增 platform.shell_project_actions 测试）。
- 测试：`tests/cpp/platform/test_shell_project_actions.cpp`（空态/样例引导/
  会话契约/保存-重开往返/预览设置持久化）；`test_app_shell.cpp` 增量 palette
  provider 断言（map: 详情 tooltip 非空）。
- 迁移矩阵：`tools/migration/pwb_closure_matrix.py` + 12 线
  capability-matrix.json + 生成的 closure-matrix.md；
  `tests/test_closure_matrix_generator.py` 6/6 通过（pytest 9.1.1，
  /tmp/pwb-oracle-venv）。
- 许可审计：`scripts/cpp-migration/audit-licenses.sh`（bash -n 通过）。

## R3 验证（待资源门）

- 资源门 Probe → RESOURCE_BUSY（08 线持锁，~30min）→ 排队退避中。
- 待执行：vendored SDK 尾部构建（369 步）→ worktree Configure（PLATFORM
  全闭包，PALEO_QGIS_SDK_DIR 只读指向）→ 平台构建（j2）→
  platform.shell_project_actions + platform.app_shell + 受影响回归 ×2。
- 编译验证未完成前不提交（先本地全绿）。

## R4 审查与修复（2026-09-20）

- 独立审查代理（1 个，只读静态审查）：2×P0 + 4×P1 + 10×P2，全部处置
  （逐条见 acceptance.md R5）。要点：ui_shell include 误入 namespace
  （P0，编译阻断）、测试目标缺预览闭包（P0）、shell_project_actions 在
  无 data 闭包构建下的编译破坏（P1）、样例引导未激活图层（P1）、预览
  容器改为复用 UI-15 PreviewSettingsDialog + 窗口持有 store（P2×2）。

## R5 构建与测试（2026-09-20，资源门内完成）

- vendored QGIS SDK：恢复构建 exit 0（尾部已在早前持锁轮次完成）。
- Configure + Build（j2，603 targets）：经一轮 API 误用修复（vectorLayerById
  形参）与两轮链接/守卫修复后 **exit 0**。
- 测试：Round A 2/2 → Round B **21/21 platform.\* 全绿** → Round C 关键
  回归二遍 6/6。全部 exit 0（ctest，offscreen）。
- 中途发现并修复：预存测试目标经 PWB_APP_SERVICE_SOURCES 编译
  main_window.cpp，未链新源导致 link 失败 → 集合上按 TARGET Pwb::Data
  统一追加（findings R7）。

## R6 验收审计与部署（2026-09-20）

- audit-python-runtime-deps.sh：归类修订后 **AUDIT PASS（exit 0）**；
  --exe ldd 审计待部署树（诚实 SKIP 标注）。
- 部署：deploy-native-product.sh → /tmp/pwb12-dist（资源门退避排队中，
  结果回填 acceptance.md）。
- 提交/推送/PR：待部署轮次落地后执行。
