---
status: accepted
---

# 完整插件 Runtime 与宿主 Command 审计后置于 Desktop 首发（轨 P / T17）

Desktop **首发**（epic #288）仅交付 **声明式 Custom Layer + 同源/同工具链 SDK 嵌入**（ADR 0018 / 0046 / 0042）。  
**完整插件 Runtime**（发现、沙箱、热加载、第三方包生命周期）与 **宿主 Command 审计**（命令总线、可回放审计日志、权限边界）归 **轨 P 后续**，须按本 ADR 规格拆实现单，**不得**在未实现时宣称已支持通用插件市场或闭源二进制 ABI。

## 背景

- 愿景文档与 epic #288 共识：首发「插件最小化」——Custom Layer + SDK；Runtime / 宿主审计后置（T17 / #305）。
- ADR 0018：首期扩展为声明式原语，禁止扩展直接 OpenGL/改渲染状态；不承诺第三方 C++ 二进制 ABI。
- ADR 0046：Custom Layer 纯数据原语进 PreparedScene；内核统一 GL/SVG/拾取。
- ADR 0042：Pattern / Custom Layer 为不可信输入，须校验拒绝。
- T17 验收：不在 Desktop 首发；**另开规格后再拆实现单**（本 ADR + `docs/plugin-runtime-status.md` 即该规格）。

## 决策

### 1. 首发已交付的扩展面（不得回退）

| 能力 | 状态 |
|------|------|
| 声明式 Custom Layer 原语（折线/三角/矩形/符号/裁切等） | 引擎 + ADR 0018/0046 |
| 同源/同工具链内嵌（Python 宿主调引擎 API） | `well_log_workstation` + bindings |
| 不可信资产校验策略 | ADR 0042 |

首发 **没有**：entry-point 自动加载第三方插件、隔离进程、签名校验、完整 Command 总线审计 UI。

### 2. 完整 Runtime 形态（后续，拆单用）

建议实现分期（**P.\*** 子单，未开工）：

| ID | 内容 |
|----|------|
| **P.SPEC** | 本 ADR + status 文（本票关闭门禁） |
| **P.REG** | 版本化扩展点注册表（能力 ID、semver、宿主 API 契约） |
| **P.DISC** | 可选 discovery（如 `wellplot.plugins` entry points）——**默认关闭**，需显式设置才扫描 |
| **P.LOAD** | 加载策略：仅白名单路径 / 签名包；禁止静默从用户目录加载任意代码 |
| **P.AUDIT** | 宿主 Command 记录：命令名、目标图件/井 id、时间戳、结果；append-only；可选落盘 |
| **P.ISO** | （可选）进程/权限隔离；若需要再开 ADR |
| **P.CABI** | （可选）闭源二进制 ABI；相对 0018 显式修订后才做 |

### 3. 安全默认

- **默认不执行**第三方代码。Discovery 关闭时行为与今日相同。
- Custom Layer / Pattern 继续走数据面校验（0042），不因 Runtime 推迟而放松。
- 审计日志默认进程内环形缓冲；落盘路径与保留策略由 P.AUDIT 定，不得默认写敏感曲线样点。

### 4. 与导出 B1 / 首发的关系

- 轨 E（导出 B0/B1，#304）**不依赖**完整插件 Runtime。
- `IExportPlugin` 若出现，挂在 P.REG 能力 ID 下，且不得绕过现有 `export_dispatch` 披露/门禁。

## 后果

- T17 门禁闭合：规格存在，可拆 P.\* 实现单。
- 产品话术：首发 = Custom Layer + SDK 嵌入；「插件市场 / 任意 .so 热插拔」属后续。
- 宿主可先落地 **无动态加载** 的扩展点目录与 **可选** Command 审计环（见 `well_log_workstation/extension_points.py`、`command_audit.py`），不构成完整 Runtime。
