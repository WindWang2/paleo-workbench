# 05 — 人工解释与综合解释（Human-in-the-loop）

## IntegratedInterpretation（P0-4）

`workflow/interpretation/integrated_interpretation.py`，持久化 =
`ProjectDocument.integrated_interpretations`。绑定：input_set id、fusion
种子版本（+ latest_fusion_version_id 重跑追踪）、geometry layer、
committed catalog 版本、class schema、confidence/conflicts（fusion QC
提取，FUSION_CONFLICT_KEYS 常量）、修订链、QA ref、maturity。
`commit_integrated_interpretation`：层几何 → DERIVED 版本 +
`integrated_interpretation` DataRun（输入= fusion 种子 + 上一提交）+
commit 修订；空几何/无 catalog 拒绝；失败无文档残渣（R3-S4 验证）。

## InterpretationRevision（P0-6）

`workflow/interpretation/revision.py`，持久化 =
`ProjectDocument.interpretation_revisions`。每次内容变化记录：
target/base（RAW/fusion/factor/draft/manual/commit）、evidence_refs
（本修订依据的选择器——goal §13 三问可答）、内容指纹（9dp 稳定哈希）、
要素/顶点 delta、parent 链。内容未变不产生空修订；commit 后锚点推进
（last_committed_revision_id），`has_uncommitted_edits` 可见。

## 闭环

```
算法（fusion 播种）→ QGIS 可视化 → 专家编辑 → stage_save 记录修订
→ 重新评估（staleness/QA）→ commit（新 DERIVED 版本 + 修订）
```
融合重跑绝不覆盖人工草稿；解释记录追踪最新融合版本。
