# 05 — 测井、连井对比与井震标定联通 — task_plan.md

- date started: 2026-09-19
- base SHA: 06211541ae1ccce22b0d5ba9258ce722170ca98b (origin/main, fetched)
- branch: codex/cpp-close-05-well-crosswell-20260919
- worktree: /home/kevin/project/worktrees/cpp-close-05-well-crosswell
- executor: glm5.3-flash (ZCode), goal-loop with file persistence

## Platform note (/goal, /goal-loop)
- 执行平台（ZCode 会话）当前可用技能列表中**没有** /goal、/goal-loop 命令或对应技能。
- 处理：按任务文件规定，采用同等语义的**文件持久化循环**（本目录四份文件 + 协调登记），
  不安装未知插件、不伪造命令成功。预算按 token 累计记录于 progress.md（预算上限 3.6e8，
  属上限请求而非目标消耗量）。

## Goal (from task file)
在最新 main 上完成 05 线负责的 C++ 转换、现有新功能迁移与产品闭环，交付可审查 PR：
- 独占范围：well-log 适配器、viz_a/viz_b 安装模块、cross-well/well-tie 产品层及相关测试
- 复用已合并 A/B 的 LAS/WLE、DTW、标定、轨道绘制和报告
- 补：XML worker 真加载；B 的真实 LAS 数据通路；A 的共享井身份
- 打通：资产→测井/连井→编辑 tops/picks/links→标定→保存重开→报告
- 核对 pattern 近似与导出行为；连井会话恢复与结果来源显示
- 只向 04 提供 well/time-depth presenter；井震 3D 归 06；报告模板短写与 13 分工

## Loop protocol
每轮记录于 progress.md：候选 SHA、目标、范围差量、真实命令/退出码、测试数据、
资源租约、发现/处理、下一步。恢复点 = 本目录四文件 + git 分支。

## Verification gate (from task file)
- LAS/XML 真文件；不同深度单位/缺曲线/反向深度；取消与迟到结果；跨工程切换
- 编辑重开与标定数值可复现；真实 dock 测试覆盖对象销毁；04 能消费 presenter
- oracle 由冻结 Python 生成并记录 SHA/版本/数据/容差，含篡改或负面 self-check
- 确定性关键回归至少跑两遍；GL 证据分开报告
