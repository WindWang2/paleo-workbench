# Prompt A — C++ Qt/QGIS 平台、地图编辑和集成

将本文件全部内容作为一个独立开发任务的输入。GOAL 模式执行，并使用 `agent/skills/goal-loop/SKILL.md`。

## GOAL

在 `feat/cpp-platform-qgis` 独立 worktree 中交付 C++20/Qt/QGIS 平台首轮实现：统一构建与运行时，直接 C++ 地图画布/图层树、原生编辑和工具状态、布局导出及最小安装验证；发布供 B/C 集成的接口和构建入口，以真实 QGIS smoke 和本轮全部 Oracle 为完成依据。

范围对应总设计 P0/P1、P3 的 QGIS 一侧和 CPP-10/CPP-30。第一轮不要求完成所有旧版 UI，也不把模块通过声明为完整产品切换。

## 启动与隔离

1. 阅读 `docs/development/full-cpp-migration-v1/01-parallel-development.md` 全文、总设计、goal-loop、`CLAUDE.md` 和适用 AGENTS。
2. 工作目录必须为 `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-platform`；分支必须为 `feat/cpp-platform-qgis`。核验 `cpp-migration-plan-v1` 是当前 HEAD 的祖先。
3. 若没有 worktree，仅在目标目录和分支都不存在时，从主仓创建：`git worktree add --no-checkout -b feat/cpp-platform-qgis ../paleo-workbench-cpp-platform cpp-migration-plan-v1`，再按共同协议初始化稀疏 checkout 与空索引。若已存在则核验后使用，不重复创建。
4. 使用原生 goal API 注册本 GOAL；已有相同目标则恢复。最多 15 轮，每轮按 skill 更新根账本的 CPP-A 区段。
5. 只做本分支开发。相关旧 PR #1301/#1304/#1310、V11–V13 文档及历史修复是输入；先检查新 PR/issues 是否重复。
6. 资源硬限制：三个任务总共一个重型槽；自己不再创建 subagent；编译/测试最多 2 jobs；8 GiB 内存门槛，QGIS 全量构建 12 GiB；必须使用共同资源门禁。资源返回 75 时继续轻量工作，禁止绕过或无限重试。

## 唯一写入范围

顶层 CMake/Presets/vcpkg、`cmake/`、`apps/`、`libs/qgis/`、`libs/ui/`、`libs/application/`、`libs/tool_policy/`、`tests/cpp/platform/`、新 `.github/workflows/cpp-*.yml`、`scripts/cpp-migration/`、`docs/development/cpp-platform/`。

B 的数据库/schema/recovery coordinator 和 C 的算法/viewer 由对应 owner 实现。不要修改旧 Python、旧 bridge 的 API 或 vendor 源码；确需 QGIS vendor patch，先记录原因、上游差异和 owner 决策，不能偷偷改变公共基线。

## 必查代码

- `native/qgis_render_bridge/src/{bindings.cpp,qgis_render_bridge.*,map_stack_service.*,edit_tools.*,style_codec.*,geometry_service.*}`
- `paleo_workbench/ui/qgis_stack/{widgets.py,canvas_shim.py,display_canvas.py}`
- `paleo_workbench/qgis_runtime/`
- `paleo_workbench/mapping/{tool_context.py,tool_availability.py,qgis_mirror.py,map_render_backend.py}`
- `paleo_workbench/ui/workstation/`
- `docs/adr/0057-*`、`0059-*` 和 V11/V12/V13 的权威、编辑、图层顺序和已知限制文档
- 现有 Windows QGIS 构建脚本与 QGIS CI；`well-log-engine/CMakeLists.txt` 的 Qt 要求

## 交付步骤

### A0：先冻结实际运行时与接口

在 `docs/development/cpp-platform/` 输出 baseline、contracts、test-plan、progress。记录 QGIS/Qt/compiler/CRT/SDK 路径和实际可用能力；复核 Qt 版本候选，选唯一 ABI。不要在一进程混装系统 Qt、PySide Qt 和 Conda Qt。

明确：
- `Pwb::Qgis`、`Pwb::Application`、`Pwb::ToolPolicy` targets；
- `EditDeltaV1`、MapSession/CanvasHost 生命周期；
- 对 B 的 ProjectSnapshot/LayerBinding/CommitRequest adapter；
- 对 C 的 viewer/result publisher adapter；
- QGIS project 为 session-owned，进程 QGIS init/exit 唯一，不依赖无边界全局 singleton。

