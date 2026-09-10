# 09 — Known limitations（V9）

1. **桥 `canvas_destination_crs` 在本 worktree 配方下常返回 ""**：vendored
   build 无 proj.db（PROJ 数据不在 loader 环境里），QGIS 侧 CRS 无法解析
   → 诚实空串。数字化 CRS 守卫按「未知不比对」处理——守卫在本配方下
   不产生假失败，但在 proj 数据齐备的环境（CI qgis 腿/conda 配方）才
   真正生效。这是运行时配方约束（同 V8 osgeo 限制家族）。
2. **测地 fallback 与原生椭球语义的理论级差**（review-1 P2-1）：fallback
   在椭球不可解析时替换 WGS84（记日志）；原生 PwbMeasureTool 依赖
   QgsProject ellipsoid（QGIS 3.x 默认非空）。两路径在默认工程下等价。
3. **测量工具使用工程 CRS 而非画布目标 CRS**（review-1 P2-8）：镜像降级
   丢目标 CRS 的边角场景下，fallback 采点轨的测地标注可能对错 CRS。
   守卫（W7）会拦截提交但测量读数不受守卫保护——后续把 shim 路由坐标
   的 CRS 语义与 `canvas_destination_crs` 对齐。
4. **行级「按角色推荐」改全局模式框**（review-1 P2-7）：per-row 单元格
   无法表达 endpoint/midpoint/intersection（accept 的单写径语义），推荐
   应用因此有工程级模式副作用（推荐语明示，用户可改）。全保真 per-layer
   模式编辑留给后续对话框扩展。
5. **属性表对话框打开期间角色/列结构变化不主动重建列**（review-1
   P2-4）：差量刷新保持列结构；角色变化经下一次全量 refresh 收敛
   （瞬时对话框，有界陈旧）。
6. **`_capture_layer_crs_provider` 为 bound-method 强引用**（review-1
   P2-3）：与 `_tool_controller` 同形态（宿主→画布单向、shutdown 守卫
   先行）。显式 `detach_canvas` 留给后续清理批次。
7. **QgsDualView 全托管未做**（03-decisions D3）：属性表是 QGIS provider
   schema 的事实消费者（编辑器/约束/parity），不是 QGIS 表格部件的宿主。
   表单视图/表达式过滤/列拖拽不在本批。
8. **存量 quiet-4326 数据类默认值保留**：`layers.py`/pipeline models/
   `project/models.py` 的 dataclass 默认值是 wire 兼容面——消费点已经
   契约化（未声明有判词），但默认值本身未改（改默认会动持久化兼容）。
9. **同机环境性测试失败（3 项）**：gil-contract 顺序依赖、layer-panel-menu
   teardown 悬空菜单、mirror-publish 50 层首发预算——三项在 V8 基线
   worktree 同机对照同样失败（08 §3），CI 覆盖。
10. **100GB seismic**：零接触（无支持/基准/优化/体数据路径改动）。
