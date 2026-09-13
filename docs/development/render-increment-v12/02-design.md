# 02 — 设计（V12-C）

三个变更单元 + 一个测试矩阵。全部改动落在：
`paleo_workbench/mapping/`（`revision_cache.py` 新增、`map_render_backend.py`、
`layers.py`、`qgis_mirror.py`、`topology.py`）与 `tests/`。

## A. `revision_cache.py` — LatestRevisionCache

```python
class LatestRevisionCache(Generic[Subject, Value]):
    """每主体至多保留一个修订版的缓存。

    命中语义：store(subject, key, value) 之后的 get(subject, key) 返回 value；
    任何不同的 key 都 miss（安全侧：修订未知/漂移 ⇒ 重建，永不服旧值）。
    latest(subject) 不校验修订，专供「旧值作基线」的读者（qgis_mirror
    delta 签名基线）；对渲染侧缓存无此读法。
    """

    def get(self, subject, revision_key) -> Value | None
    def latest(self, subject) -> Value | None          # 不校验修订
    def store(self, subject, revision_key, value)      # 替换同主体任何旧条目
    def subjects(self) -> tuple[Subject, ...]          # prune 用
    def prune(self, keep) -> None                      # 保留 keep 中的主体
    def clear(self) -> None
    def __len__(self) -> int
```

设计要点（DEEPENING：小而深，一处语义）：
- **不含锁、不含计数**：调用方（渲染后端）已有 `_prepared_lock` 与诊断计数；
  cache 保持纯数据结构，避免第二套并发策略。
- **同主体替换式 store**：四处使用方的既有语义（prepared 按 id 覆盖、
  reprojected 存时清同层旧键、signature 同 (stack,layer) 只留一个修订、
  scalar QImage 按 id 覆盖）在「至多一个修订」这一点上同构，归一于此。
- 条目值直接持强引用（含 payload），生命周期由 prune/clear 收口——主体
  从合成中消失 ⇒ 条目随之释放（与 `_prepared` 的 seen_layers 剪除同律）。

### A.1 各迁移点

| 使用方 | 主体 | 修订键 | 读写路径 |
|---|---|---|---|
| `_prepared` | `layer.id` | `int(data_revision)` | `_prepared_layer` 快路径 + 双检插入（锁留在后端） |
| `_reprojected` | `layer.id` | `(int(data_revision), src, dst)` | `_reprojected_prepared` |
| `_scalar_images`（新） | `layer.id` | 见 §B | `_draw_scalar_grid` |
| `_SIGNATURE_CACHE` | `(id(stack), layer_id)` | `int(data_revision)` | `mirror_snapshot_to_stack` 预读（`latest`）+ 发布后 store |

`qgis_mirror` 迁移的行为差异（有意为之，均有测试）：
1. `reset_publish_ledger` 真正清空签名缓存（修复 :392-405 死代码——原意图即如此，
   注释明说 V10/V11「一并清」）。
2. `_SIGNATURE_CACHE` 其余读写语义不变：`latest()` 读旧值作 delta 基线、
   要素数不符作废（长度校验留在 mirror）、发布成功 store 新修订并按 (stack,layer)
   替换旧修订、`keep_keys` 剪除。

## B. 标量栅格 QImage 缓存（`_scalar_images`）

```
_scalar_images: LatestRevisionCache[str, _ScalarImageEntry]

_ScalarImageEntry:
    image: QImage            # .copy() 产物，自有数据
    payload: object          # 强引用；命中还要求 renderer_payload is entry.payload
    width/height: int
```

`_draw_scalar_grid` 新流程：
1. `scalar = layer.renderer_payload`；None/无 `rasterize` → return（不变）。
2. 计算 `key = (int(layer.data_revision), int(layer.style_revision),
   _payload_revision(scalar, "data_revision"), _payload_revision(scalar,
   "style_revision"))`；`_payload_revision` 用 `getattr`，native 层有该属性、
   `_ScalarPayload`（本 Goal 补）有、其余 payload 无 ⇒ None（参与元组比较即可）。
3. 命中且 `entry.payload is scalar` 且尺寸一致 → 直接用 `entry.image`（零拷贝零重算）。
4. 未命中 → `rgba = scalar.rasterize()` → 原 shape 探测/早退路径不变 →
   `QImage(...).copy()` 一次 → `store`。
5. `drawImage(QRectF(...).normalized(), image)`（不变）。

线程：读写都在 `_prepared_lock` 内（worker 线程 `_rasterize_frame_offthread` →
`_paint_composition` → 本方法）。剪除：`_paint_composition` 的 seen_layers 块
加 `self._scalar_images.prune(seen_layers)`；`shutdown()` 清空。

