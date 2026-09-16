---
name: goal-loop
description: "Fixes goal modes that stop after one round — built for ZCode's GOAL mode (its Stop hook caps auto-continuation at 3). Keeps the agent iterating inside a single turn until an explicitly verifiable completion condition is met — no premature \"done\". Best for long tasks: paper revision, batch document processing, data pipelines, coding. 为 ZCode GOAL 模式一轮就结束而写：设定可验证完成条件，单轮内持续迭代直到达成，禁止提前宣告完成。Triggers: '/goal-loop', '循环直到完成', '跑到完成为止', '不要停', '一口气做完', 'keep going', 'loop until done', 'run until complete'."
license: MIT
compatibility: Pure prompt-driven, zero dependencies. Works in any Agent Skills-compatible host (Claude Code, ZCode, Codex CLI, Cursor, Gemini CLI, etc.). No scripts, no network access required.
metadata:
  author: bravesd
  version: "1.0.0"
  homepage: https://github.com/bravesd/goal-loop
  tags: loop,autonomous,iteration,goal,agent
---

# GOAL Loop — 单轮内持续迭代直到可验证完成

> ZCode 的 GOAL 模式"一轮就结束"：模型提前宣告完成，回合终止；且官方文档明确 **Stop hook 最多只能请求继续 3 次**，无法像 Codex 那样无限自主推进。
> 本技能的对策：**把完成条件变成可验证的硬性检查，验收不通过就永远不结束当前回合。** 其他 Agent Skills 宿主同样适用。

## 启动协议

用户给出目标后，先在回复开头声明三件事（一次性，之后不再重复）：

```
▎ [GOAL Loop] 已启动
▎ 目标：<一句话复述>
▎ 完成条件（Oracle）：<可客观检查的条件，如"所有测试通过"/"PDF 共 N 页且无占位符"/"脚本退出码为 0">
▎ 迭代上限：<默认 15 轮，防止烧钱；用户可改>
```

**完成条件必须可验证**——"代码写好了"、"论文改好了"不合格；"npm test 退出码 0"、"文档里搜索不到 TODO/占位符"、"程序能跑通用户给的样例输入"才合格。如果用户给的目标太模糊，把最接近可验证的解释写出来直接采用，不要停下来问。

## 迭代循环（核心）

每一轮迭代按固定顺序执行：

1. **读账本** — 读取 `<工作区>/.goal-loop-ledger.md`（没有则本轮结束时创建），回顾已试过什么、失败在哪
2. **评估差距** — 当前状态离完成条件还差什么？只列真差距
3. **单一改动** — 每轮只做一个聚焦的改动（改多了无法归因）
4. **运行验证** — 亲自跑验证命令/检查，**不要凭感觉判断**
5. **记账** — 向账本追加一行：`第N轮 | 改动 | 验证结果 | 通过/未通过 | 下一步`
6. **判定** — 验证通过 → 跳到完成协议；未通过 → 回到第 1 步

## 三条红线

1. **验收条件未满足，禁止结束回合。** "看起来差不多了"、"剩下的比较简单"、"时间差不多了"都不是结束理由。宁可多跑一轮空验证，也不带着未验证的"完成"退出。
2. **禁止说"我无法解决"然后退出。** 卡住时换方法：换工具、换搜索词、换思路、拆小问题。穷尽手段后才允许走 abort 信号。
3. **"完成"必须附带证据。** 宣告完成时，最终回复必须包含验证命令的实际输出或验证结果的直接描述（页数、通过数、退出码），不能只说"已完成"。

## 卡壳升级（防止原地打转）

| 连续未通过轮次 | 强制动作 |
|---|---|
| 1–2 | 正常推进，换个小角度重试 |
| 3–4 | 停下来：重读验证输出全文，列出 3 个**不同**的失败假设，选最不像原因的那个先排除 |
| 5–7 | 换层级：换个工具/换条路径/把问题拆成两半分别验证 |
| 8+ | 质疑前提：完成条件本身是否定义错了？回到需求重新推导，必要时走 pause 信号 |

## 人工介入信号（仅两种）

- `<loop-abort>` — 真的不可自动化完成（缺外部权限/账号/硬件，或需求本身矛盾）。输出前说明卡在哪、试过什么。
- `<loop-pause>` — 需要用户补一个具体信息（密钥、二选一决策）。先把进度完整写入账本再提问。

**禁止**用这两个信号逃避困难——验证失败不是 abort 理由，是迭代理由。

## 完成协议

验证通过后：
1. 再跑一次验证确认不是侥幸（关键验证跑两遍）
2. 清理中间产物（临时文件、调试代码），账本保留
3. 最终回复：目标回顾 + 验证证据 + 迭代轮数 + 遗留事项（如有）

## 使用示例

**输入：**
```
/goal-loop 把论文里所有图表引用改成新编号顺序，完成条件：全文搜不到旧编号、每个交叉引用都能对应上实体图表
```

**预期行为：** Agent 先复述目标与 Oracle → 逐章扫描替换 → 全文正则自检（第一遍）→ 发现 2 处漏网 → 修复 → 再自检（第二遍）→ 附带"搜索 0 命中"的证据后宣告完成。

## 设计说明

- **为什么要求"验证跑两遍"**：单次通过可能是侥幸（缓存、部分文件），第二遍排除假阳性。
- **为什么每轮只改一处**：多改动并行时无法归因失败原因，账本会失真。
- **与外部循环器（Ralph 等）的关系**：Ralph 靠外层 bash 无限重启会话，需要 CLI 入口；本技能纯 prompt 驱动，在单轮内完成循环，绕开 ZCode Stop hook 的 3 次继续上限，任何支持 Agent Skills 的宿主开箱即用。
