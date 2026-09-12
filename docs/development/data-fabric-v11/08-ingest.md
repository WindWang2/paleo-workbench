# 08 — Batch / Directory Ingest（专业导入计划）

## 1. 流程

```
用户选择目录/多文件
   ↓ 1 scan        递归枚举（可排除模式），文件级 stat+sha（分块）
   ↓ 2 classify    类型探测（复用 import_service/scanner 既有规则）
   ↓ 3 family      文件族检测（shp 族等）→ bundle 候选
   ↓ 4 identity    井名/UWI/调查名抽取（LAS header/DAT/XML/SEG-Y header）
   ↓ 5 match       resolve_well/SurveyRegistry；歧义→unresolved 候选集
   ↓ 6 role        RoleRegistry 推断（类型→角色 + 格式启发）
   ↓ 7 duplicate   对已注册资产（sha/size；external 按 path）
   ↓ 8 plan        IngestPlan（纯数据，可序列化/审查/编辑）
   ↓ 9 用户确认    UI 展示计划：绑定/角色/primary/跳过/合并 bundle
   ↓ 10 execute    catalog batch_save 分块 + 域绑定 + primary 选择
                   可取消（checkpoint 续跑）/幂等重入
```

## 2. IngestPlan 数据模型（`resources/ingest_plan.py`）

```python
@dataclass
class PlannedItem:
    path: Path
    type: str                    # well_log | seismic | well_head | geojson | ...
    format: str
    sha256: str | None
    size_bytes: int | None
    bundle: BundleSuggestion | None     # family 归组建议
    identity: IdentityProposal          # well/survey 候选 + 置信度 + 策略
    role: str
    primary: bool
    duplicate_of: str | None            # 既有 asset/version id
    decision: str = "pending"           # pending|accept|skip|as_new_version

@dataclass
class IngestPlan:
    items: list[PlannedItem]
    issues: list[str]
    unresolved: list[PlannedItem]
```

## 3. 规则

- **不静默猜科学语义**：井名无法可靠匹配 → unresolved + 候选列表
  （复用 resolve_well 的歧义输出）；角色冲突（同文件多角色可能）→ 用户定。
- 同井多 log：全部接受，首个 primary=True（井无该角色资产时），
  已有 primary 的新成员默认 primary=False。
- 重复文件：sha 相同的 managed RAW → 建议 skip（引用既有版本）；
  用户可选 as_new_version（数据可能"同名不同源"）。
- 目录布局提示（`Well-A/A.las + deviation.xlsx + tops.csv`）：目录名仅作
  identity 线索之一（低置信），LAS header 井名优先。
- cancel/resume：execute 按文件分块提交；中断后重跑对已完成项幂等跳过
  （按 path+sha 查已注册）。

## 4. 与现有导入的关系

- 单文件导入（Data Manager 既有路径）内部改走同一 planner（items=1），
  消除第二套导入语义。
- onboarding.analyze_data_folder 保留（向导语义），内部复用 planner 的
  scan/classify/match，输出其既有报告结构。
- seismic 大文件：sha 计算放 worker + 取消点；SEG-Y 只读 header。
