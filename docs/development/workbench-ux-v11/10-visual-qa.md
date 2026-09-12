# 10 — Visual QA (V11)

## 脚本化场景矩阵（goal §20）

`paleo_workbench/ui/visual_qa_v11.py` — 13 个场景（`V11_SCENARIOS`），构建真实面板（合成事实，不 mock 呈现层），每场景带结构检查注册表（`run_scenario_checks`）+ 抓图非空/尺寸断言；像素 diff 非门禁（D8 政策延续）。

| # | 场景 | 覆盖 |
|---|---|---|
| 1 | `first_open_empty_shell` | 首开（空工程 AppShell；检查器=工程上下文、任务中心 0 行） |
| 2 | `data_manager_surface` | Data Manager（5 类型资源 + 选中资产的检查器行） |
| 3 | `well_task_workflow_panel` | 井工作流（任务面板 pending/running/complete 三态——词表渲染） |
| 4 | `seismic_context_surface` | 地震工作流（上下文工具条 工区/属性/模式） |
| 5-7 | `stage_bar_phase1/2/3` | Phase ①②③（阶段条+面板：标记/栈页/约束行） |
| 8 | `inspector_version_payload` | Inspector 2.0 版本实体 |
| 9 | `inspector_run_payload` | Inspector 2.0 Run 实体 |
| 10 | `task_center_operations` | 任务运行中（registry 42% + 终态结果标签 + 跳转入口） |
| 11 | `command_palette_disabled_reason` | 错误/禁用态（palette 禁用原因 + 工具详情 tooltip） |
| 12 | `error_empty_states_composite` | 空/加载/警示徽章组合面板 |
| 13 | `theme_matrix_smoke` | 主题×分辨率矩阵（亮/暗 × 1280×720/1920×1080，尺寸精确 + 采样色 ≥2） |

对话框场景由既有 v6-v10 场景族继续覆盖（WRITE 授权、RAW 阻断、捕捉详情、拓扑 chip、CRS、紧凑 1366 工具条等）；high-DPI 由 DPR 感知图标路径 + `test_a11y_dpi_v6.py` 门禁覆盖（offscreen 无真实高 DPI 屏，记录于 12）。

## 门禁

`tests/test_v11_visual_qa.py`：每场景 grab() 非空 + 全部结构检查通过；注册表形状断言（场景可发现性）；主题矩阵轴向断言。与 v6–v10 谱系同跑全绿（v6 措辞断言已对齐 V10 M10 单一真源）。

## 运行

```
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_v11_visual_qa.py -q
```

全场景 offscreen 可渲染（无 skip）；两个整壳场景经 canvas_shim monkeypatch 钉住无桥确定性。
