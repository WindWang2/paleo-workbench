# V6 视觉 QA 证据页（Phase 8）— 人工复核模板

> 本页是 **manual-review 工作台**：截图与语义检查结果是供人判读的证据，
> 不是自动门禁。填写下方复核记录时保持诚实——只声明本环境真实跑过的
> 内容；本套件运行在 **offscreen 平台、无 QGIS 桥**（composite 回退画布），
> 因此这里**不包含**任何真实显示服务器 / DPR>1 / QGIS 原生渲染的验证声明。

## 1. 覆盖的状态（6 个新增，不改动既有 12 状态）

注册形态与 V5 harness 一致（`(合成工程工厂, 驱动函数)`），驱动与语义
检查在 `paleo_workbench/ui/visual_qa_v6.py`，注册合并在
`scripts/capture_workstation_screens.py`（`shots.update(v6_shot_table(...))`）。

| 状态 | 画面内容 | 关键语义不变量（`run_state_checks`） |
|---|---|---|
| `mapping_stage_phase1` | 阶段 ① 初始相图校正：阶段条 + 阶段面板 + 工具条 | 阶段条 ① checked（②③ 不 checked）；面板第 1 页在栈顶；**`add_line` 工具动作隐藏**；`add_polygon` 可见 |
| `mapping_stage_phase2` | 阶段 ② 约束与单因素 | 阶段条 ② checked；面板第 2 页；**`add_line` 可见**；约束创建行仅本阶段显示 |
| `mapping_stage_phase3` | 阶段 ③ 综合编图 | 阶段条 ③ checked；面板第 3 页；`add_line`/`add_polygon` 可见 |
| `command_palette_context` | Ctrl+K 面板打开，过滤「单因素」 | 阶段 2 专属命令在阶段 1 下**禁用但可见**：条目文本含人类可读原因（当前编图阶段不可用…）、item flag 无 `ItemIsEnabled`、spec 带 `stages` 白名单 |
| `write_grant_dialog` | Agent WRITE 授权对话框（真实注册表动作卡） | 拒绝按钮为 **default**；按钮文案 拒绝/授权；未交互 `granted=False`；每个动作 id 有卡（`map.add_layer`/`map.export`，非「未知动作」降级） |
| `status_workbench_segment` | 状态条工作台段（阶段 · 编辑目标 · 后端 · 任务） | 段文本非空；含后端态（本环境诚实显示「画布回退（QGIS 桥不可用）」）；阶段 ② 已反映到段内 |

每个状态在基线矩阵中各 6 份（light × compact/comfortable × 1180×720 /
1440×900 / 1920×1080）→ 共 **36 张新基线**，位于 `visual_qa/baseline-v6-matrix/`。
既有 30 张 v5 矩阵基线（`baseline-v5-matrix/`）与 12 张 `baseline-v5/`
**未重生成、未触碰**。

## 2. 如何再生成 / 重跑

```bash
# 基线（写入 visual_qa/baseline-v6-matrix/；确认无人为像素改动后提交）
QT_QPA_PLATFORM=offscreen python scripts/capture_ui_matrix.py --v6 visual_qa/baseline-v6-matrix

# 当前矩阵（临时目录）+ 与基线的 PIL 像素 diff 报告（非门禁）
QT_QPA_PLATFORM=offscreen python scripts/capture_ui_matrix.py --v6 /tmp/ui-matrix-v6
python scripts/diff_ui_matrix.py visual_qa/baseline-v6-matrix /tmp/ui-matrix-v6 \
    --out /tmp/ui-matrix-v6/diff-report.md

# 单状态细查（含语义检查 PASS/FAIL 行与 _checks/<state>.json 旁车）
QT_QPA_PLATFORM=offscreen python scripts/capture_workstation_screens.py /tmp/v6-one \
    --shot mapping_stage_phase2 --theme light --density comfortable --size 1440x900
```

门禁断言（注册、语义检查、基线在位、v5 基线不被触碰）在
`tests/test_visual_qa_v6.py`：

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_visual_qa_v6.py -q --timeout=300
```

## 3. 非门禁 diff 政策（与 V5 一致，decisions.md D8）

- **像素 diff 非门禁**：`diff_ui_matrix.py` 的比例分级（>1% changed /
  >5% 大面积）只标注供人工判读；主题/字体渲染微差容忍（灰度差 ≤16 忽略）。
- **语义检查在 harness 内同样非门禁**：截图子进程把每状态检查结果写
  `_checks/<state>.json`（`state_ok` 汇总位）并打印 `CHECK PASS/FAIL` 行，
  **不使截图失败**——截图证据优先落盘，失败项交给测试门禁与人复核。
- **测试才是门禁**：`tests/test_visual_qa_v6.py` 把同一批语义检查作为
  硬断言（结构回归靠语义 Qt tests 钉住，像素证据不替代断言）。

## 4. 诚实边界（本环境没有验证过的，不声明）

- 截图来自 `QWidget.grab()` 的 **offscreen 渲染**；无真实窗口管理器、
  无 DPR>1 / 多屏 / 1366×768 状态（V6 残留，见 docs G-P2）。
- 本套件 **无 QGIS 桥**：地图区是回退画布的真实渲染（状态条亦如实标注
  「画布回退」）。QGIS 原生渲染需在构建了 `qgis_render_bridge` 的环境
  另行验证（`pytest -m qgis` 腿），本页不含该声明。
- `write_grant_dialog` 抓的是对话框本体（独立顶层窗，560×480；基线
  文件名中的矩阵尺寸对应该次运行的主窗请求，非对话框像素尺寸）；
  动作卡使用真实 harness WRITE 动作（非伪造 spec）。
- **尚未覆盖的 V6 状态（残留）**：stale factor（过期单因素）态、active
  editing target 带被拒原因的态——需要更重的合成工程（版本钉住/依赖传播），
  留待 Phase 8 后续。

### 4.1 尺寸守卫与已知隔离边界（Windows 注册表）

V6 起主窗几何会持久化（`restoreGeometry`，G-P0-2 修复）。在 Windows 上
`QSettings(org, app)` 双参构造是**注册表**存储——`XDG_CONFIG_HOME` /
`setPath(IniFormat)` 都拦不住它。因此截图子进程的布局沙箱对该存储只有
「进程启动时 + show 前各 clear 一次」的弱隔离：**同时段运行的其他进程**
（例如同时跑的 pytest 套件）若构造工作台窗口，会写入同一注册表键，
可能被 +50ms 的 post-show 恢复定时器读到，把主窗几何改掉。

对策（已实装）：`--shot` 子进程在 grab 前做**尺寸守卫**——窗口实际尺寸
与 `--size` 请求不符时该 shot **显式失败**（exit 1，矩阵 manifest 记
FAILED），绝不静默落盘与文件名不符的像素。基线生成期间不要并行运行
其它构造工作台窗口的进程；单次顺序运行实测 36/36 通过、重复运行像素
diff 0.00%。

## 5. 人工复核记录（每次基线变更后填写）

| 日期 | 复核人 | 范围 | 结论 / 备注 |
|---|---|---|---|
| _ | _ | _ | _ |
