# 12 — task_plan（主程序收口、双平台部署与无 Python 验收）

<!-- 恢复协议：上下文压缩/会话重启后先读本文件 + findings.md + progress.md +
     acceptance.md，恢复同一目标与预算记录。协调登记：
     .git/codex-coordination/cpp-close-wave/12-line.json -->

## 目标（/goal 语义的文件持久化）

在 paleo-workbench 最新主线（origin/main @ 06211541，已重新 fetch 确认为生成时
锚点）基础上，完成本任务负责的：全局组合逻辑收口、01–11 真实安装点集成、
C++ 独立可运行安装包与无 Python 验收证据、全局迁移矩阵生成器，交付可审查 PR。

- 平台 /goal、/goal-loop 支持核查：`which goal` 不存在；技能清单
  （zcode 官方插件目录 + 会话技能列表）无 /goal、/goal-loop 命令。
  → 采用文件持久化循环（本文件），如实记录，不伪造命令成功。
- 预算：360,000,000 tokens 为上限请求。平台无按 token 计量接口可查询，
  无法在运行时读取确切累计用量 → 无法宣称该额度已生效；按"完成即可停止"
  执行，不派生无意义任务消耗预算。
- 子代理上限：根 ≤3，每个子代理 ≤3，同模型继承，不并行写同一文件。

## 验收门（本线完成定义）

1. 四 deferred AppShell 信号（save/open_sample/properties/preview_settings）
   有生产处理器 + 真实测试；CommandPalette context/tool-details provider 注入。
2. 产品入口 placeholder/null provider/deferred host 审计清单（findings.md），
   可修的修，不可修的如实登记依赖线。
3. 迁移矩阵生成器可从仓库事实+各线 ledger 生成 implemented/merged/wired/
   verified 矩阵；带自身测试。
4. 打包：deploy-native-product.sh/audit-python-runtime-deps.sh 复验 + 许可
   材料审计 + （增量）CI；不重写既有脚本。
5. 平台闭包（QGIS SDK）本地构建 + platform.* 测试（资源门 j2，关键回归×2）。
6. 独立审查（1 个子代理）+ 高优先级修复 + 复验。
7. 提交/推送/PR（不 merge）；PR 正文含前后行为变化、测试 SHA/命令/结果、
   真实限制。

## 范围边界

- 独占：app_shell/main_window/app_context 全局组合、根 CMake 公共门、
  CI/presets/packaging、全局迁移矩阵、release 验收文档。
- 01–11 只带独立安装模块 + 小型具名注册块；12 不越权改其目录。
- 不删除 Python 参考实现；不做无边界产品扩张；stub 只做测试替身。

## 轮次状态

- R1 盘点完成（见 progress.md）。
