# Example Capability Providers (Harness 2.0)

两个遵循 Provider Contract V2 的第三方扩展示例。它们不进 `paleo_workbench/`
包体，按 ADR 0065 的注册模型接入：**显式注册**（默认）或 **entry-point 发现**
（opt-in，`PALEO_PROVIDER_ENTRY_POINTS=1`）。没有目录扫描。

| provider | family | 真实接口 | 说明 |
|---|---|---|---|
| `geology.factor_stats` | interpolation | `GeologicalFactorDataset.valid_points`（mapping 管线真实产出） | 纯计算：因子统计摘要 → JSON 报告工件（run 绑定时登记 INTERMEDIATE） |
| `export.map_thumbnail` | exporter | `FallbackMapRenderBackend`（snapshot-in/frame-out 生产渲染 seam） | 渲染导出：MapDocument → 工作区内 PNG（#1177 包含检查） |

两者都实现 V2 的 `verify` 钩子（fail-closed）：统计报告的 mean 必须落在
[min, max]；导出文件必须是真实非空 PNG。descriptor 带数字版本和
`build_identity`，可进 receipt 与复现说明。

## 显式注册

```python
from paleo_workbench.providers import get_provider_registry
from geology_factor_stats import FactorStatsProvider
from export_map_thumbnail import MapThumbnailProvider

registry = get_provider_registry()
registry.register(FactorStatsProvider())
registry.register(MapThumbnailProvider())
```

## Entry-point 声明（分发场景）

```toml
# pyproject.toml
[project.entry-points."paleo_workbench.providers"]
factor_stats = "geology_factor_stats:FactorStatsProvider"
map_thumbnail = "export_map_thumbnail:MapThumbnailProvider"
```

启动前 `export PALEO_PROVIDER_ENTRY_POINTS=1`。注册失败的插件进入
quarantine（可查、不阻断应用启动）。

## 测试

`tests/test_provider_examples.py` 用真实数据集/真实文档执行两个 provider，
并覆盖 verifier 的拒绝路径。
