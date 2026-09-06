# Workstation UX V6 — 10 已知局限与遗留

Date: 2026-09-07 · 本文档是诚实边界声明：以下各项**未在本轮实现**，均经三轮评审确认后显式接受。

## A. 功能/UX 遗留

1. **Hub 页仍 force-float**（A-P1）：hub 页以浮动窗口呈现而非可停靠文档窗。改为 docked+持久化是后续工作。
2. **WellSeismicJointPage 等死代码未删**（A-P2 家族）：page_placeholder/screen_inventory/fallback_preview/ribbon_panel_entries ×9/4 个死 preset 枚举值/隐藏 MapEditToolbar。删除属独立清理 PR（涉及引用面审计）。
3. **group_summary 聚合无树 UI 消费者**（R1-P2）：stale/errors 计数已真实计算（layer_freshness 可查），但 QGIS 树尚未渲染组级/层级 glyph——需要桥侧 decoration 通道设计。
4. **镜像发布全层重序列化**（B-P1-1）：`qgis_mirror` 每次 publish 重序列化全部图层 + C++ truncate/reload——1000 层重绘噪声热点，需内容哈希增量发布。
5. **fallback 树全量重建**（B-P1-4）：无桥环境的图层面板每次 publish clear+rebuild。
6. **组内手动排序不持久**（B-P2）：系统组内用户拖动顺序被快照顺序覆写。
7. **完整性智能视图 ≥25k 物化回退**（C-P0-2 剩余）：fs probe 不可 SQL 映射；方案（离线程扫描+「—」）已写明未实施。
8. **Agent planner 永不产 WRITE 计划**：正则 5 意图不含写路径，授权对话框的自然触发面受限（harness API 与 LLM ChatModel 接线是后续项）；Task Center retry 重放闭包、run-history/resume UI、outputs/receipts 渲染未做。
9. **write_granted 布尔粒度**（R3-P2）：UIContext 把授权集合坍缩为 bool；`requires_write` 命令门比 Agent 面板的精确集合判定粗。首个真实 requires_write 命令落地时应细化为集合比较。
10. **地震/3D 面缺口**（E 家族未动）：命令面 caption 匹配手术、拾取静默拒绝反馈、SeismicVolumeState 孤儿、三套地震 chrome、模态失败对话框——本轮未进入（优先级让位于正确性 P0 与规模 P0）。
11. **Well Content Tree/Display Set 未入 workstation host**（D-P1）：仅 wellplot-desktop 侧实现。
12. **视觉机械迁移未做**（G-P0 剩余）：218 处 legacy 页面内联样式/86 固定尺寸/106 内联字号需 lint ratchet 推进，不适合本 PR 手改；emoji 状态图标（数据页）未替换为状态语言。

## B. 平台/验证边界

13. **仅 Windows/offscreen 验证**：无 macOS/Linux 实机；无 4K/HiDPI 实屏截图（visual QA 无 DPR>1 状态）。
14. **visual QA 无 1366×768 状态**；并发测试进程可能污染 QSettings 注册表（再生成基线时须独占运行，见 v6_evidence README §4.1）。
15. **主分支既有环境失败**（非本分支引入，09 §4）：map_authoring_architecture_guards ×1、keyboard_shortcuts 焦点 ×3、test_ui_exports 导入顺序。

## C. 范围硬边界（按 /goal 明令排除）

16. **100GB 地震体支持/基准/优化不在本轮**——未实现、未基准、未宣称。
