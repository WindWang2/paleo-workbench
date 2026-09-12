# 06 — Typed Lineage / Provenance

## 1. 模型

```python
class RunPort(BaseModel):
    role: str            # 端口语义角色：sonic / density / time_depth / normalized_log / ...
    version_id: str
    ordinal: int = 0     # 同角色多输入时的顺序
    required: bool = True
    entity_type: str = ""   # 可选实体上下文（well 等）
    entity_id: str = ""
    note: str = ""

class DataRun(BaseModel):
    ...
    input_ports: list[RunPort] = []
    output_ports: list[RunPort] = []
```

不变式（单一写入口 `service.set_run_ports` / 注册时直接构造）：
`{p.version_id for p in input_ports} ⊆ set(input_version_ids)`；扁平列表
在 ports 设置时自动并集补齐。旧数据（无 ports）完全合法。

## 2. 端点角色词表

`catalog/port_roles.py`：常见端点角色注册（`sonic/density/gamma/time_depth/
tops/trajectory/seismic_volume/horizon/constraints/model/normalized_log/
prediction/factor_grid/map_product/...`）。**开放词表**：未知角色原样保留，
查询按字符串匹配；每个注册项带 display 与默认 required。业务模块用常量
引用避免拼写漂移。

## 3. 存储

表 `run_ports`（run_id, direction, role, version_id, ordinal, required,
entity_type, entity_id, note；PK (run_id, direction, version_id, role, ordinal)）。
接入点与 04 §3 相同模式（apply_changes runs 循环、rebuild、load、reconcile）。

## 4. 查询 API

- `inputs_by_role(version_ref or run_id, role)` → 有序端口绑定。
- `runs_consuming(role=…, version_id=…)`。
- `lineage_chain` 扩展节点携带端口注解（该边由什么角色驱动）。
- DependencyGraph（workflow/dependency_graph.py）从 ports 增强：
  `edge_role(source, target)` → 最近一条 run 的端口角色。

## 5. 迁移与兼容

- 旧 run 无 ports：查询面按 `input`/`output` 匿名角色降级 —— typed 能力
  对旧数据"逐步变准"，永不失真。
- `migrate_run_ports()`（打开时一次性、确定性、幂等）：对已知 operation
  词表（prediction/factor_interpolation/factor_fusion/map_compile/
  td_calibration/stratigraphic_correlation）用启发规则补端口标注
  （例如 prediction run 的 well_log 输入 → role=well_logs）。规则只使用
  已有元数据（parameters 中的键），不猜科学语义；无法确定的保持匿名。

## 6. 工作流接入（strangler 顺序）

lifecycle.py 各 helper 增加 ports 参数并逐步由各业务模块传入：
1. prediction（inputs: well_logs/seismic_volume; outputs: prediction）
2. factor_interpolation / factor_fusion
3. td_calibration（inputs: checkshot 等; outputs: time_depth）
4. stratigraphic_correlation（inputs: tops 多井; outputs: correlation）
5. map_compile / map_product
6. qc / export / modeling
