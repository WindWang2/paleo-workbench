# Plugin Runtime status (T17 / #305 · 轨 P)

规格与分期门禁文档。完整插件 Runtime **不在** Desktop 首发（epic #288）验收范围。

## 决策来源

- [ADR 0055](adr/0055-plugin-runtime-staged-after-first-ship.md) — Runtime / 宿主审计后置
- [ADR 0018](adr/0018-declarative-custom-layer-extension.md) — 声明式 Custom Layer
- [ADR 0046](adr/0046-declarative-custom-layer.md) — 原语与 PreparedScene
- [ADR 0042](adr/0042-untrusted-external-assets.md) — 不可信资产

## 首发已有（勿与 Runtime 混淆）

| 能力 | 说明 |
|------|------|
| Custom Layer 数据原语 | 由引擎分解进 GL/SVG/PDF/拾取；扩展不直接渲染 |
| Python 宿主嵌入 | `well_log_workstation` 调 WellLogEngine / 本机模块 |
| 扩展点目录（只读） | `well_log_workstation.extension_points` 列出**内建**能力，不加载第三方包 |
| Command 审计环（可选） | `well_log_workstation.command_audit` 进程内 append-only 记录，默认不落盘、不加载插件 |

## 实现切片（待拆 GitHub 子单）

| ID | 内容 | 状态 |
|----|------|------|
| **P.SPEC** | 本文件 + ADR 0055 | ✅ 本票 |
| **P.REG** | 版本化扩展点注册与 API 契约 | 未开工 |
| **P.DISC** | 可选 entry-point discovery（默认关） | 未开工 |
| **P.LOAD** | 白名单/签名加载 | 未开工 |
| **P.AUDIT** | Command 审计落盘、查询 UI、与 undo 关联 | 骨架：内存环 |
| **P.ISO** | 隔离（若需要则新 ADR） | 未开工 |
| **P.CABI** | 闭源 C ABI（若需要则修订 0018） | 未开工 |

## 明确不宣称

- 第三方插件市场或静默扫描用户目录执行代码  
- 完整沙箱 / 热卸载保证  
- 闭源二进制 Layer 插件 ABI  

## 产品话术

> WellPlot Desktop 首发通过 **声明式 Custom Layer** 与 **SDK/同源嵌入** 扩展；  
> **插件 Runtime** 与 **宿主 Command 审计** 按轨 P 规格分期，见本文档。