诊断：`_diagnostics` 增 `scalar_cache_hits` / `scalar_cache_misses`（进入
`render_diagnostics()`；`fallback_diagnostics()` 旧键不动）。

`layers.py::_ScalarPayload` 补 `data_revision`/`style_revision` 只读 property。

**等价性论证**：像素字节唯一来源 `rgba`；缓存 QImage 与每帧新建 QImage 字节相同；
`drawImage` 参数（目标矩形、变换提示）不变 ⇒ 逐像素等价。测试：同一场景
「首帧（miss）」与「后续帧（hit）」的 RenderFrame.rgba 逐字节相等；以及数据/
样式变更后帧变化。

## C. 拓扑批量接口（`validate_many` 探针 + 回退）

```python
@staticmethod
def _bridge_validate_many_fn():
    """桥 geometry.validate_many（批量）——不可用返回 None（回退逐要素）。"""
    # 与 _bridge_validate_fn 同源；probe 照 qgis_mirror._stack_supports_delta：
    # inspect.signature 优先（geometries 形参）→ pybind11 __doc__ 首行声明 → None。
```

`validate_records` 新控制流（规则与输出结构逐字不变）：
1. 探测：`bridge_validate`、`bridge_validate_many`、`shapely_ok`（沿用 P2-6 的一次性提升）。
2. 全不可用 → `validator_unavailable`（不变）。
3. 批量可用：收集 `[(record_index, geometry), ...]`（原来会过桥的那类几何，
   保持顺序）；`results = validate_many([g for _, g in items])`；返回非 list 或
   长度不符 → 异常同路：warning 一次 + `bridge_failed = True`，本轮整批让位
   Shapely（与既有「桥路径失败一次即回退」P2-2/P2-6 纪律一致，不做 N 次
   单要素重试）；批量结果按位置回填，issues 顺序与逐要素路径逐字相同。
4. 批量不可用（BASE 真桥即此情形）→ 现行逐要素循环，零行为变化。
5. ring-closure 检查保持原位原序（它不因批量而移动顺序——issues 顺序对齐旧输出
   语义：每记录内 [有效性消息, ring 消息]）。批量路径按下标回填，顺序不变。

探针纪律（mirror 同款）：不缓存探测结果、不调用被探方法、两层信号
（signature → doc）任一命中才启用。

## D. 失效矩阵测试（`tests/test_render_increment_v12.py` 新文件）

| # | 场景 | 操作 | 正向断言 | 反向对照（破坏键后断言陈旧） |
|---|---|---|---|---|
| 1 | 改顶点 | feature geometry 改点 + data_revision+1 | prepared miss+1；帧字节变化 | 键比较恒真 ⇒ 帧字节不变（陈旧）被断言 |
| 2 | 增删要素 | features ±1 + data_revision+1 | 同上；要素计数变化 | 同上 |
| 3 | 改样式（不动几何） | style_revision+1 | 帧**变化**；prepared **零** miss（hits+1） | 破坏 prepared 键 ⇒ miss 计数被压为 0（与正向断言互补） |
| 4 | 可见性/不透明度 | visible/opacity 翻转 | 帧变化；重新可见后 prepared/scalar 仍命中（无 miss） | 跳过剪除 ⇒ 缓存膨胀被断言（len 增长） |
| 5 | 切换图层（文档切换） | 快照换成另一组 layer id | `_prepared`/`_scalar_images` 主体集 == 新集合（旧条目释放） | 破坏 prune ⇒ len 陈旧增长被断言 |
| 6 | 切换 CRS | project_crs 变化 | `_reprojected` 新键；帧变化（pyproj 在场时） | 键退化 ⇒ 旧投影被复用（帧不变）被断言 |
| 7 | undo/redo | 会话 revision + data_revision 回滚 | prepared miss；帧还原为 undo 前字节 | 同 1 |
| 8 | scalar 数据变更 | grid 值变 + revision bump | scalar_cache miss；帧变化 | payload 修订不入键 ⇒ 旧像素被断言 |
| 9 | scalar 样式变更 | set_color_ramp（style bump） | scalar miss；帧变化 | 同 8 |
| 10 | scalar payload 替换 | 同 layer.id 换新 payload 对象 | miss（`is` 校验兜底） | 去掉 `is` 校验且修订相同 ⇒ 陈旧被断言 |

另：镜像侧 `reset_publish_ledger` 真清理（迁移后）+ 签名缓存旧值基线读法回归
（现有 `test_mirror_lifecycle_v11` 全绿即可）+ 拓扑：fake 批量桥 N→1 调用数、
批量/逐要素结果等价、长度不符回退、老桥（无 validate_many）逐要素不变、
真桥（若本机可 import）探针返回不支持。

像素对照采用既有 `RenderFrame.rgba` 逐字节比较（`test_fallback_render_incremental`
同款），不引入新比较器。
