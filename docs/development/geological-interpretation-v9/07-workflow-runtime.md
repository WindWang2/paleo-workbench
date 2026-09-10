# 07 — Workflow 运行时

## 任务状态（goal §27）

`TaskState`：QUEUED / RUNNING / **CANCELLING** / DONE / **DEGRADED** /
FAILED / CANCELLED（+ `TERMINAL_TASK_STATES`）。

* CANCELLING：协作取消等待期可见（不再伪装 RUNNING）；二次取消幂等接受；
* DEGRADED：`TaskSpec.degraded_when(result)` 谓词为真（或谓词自身异常）的
  终态——"成功"必须含 registered artifact + DataRun + output version，
  否则最多 DEGRADED；
* 取消后晚到结果不触发 on_done（不作为完成消费）。

## 动作面（goal §26）

新增（`harness/actions/interpretation_v9.py`，全部带 verifier 或显式
side_effect_notes）：

```
compilation.create_input_set / freeze_input_set
interpretation.commit / compare
map_product.assemble / review / publish
```

UI 阶段动作（stage_actions）与 harness 动作调用**同一领域函数**
（单一实现双入口）：commit_constraints、commit_interpretation、
组装（assembly_from_workspace 共享构造器）、融合（evidence_view）。

## MapProduct 生命周期（goal §31）

```
DRAFT →（review：产品级 QA 无 ERROR/BLOCKER）→ REVIEWED
      →（freeze）→ FROZEN →（publish：仅 FROZEN + BLOCKER/ERROR 清零）→ PUBLISHED
任何时刻 → SUPERSEDED（首个继承者胜）
```
PUBLISHED 不可冻结/解冻/取代路径外修改；unfreeze 回 DRAFT。
产品级 QA（severity: INFO/WARNING/ERROR/BLOCKER）挂 record.product_qa。
