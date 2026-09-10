# 13 — Known Limitations（V10 边界清单）

## 原生树菜单的 evaluator 化（桥依赖）

原生 `QgsLayerTreeView` 右键菜单由 C++ 桥侧组合（`map_stack_service.cpp`
的 `createContextMenu`），菜单项 enable 无法从 Python 覆写（无菜单校验
API）。V10 已把**执行侧**升级为完整 evaluator re-gate（拒绝带判词进状态
条）；菜单项呈现级 enable 的统一需要桥新增「菜单项可用性回调」API——
移交后续桥方向。回退树面板已完整 evaluator 化（M5）。

## 环境限制（本 worktree，非产品）

* QGIS 渲染桥未安装（vendored 构建需数小时）：全部 UI 测试跑 fallback
  画布（offscreen）。原生路径断言（row indicators、native menu、
  destination_crs、reshape 能力门）为代码级验证 + 信号模拟（V8 同策）。
* Windows 本机多窗口/多状态同进程连跑偶发 Qt 崩溃（`test_mapping_stage_ui`
  在干净 main 同样崩溃——既有环境问题）：V10 视觉 QA 逐状态运行为绿；
  批跑用 batched runner。

## 语义边界（记录在案）

* **capture 组不进 palette**：palette 快照无法诚实判定「kind 会话细节」
  （add_point/line/polygon 依赖活动层会话 + kind），执行面覆盖（工具条/
  画布菜单/快捷键）；split/merge/reshape 已因 v4 快照事实进入 palette。
* **阶段面板无 per-item 门禁**：按钮永可点，执行统一 re-gate + 判词状态
  条（V6 起的设计取舍——阶段动作多为向导式，禁用态反而误导）。
* `stage_group_visibility()` 返回**组级**呈现映射；cancel 的逐工具豁免
  （未知阶段可见）不反映在该映射（docstring 已注明）。
* 菜单 exec 期间共享 QAction 可见性变化可产生孤儿分隔符（菜单生命周期
  极短，实际不可达；aboutToShow 重算留后续）。
* help 签名含易变字段（scale/tolerance）——zoom 后首次刷新会重拼同文
  tooltip（成本有界，语义正确；字段级签名留优化）。
* legacy `MapStatusBar.update_state` 保留（mapping_page 兼容）；其 chip
  无事实输入（恒「查看/编辑」两态）——legacy 页不在 V10 呈现承诺内。
* `write_granted` 仍是无生产消费者的预留字段（V6 起记录；Agent WRITE
  授权与 evaluator 的会合点在 UIContext，非 ToolContext）。
* 程序化批量建层（测试态）需手动抑制 layers_changed 重组；产品路径无
  此需求（用户逐层操作）。

## 100GB seismic 排除（Goal §37）

本方向未触及 seismic cache / GPU paging / volume LOD / SEG-Y 基准。
既有 seismic dock UI 维持原状。
