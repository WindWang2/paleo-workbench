# 03 — Entity–Asset Model（井/调查多资产关系产品化）

## 1. Role Registry（`project/roles.py`）

```python
@dataclass(frozen=True)
class RoleDefinition:
    role: str
    entity_types: tuple[str, ...]        # ("well",) / ("seismic_survey",) / ...
    cardinality: str                     # "0..1" | "0..N"
    primary_policy: str                  # "none" | "optional" | "required_single"
    ordered: bool = False                # 成员是否有业务顺序（ordinal）
    display: str = ""                    # UI 中文名
    stage_default: str = "raw"           # 该角色源数据通常的 lifecycle stage
    description: str = ""
```

井角色（在既有 WELL_ROLES 基础上补 `core`、`qc`）：

| role | cardinality | primary_policy | 说明 |
|---|---|---|---|
| well_head | 0..N | required_single | 井位/井史主记录；多文件时一 primary |
| well_log | 0..N | optional | 多 LAS/DLIS 并存；primary 可选标记偏好曲线集 |
| trajectory | 0..N | optional | 井斜；primary=当前生效，其余 historical |
| tops | 0..N | optional | 分层顶；多版本并存 |
| time_depth | 0..N | required_single | 时深；primary=active 版本 |
| core | 0..N | optional | 岩心 |
| interpretation | 0..N | none | 解释成果（多解释方案并存） |
| qc | 0..N | none | QC 报告附件 |
| other | 0..N | none | 兜底 |

调查角色（SURVEY_ROLES 不变 + 语义表）：seismic_volume（required_single）、
geometry/velocity/horizon/fault/interpretation/other（0..N）。

`WELL_ROLES`/`SURVEY_ROLES` 改为从 registry 派生的 tuple（顺序保持原值 —— 
`other` 永远最后），`project/domain.py` re-export，既有 import 不破坏。

## 2. Link 扩展

`EntityAssetLink` 增加 `ordinal: int = 0`（角色内有序成员，如多 LAS 的
加载顺序）。primary 语义保持：同 (entity, role) 至多一个 primary
（`_demote_sibling_primaries` 已保证）。active 版本 = primary 资产的
`current_version_id`；历史版本 = 该资产其余版本 + 非 primary 资产的全部版本。

## 3. WellDataView / SurveyDataView（`catalog/entity_views.py`）

```python
@dataclass
class RoleSlot:
    role: str
    primary: AssetSummary | None        # primary 资产 + 其 current 版本
    members: list[AssetSummary]         # 含 primary，按 (ordinal, name) 稳定排序
    unresolved: list[AssetSummary]      # unresolved=True 的链接

@dataclass
class WellDataView:
    well: WellEntity
    slots: dict[str, RoleSlot]          # 按 RoleRegistry 全角色展开（空角色也占位）
    derived_products: list[VersionRefLite]   # 从该井任意源版本下游闭包（LIMIT 受控）
    stale_products: list[StaleItem]
    missing_sources: list[AssetSummary]      # find_missing_sources 的井内子集
    uncommitted_edits: list[WorkingCopyLite] # 该井源版本的 live working copies
    related_runs: list[RunRefLite]           # 井内版本参与的 runs（受控窗口）
```

查询代价约束：单井视图 = links 过滤（内存）+ ≤ 角色数×成员数 次点查
（`get_asset_models` 批量）+ 下游闭包走 impact 服务（带界深广度）。
**不触碰 list_assets() 全量**。

`EntityViewService`：
- `well_view(well_id)` / `survey_view(survey_id)` / `entity_view(entity_id)`
- `well_index()` —— 轻量井摘要列表（名/井号/角色填充计数/stale 计数），
  供树根节点（一次组装 O(W×平均link)）。
- `unassigned_assets_page(...)` —— 无任何 link 的资产分页（树中"未分配"桶）。
- 井列表本身来自 `project.wells`（≤10k），不查 catalog。

## 4. 绑定管线增强

`bind_well_extracts`：井日志角色多文件 —— 每个 LAS 资产独立 link
（role=well_log），不再假设一井一 LAS；ordinal 按导入确认顺序分配。
ingest plan（08）负责 primary 建议：同角色第二个及以后成员默认
primary=False，用户可改。
