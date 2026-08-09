---
status: accepted
---

# 宿主持久化图件 Revision

per-plot 的 revision 计数器不再只存在于内存：作为 `plots/<id>.json` 的顶层字段持久化（schema v3），保存时 bump 为新的已提交状态、加载时以 max 语义恢复（不回退）、emit 时 bump。宿主负责持久化（ADR 0025）；引擎 DocumentRevision 是另一套概念，本期不接线。

## 背景

T7 引入 `well-log-engine/apps/wellplot-desktop/well_log_workstation/events.py` 的 `_revisions` 时，revision 被刻意设计为纯内存态：当时为 composite 面板（油藏综合图）引入 panels 已导致一次 T9 schema bump，为避免再对 `plots/<id>.json` 做一次 schema 升级，revision 暂不落盘，`workspace.json` 的 catalog 亦不存储 revision 字段。

ADR 0025 明确宿主负责持久化，并把"未提交修改、Document Revision 与项目保存状态"区分为三套概念；本 ADR 落实其中与图件保存状态相关的一环：revision 必须跨会话存活。

仅内存态的后果：应用重启后所有图件 revision 归零，`plot_changed` 信号的 revision 参数在跨会话场景下不再单调；任何依赖 revision 判断"图件已变化"的消费方（如未来 composite 面板按 revision 决定刷新或使 snapshot 失效）都会失去可靠的比较基准。

## 决策

- `PlotDocument` 新增 `revision: int = 0` 字段（位于 `panels` 之后）；`PLOT_SCHEMA_VERSION` 2 → 3。
- `_to_json` 始终写出顶层 `"revision": int(doc.revision)`。
- `_from_json` 升级链沿用既有 v1 → v2 加法先例（plot_document.py:97-108）：v1 `setdefault("panels", [])`、v2 `setdefault("revision", 0)`；读取 `revision = max(0, int(data.get("revision") or 0))`；`version != 3` 抛 `WorkspaceError` 不变。
- 新增 `restore_plot_revision(plot_id, revision)`：以 `max(current, revision)` 播种内存计数器，**永不回退**。
- `save_plot_document` 写文件前 `doc.revision = bump_plot_revision(doc.id)`：保存即新的已提交状态，bump 但不 emit 信号。
- `load_plot_document` 解析成功后 `restore_plot_revision(doc.id, doc.revision)`。
- 引擎 `DocumentRevision` 已通过 `WellLogView.documentChanged` 信号暴露到 Python，但本期不接线：它是引擎文档内容版本，与宿主侧图件保存状态是两套概念。
- `workspace.json` 的 catalog 不加 revision 字段；revision 只随 `plots/<id>.json` 文档本体持久化。

## 后果

- 旧文件兼容：已有 v1/v2 文档经加法升级读取，revision 默认 0，首次保存即获得新版本号。
- 跨会话单调：加载播种 + 保存 bump，即使 load-modify-save 路径非原子（加载后崩溃、再次加载），`restore` 的 max 语义也保证 revision 不回退。
- save 不 emit 信号：composite 保存时不触发 `plot_changed`，面板刷新行为维持现状，避免保存动作本身造成刷新风暴。
- 未来工作：接线引擎 `documentChanged` 信号；按 revision 判断 composite snapshot 失效。
