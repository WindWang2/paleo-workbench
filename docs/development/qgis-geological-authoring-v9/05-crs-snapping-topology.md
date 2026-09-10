# 05 — CRS / snapping / topology（V9）

## 1. CRS 契约（W3）

`paleo_workbench/mapping/crs_contract.py`——单一谓词/解析权威：

| API | 语义 |
|---|---|
| `normalize_crs` | 归一化（委托 `map_render_backend._normalize_crs_name`） |
| `crs_is_geographic` | 轴单位真值（委托 `workflow.crs_policy`；None = 不可验证） |
| `resolve_crs(value, purpose, fallback="")` | `CRSResolution(crs, declared, degraded_reason)`——未声明永远带判词，绝不静默 4326 |
| `crs_axis_unit_metres` | 米制轴判定（诚实比例尺分母的前提） |
| `geod_for_crs` | 地理 CRS → `pyproj.Geod`（椭球轴构造；WGS84 替换记日志） |
| `scale_denominator_from_pixels` | 米制轴才给分母，其余 0.0（诚实未知） |
| `panel_publish_crs` | 面板发布：未声明 → ""（原坐标呈现 + 日志），不伪造 |

**resolution 站点与契约**：

| 站点 | V9 行为 |
|---|---|
| 镜像发布（snapshot/layer CRS） | 声明值直传；度域 extent 不合 → 丢 CRS **+ 诊断**（此前静默） |
| 参考图层导入 | 未声明 → **拒绝** + 判词（此前 `or "EPSG:4326"`） |
| 画布渲染快照（两面板） | `panel_publish_crs`（不伪造） |
| 状态条 | 未声明显示「未声明」 |
| 因子提取 | 记录在案的 legacy fallback（resolve_crs + 降级日志） |
| 测量 | 地理 → Geod 测地米；投影 → 平面地图单位（标注区分） |
| 比例尺事实 | 原生 `canvas_scale`；回退米制推导；否则 0.0 |
| 数字化提交 | 画布 vs 会话层 CRS 可证不同 → fail-closed（auth-id 形态才比对） |

## 2. Snapping（W4）

角色簇 profile + rationale（词表/簇键/应用面见 03-native-authoring §2）。
native 下推链中 per-layer `intersection` 无对应物（整配置 flag）——降级
告警覆盖全局与 per-layer 两态（review-2 P2-3 修复）。

## 3. Topology（W2）

计数缓存（刷新点/会话身份语义见 03-decisions D2 + review-2 P1-2 修复：
缓存条目携带 session 对象身份，新会话不继承旧计数）。QGIS
`topologicalEditing` 随捕捉配置下推（manifest 门控）。compound undo/redo
（V8 M3）不变；undo/redo/几何命令现在是计数刷新点。

## 4. 测试矩阵

- `test_v9_interaction_facts.py`（20）：契约 API、谓词去重、CRS 丢弃诊断。
- `test_v9_snapping_capture.py`（19）：profile 词表 + 对话框 + 控制器注入。
- `test_v9_review_fixes.py`（6）：review 修复回归（含 panel 不伪造断言）。
- `test_qgis_v9_bridge_surface.py`（5，qgis-marked）：真桥 CRS/scale/拓扑键。