### A1：统一 CMake 和最小主程序

创建 C++20 executable，直接链接 Qt/QGIS；复用已验证 QGIS build flags。QGIS SDK 只由 A 构建；优先验证现有 install artifact 能否复用，manifest 不匹配则独立低并发构建。

根配置能单独只构建 platform；B/C 开关 OFF 可独立开发，ON 必须真实查到 targets，否则失败。不要把“模块不存在”偷偷记为测试通过。

MainWindow 内直接使用 QgsMapCanvas/QgsLayerTreeView，无 Shiboken/raw pointer address bridge。创建/读取真实图层，provider 初始化错误有诊断，启动失败不得冒充 fallback 成功。

### A2：地图、状态机与编辑

从既有纯 ToolContext/evaluate_tool 移植语义到独立 C++ ToolPolicy；不要复制规则进 QAction。覆盖 active/current/edit layer 一致性、无工程、只读 provider、阶段限制、选择、dirty、capturing、committing、取消/关闭。

实现本轮必要编辑：开启/结束、移动顶点、捕捉、撤销/重做、拓扑校验。QGIS edit buffer 是编辑期间唯一几何状态。旧 C++ 几何/拓扑核按需复用，不能复制 Python/QGIS 两套 undo。

QGIS 图层树是顺序/可见性运行态权威；标签/图例/布局使用同一 project。保留现有 custom property join key，输出 staged asset 给 B 的提交协议，不直接写 catalog.sqlite。

### A3：生命周期、导出与部署

- 明确 tool → canvas/tree → project → runtime 关闭顺序，采用 Qt parent 与 RAII；
- GUI 线程操作 QGIS GUI；worker 只传不可变结果，不以 processEvents 嵌套事件泵等待；
- PNG/PDF/SVG 导出至少建立真实 smoke，QGIS 缺能力时必须明确失败；
- provider、CRS、GDAL/PROJ data 和 Qt platform plugin 的部署 manifest；
- 新 CI workflow 配置 Windows/Linux 验证；没有在某平台实际跑过就不能说该平台通过；
- 最小 Windows package 具备无 Python 的启动/加载/渲染 smoke。签名发布属于后续 P6，不是本轮伪造证书/成功的理由。

### A4：集成接线

先用自己测试目录的 B/C port substitutes 完成平台独立测试；在报告标注“仅模块验证”。B/C 可用后，在本分支有序合入已提交成果，由 `libs/application/adapters/` 连接真实模块；集成的通过状态单独记录。等待其他线期间继续独立测试/审查，不每分钟轮询、重建或空循环。

## 本轮 Oracle（全部必选）

1. 本分支 C++20 platform 配置/编译退出码 0；生成真实 executable，无生产 Python runtime/bridge 链接。
2. 实际 QGIS smoke：创建画布/树、打开矢量与栅格 fixture、验证 provider/CRS、渲染和导出；不是 fake QGIS 测试。
3. ToolPolicy 参数化测试覆盖 active/current/edit、只读/dirty/capture/commit/关闭，QAction 与 policy 输出一致。
4. 编辑一次顶点 → undo/redo → staged asset 输出，重读几何与属性正确；拓扑错误阻止非法提交。
5. 生命周期关键测试至少 20 次自动开/关循环，实际统计无 crash；500 次 soak/sanitizer 安排为集成/稳定性门禁，未跑不能声称通过。
6. 发布运行时 manifest、构建说明、所有 CTest 的实际测试数/失败数/skip 数、已知限制；测试数为 0 或生产路径全 skip 不通过。
7. 顺序审查并修复本范围的高优先级问题；关键确定性 smoke 二次复验通过。
8. 提交本分支内交付物，报告 commit 和 integration-ready 状态。仅真实 B/C E2E 通过后才能记录 integrated。

## 收尾与资源释放

账本最终区段复制到 `docs/development/cpp-platform/ledger.md`。输出 changed files、命令/退出码、SDK manifest、未完成 P3/P6/P7 项和下一步集成入口。只清理自己的临时文件，保留 worktree 与测试证据；确认本任务无遗留构建/GUI 进程。15 轮上限或外部资源阻塞时明确“未完成”，不能用 stub、忽略失败或跳过 Oracle 来结束 GOAL。
