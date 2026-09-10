# 09 — 评审发现与修复记录

三轮评审（goal §38）：Round 1 科学正确性、Round 2 架构、Round 3 工作流对抗。
全部 P0/P1 已修复；P2 除显式记录者外均已修复。

## Round 1（科学）+ Round 2（架构）—— commit 038ba688

| 级别 | 发现 | 修复 |
| --- | --- | --- |
| P0 | 多约束组时 constraints:current 冻结钉首组=暗洞（R1-F1/R2-F4） | 恰好一组才钉+重写显式选择器；多组拒绝 |
| P1 | 冻结产出不可解析 constraints::ver（R1-F2）；服务路径指纹死代码（R1-F4）；V9 引用不持久化→发布砖死（R1-F5/R2-F2）；published 可解冻（R1-F6）；draft 跳评审（R1-F7）；批量路径缺 CRS 检查（R1-F3）；结构化输入集零消费者（R2-F1）；三处分叉组装（R2-F3） | 全部修复（见 commit 信息） |
| P2 | cancel CANCELLING 幂等、'current' 组名、width/height 键、uncertainty 原因推导、alias 索引重建、current_vers
