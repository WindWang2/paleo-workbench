# 04 — Layer registry 与发布账本（V10）

## 1. 身份真源（D9）

- **C++ 侧**：`pwb/doc_id` custom property——QgsMapLayer 注册表的
  身份权威（镜像层创建时写入，跨栈收养按它比对）。
- **Python 侧**：发布账本（publish ledger）是 no-op/增量判定面，
  V10 加固为多 token 比较（§2）。`reset_publish_ledger()`（qgis_mirror.py:216）
  语义不变——重置仍是全量重发的显式通道。

身份本身只有一个真源（pwb/doc_id）；账本不是第二身份，是缓存性
判定面，锚定在 doc_id 上。

## 2. 账本 token 加固

| 项 | 内容 | 关闭的缺口 |
|---|---|---|
| name token（R1） | 编程改名（rename）后不再 no-op 命中陈旧条目——重发布触发一次 upsert，C++ `setName` 真正执行 | 00-baseline.md §B.5 |
| scale_range token | `_scale_range_token`（qgis_mirror.py:283）入账本比较——比例尺可见域变化重新发布（07-rendering.md §2） | §B.10 的宿主侧配套 |
| weakref stack-id guard（R2） | `_STACK_ID_REFS`（qgis_mirror.py:206 起）按 weakref 记栈身份；`id(stack)` 复用时清除陈旧 token——同地址新栈不再复活旧账目。不可 weakref 的栈类型诚实保留旧语义（不做假精确） | §B.6 |
| duplicate doc_id 诊断 + first-only publish（R4） | 同 doc_id 二次发布：首条生效，后续发布带诊断（不再静默双收养） | 审计新增项 |

## 3. 跨栈收养（R3）

镜像层跨栈收养（新栈按 `pwb/doc_id` 识别既有层）维持**纪律性收敛**：
单活 authoring shim + `shutdown_live_shims` 拆除契约（09-lifecycle.md §2）
保证同一时刻只有一个活编辑面——不是构造性隔离（类型系统/运行时都
不阻止第二活栈）。残余风险记录于 12-known-limitations.md 第 9 条。

## 4. no-op 比较的 token 全集

加固后账本条目比较维度：几何/要素增量（V7 feature-delta）、
fields/schema 签名（V9 `_verify_published_schema`）、**name token**、
**scale_range token**。全部 token 命中 → no-op 跳过；任一失配 →
单层 upsert（name/scale 失配走 style-only 量级路径，
10-performance.md §2）。

## 5. 活动层漂移位点（D1–D6）的收敛锚点

起点审计标注的 6 处 active-layer 状态读点（00-baseline.md §B.7）
在 V10 收敛：活动层真值单一化（registry 侧读 `pwb/doc_id` 锚定的
镜像层），清除通道走桥 `current_layer_clear`（01-qgis-runtime.md §2）
——不再依赖「层对象指针存活」这类会随重绑定漂移的隐式状态。

## 6. 与既有增量的关系

V7 的 feature-delta/增量发布、V9 的 `_verify_published_schema` 比对
全部不动——本文件的全部加固都发生在**发布判定面**（哪些变化值得
一次 upsert），不触碰发布执行面的预算模型（10-performance.md §1）。
