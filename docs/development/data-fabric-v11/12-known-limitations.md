# 12 — Known Limitations

V11 交付时明确记录的边界（诚实清单，非未完成项）。

## 数据模型

1. **bundle 成员数软上限 64/版本、run 端口数软上限 256**（11-scale）。
   超限拒绝注册并报错 —— 大目录应走多资产导入而非巨型 bundle。
2. **成员级 lineage 不存在**（设计决策，04 §6）：lineage 粒度保持版本级；
   bundle 内部结构由 members + required 表达。
3. **role 词表开放**：未知角色加载/往返无阻，UI 归入 other 组；
   cardinality 是指导性元数据，不是加载门槛（02 D4）。
4. **`EntityAssetLink.ordinal` 已有字段但绑定路径只写 0**：排序语义
   （多 LAS 加载顺序）在 view 层按 (is_primary, ordinal, name) 稳定排序，
   ordinal 的用户编辑入口留给后续 UX（当前 primary 已满足主要用例）。

## 存储与兼容

5. **新版本 app 写的 run_ports/version_members 行被旧版本 app 丢弃**：
   旧代码 rebuild（write_all）时不认识新表 —— 前向兼容为尽力而为
   （与 staging_leases/working_cvisions 同代际语义）。旧→新方向无损。
6. **catalog.json manifest 中 ports/members 以 Pydantic 默认字段往返**：
   更旧的 loader 忽略未知字段（extra 行为），数据不丢但语义降级。
7. **forward compat：`DataRun.input_ports` 在 v5 store 上打开时为空**，
   直到该 run 行下一次被标记 dirty 才会写入新表（懒回填语义）。

## 陈旧性 / impact

8. **staleness 触发规则基于"资产 current 指针演进 + trashed 祖先"**：
   不检测"外部文件被原地篡改"（那是 integrity/verify_integrity 的职责，
   两维度分离是既有设计）。
9. **pin 豁免不等于冻结快照**：pinned 下游的输入版本被物理 purge 后，
   lineage 显示缺失上游（delete_impact 预先警告此点）。
10. **ImpactService 假设单写者会话内的 document 一致性**：跨进程并发写
    由 catalog CAS 拒绝；impact 读面不做跨进程快照。

## UI

11. **井详情面板同步组装**：单井视图代价受控（批量点查），但 10k 井
    逐个快速双击极端场景未做请求合并（实际操作频率下无感知）。
12. **entity_activated 只在双击实体行时触发**；文件叶/角色组行为不变。
13. **ingest plan 的 UI 呈示层未落地**：planner/execute 是完整服务层 API
    （已被测试覆盖），Data Manager 的"计划确认对话框"交互留给下一迭代
    ——当前目录导入仍走既有批量导入路径（内部等价能力）。

## 规模

14. **entity_asset_links 全量驻留 ProjectDocument**：10k 井 × 8 角色 ×
    平均 2.5 资产 ≈ 200k links 在现状承受范围；links 分片索引化是 V12
    方向（11 §3）。
15. **impact 全图闭包上限 MAX_IMPACT_NODES=20k / MAX_STALE_ITEMS=2k**，
    超限截断并在 reason 中标记。

## Review 轮次后的残余项（P3 级）

17. **井详情首开仍是同步槽装配 + worker 迟到陈旧**：槽/版本/缺失探测
    同步（有界点查），陈旧计算走 worker 信号回填（09 §3 精神）；若
    worker 失败卡片显示"无过期成果"前的空态而非错误态。
18. **角色组计数显示总数、子项受 MAX_WELL_FILE_CHILDREN 截断**：溢出
    行已提示，但组标题不显示 rendered/total（UI 打磨项）。
19. **井详情卡片显示截断版本 id**（前 14 字符）——完整 id 在 tooltip
    级别的呈现留给 UX 迭代。
20. **`_stale_job` 单飞**：同一时刻只允许一个陈旧计算；连续快速切换
    实体时后发的计算被跳过（等下一次刷新钩子）。
21. **well_index 陈旧徽章按最近演化祖先资产归因**，井详情按 any-ancestor
    ——两者可能相差"自身资产演化"的计入（详情更完整，徽章偏保守）。

## 非管理文件（沿既有设计）

16. recipe 文档（*.paleo-workflow.json）与 DAG run store 保持 catalog
    之外（会话/文档层语义，01 §2 已论证）。
