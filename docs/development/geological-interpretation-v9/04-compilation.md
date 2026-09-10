# 04 — CompilationInputSet（综合编图输入集）

## 契约（goal §14）

`workflow/interpretation/compilation.py`。持久化 =
`ProjectDocument.compilation_input_sets`（dict 载体，schema 由本模块拥有）；
工作区旧 `compilation_input_set` dict 是兼容视图。
**消费一律经 `evidence_view(document, state)` 单一适配器**（结构化激活集
优先，legacy 回退）——fusion / staleness / attribution 三处消费者共用。

## 状态机与原子性

```
draft（可增删证据） --freeze--> frozen（版本钉死）
```

* freeze 把每条可解析条目**钉死版本并重写为显式带版本选择器**
  （`factor:t:ver_1` / `constraints:g:ver_c`）——pin 必须对融合/评估可见；
* `constraints:current` 浮动条目：恰好一个约束组有提交 → 钉该组并重写；
  多组有提交 → 拒绝（钉一组=给其余组留暗洞，评审 R1-F1）；
* UNPINNED/MISSING/UNKNOWN 条目 → 原子拒绝（快照回滚选择器+pin，R3-F4）；
* 证据增删双写（select_evidence / _remove_evidence）。

## 验证词汇

`validate_input_set` → ready（全部可用）/ degraded（含未钉版本）/
blocked（缺失/未知）。预测证据为 run 级溯源（无文件版本）→ UNPINNED →
degraded（诚实，不伪称可钉）。
