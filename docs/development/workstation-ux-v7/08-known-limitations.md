# 08 — Known Limitations（V7 已知限制）

## 环境边界

- **qgis_render_bridge 未构建**（与 main 一致）。原生树行内装饰仅编辑
  铅笔（桥 API 边界）；原生路径的组/问题态经 Python 侧摘要行呈现。
  样式库/原生属性等 native-only 功能在本环境以禁用+原因呈现（诚实）。
- 平台覆盖：Windows/offscreen（V6 同）；无 macOS/Linux；DPR>1 未做
  实机验证（Qt 高 DPI 策略默认开启，token/布局无像素锁死）。
- 全量长跑 GC-flaky：`test_lod_render_path` / `test_layer_visibility_
  authority`（main 同现象，单跑均过）；满载时 theme-switch 测试可能超时。
  验收用分批运行（05）。

## 呈现与交互

- 溢出收纳在默认 1440×900 窗口即部分生效（全量工具条 ~1500px）：尾部
  组进「»」菜单，核心编辑组始终在条上；加宽或减少 dock 占宽即恢复。
  进一步收敛需要双行工具条（未做）。
- 死 factor task 的 Inspector 降级到通用 layer 分节（诚实但未标注原因；
  评审 R3#5 记录）。
- `map:toggle_editing` 未注册进 palette（避免执行侧绕过风险的保守选择；
  工具条有该按钮且门禁三层复核）。
- 原生树（有桥时）与回退树的装饰能力不对等：回退树全装饰，原生树
  Python 侧摘要 + 铅笔。桥获得通用指示器 API 后可对齐（adapter 就绪）。

## 架构债（显式登记，非阻塞）

- artifact-key 解析在 `_layer_maturity_value` 与 `layer_freshness` 两处
  维护（历史形态；R2-F7）。建议提取 `artifact_keys_for_membership()`。
- `MapActionController.update_state`（legacy enable）与 `apply_availability`
  的顺序依赖（调用方必须后接 availability；两处调用点均正确）。建议补
  controller action ids == `_ALL_TOOLS` 全等测试（R2-F8）。
- 遗留 ratchet 存量：41 行字面 font-size（21 文件）、12 处字面定宽、
  32 行预算内裸色——只减不增，预算在 tests/test_ui_token_hygiene.py。
- `write_granted` 是保留位：本应用 WRITE grant 门控 Agent 动作；首个
  需要授权的地图工具出现前求值器不声称该门禁（R1#5 处置）。

## 保留的"死代码"（有真实功能，非死）

- `MapEditToolbar` 隐藏 shim：承载 preview/canvas-priority/topology-rebuild
  等无 QAction 等价物的功能——删除即删功能（M7 裁决保留）。
- `well_seismic_joint_page`（legacy 页）：是井震资产快照/导出 lineage 的
  测试载体；导航已被 3D 页取代，但导出机制依赖此页。

## 明确不做（本 Goal 边界）

- 100GB seismic（零涉及）。
- QGIS 桥 C++ 修改 / 重建（D2）。
- QGIS 原生 dialog 内部换肤（D5 延续）。
- 5-hub 页面架构移除（120 活跃页是生产面；只清死页与接缝）。
- mirror publish 1000 层重序列化优化（native-only 不可测路径，V6 遗留
  登记）。
