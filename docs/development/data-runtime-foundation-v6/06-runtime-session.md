# 06 — Runtime Session Generation + Real Cancellation（#1223, #1224）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 1. 会话代际 = 目录后端身份

`catalog_is_current(service)`（catalog/runtime，`__init__` 再导出）：`set_catalog`/`reset_catalog` 在每次工程打开/关闭/切换时换后端 → **后端身份即权威会话令牌**，取代散落的页内序号。语义（评审后精化）：无活动后端（headless/全关）≠ 陈旧；只有**不同的**后端在位才是陈旧——危害是错写到新工程，缺席后端收不到错写。

接线：
- 地震属性 on_done/on_fail/on_cancel：陈旧则释放租约并退出（守卫在登记之前）。
- 地震转码 `_register_derived`：同款守卫（评审 R2#4 补齐与属性路径的对称性）。
- mapping_page 导出槽：对比导出开始捕获的 project 与页面当前 `_project`（评审 R2#1 修复了读取不存在属性导致登记死代码的缺陷）。
- `resume_pending` 接入工程打开维护（中断转码不再滞留 running 至无关生命周期活动）。

## 2. 真取消

| 操作 | 旧行为 | 现行为 |
|---|---|---|
| 哈希（sha256_file） | 无取消 | chunk 粒度取消令牌（MiB 级），`ChecksumCancelled`，绝不给部分摘要；`verify_integrity(cancel=)` 透传 |
| 地图导出 | 渲染前后检查 | native→fallback、装饰前、保存前三处检查点；不可中断渲染相位诚实标注，无半成品 |
| 调度器同键重提 | ValueError（取消请求后旧任务占键到落地） | QUEUED 重复键**超越**（旧任务 CANCELLED + 触发其 on_cancel 舒展副作用，评审 R2#6）；RUNNING 拒绝信息诚实说明 |
| LAS 单文件解析 | 前后检查 | 保持（lasio 不可注入）——OwnedWorkerJob released-guard 丢弃迟到投递，新请求不排队等旧 worker；文档明示 |

槽位释放：取消的交互 worker 经 OwnedWorkerJob shutdown(3s) → DetachedJobKeeper 收养，槽位 <1s 释放（线程收尾不阻塞 UI/调度）。

## 3. 证据（tests/test_runtime_session_and_cancel.py，6 例 + 调度器回归）

令牌语义（替换才陈旧/缺席不陈旧/换回不复活）、属性回调守卫源契约、chunk 取消时机（第 4 次轮询即停）、verify_integrity 诚实 cancelled 状态、超越生命周期（旧任务终态 CANCELLED 未运行）、导出检查点契约。
