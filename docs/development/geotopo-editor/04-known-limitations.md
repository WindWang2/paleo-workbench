# 04 · 已知限制与本期不做清单

状态：Accepted ｜ 诚实边界，防过度承诺。

## 地质/算法边界

1. **三维空间拓扑投影畸变**：构面/共边运算全部在图层 CRS 平面域进行；跨投影（如经纬度图幅跨带）产生的度-米混算畸变不在本期处理（建议宿主先 CRS 变换，crs_chain 已有链路）。
2. **面积无测地修正**：`area` 为平面面积（等距投影下米制）。大区域纬度变形导致的面积偏差不修正——编图面积统计走既有 `area_with_unit` 通道。
3. **曲线类型**：控制线仅支持折线（GeoJSON LineString 语义）；真圆弧/贝塞尔在入库时已折线化（既有 ingest 行为），构面核不做弧段解析。
4. **相律矩阵的确定论简化**：Walther 相律被编码为 8 个内置相的秩差 ≤1 + 白名单对。真实盆地中浊积舌/滑塌体可使"三角洲前缘-深水盆地"直邻（已入白名单），但**项目专属相/微相级邻接**需项目级 `facies_adjacency` 覆盖——微相级矩阵本期不做。
5. **断裂标记语义**：`fault_bounded` 只标记"被该次截断操作触及"；不做走滑/逆冲几何样式区分。`fault_side` 基于首末向量叉积，闭合/近闭合断层曲线 side 判定无意义（返回空）。
6. **补偿性提交恢复的 fid 不稳定**：commit_all 中途失败后的补偿恢复保证几何/属性内容等价，但 QGIS 内存层新增要素 fid 与失败前可能不同（D9 已记录）。宿主层 `__pwb_fid` 稳定，用户不可感知。
7. **共边重塑的弧匹配**：`reshape_shared_arc` 要求弧在容差内**唯一匹配**双侧环；两侧环已各自偏移（数据脏）时返回 `PWB-GT-201` 拒绝而非自动吸附修复。
8. **多部件面 (multipart)**：构面输出恒为单部件；断层截断对 multipart 面按 QGIS splitFeatures 原生行为处理（可能产出 multipart 残件），不额外拆分。

## 工程边界

9. **性能门禁的机器相关性**：30 ms/5000 段基于本机 Release x64 单核预算；CI 慢机性能测试用 `capacity` 标记隔离，预算断言仅在本仓开发机腿强制。
10. **无 pyd 环境的功能面**：`geotopo_service` 提供构面/共边 fallback（shapely），但断层截断与镜像层重塑是编辑缓冲原生能力——无桥环境仅能校验（Ticket 4 全可用）与离线构面，不能交互截断（返回 `(False, "requires native bridge")`）。
11. **capability_manifest 不新增**：新能力经 `hasattr(bridge,"geotopo")` 探测；manifest 钉测保持零改动（ABI 承诺 §5）。
12. **版本号漂移不修**：bindings `__version__=0.11.0a0` vs setup.py `0.7.0a0` 的既有漂移不属于本任务（记录于 D10）。
13. **undo 深度**：手势级 undo 依赖 QGIS 每 `QgsVectorLayer` 的 undoStack（默认 200 步）；超深撤销截断由 QGIS 行为决定，不自行扩栈。

## 交互边界（本期工具面最小化）

14. `PwbFaultCutTool` / `PwbBoundaryReshapeTool` 交互手势为"折线数字化 + 双击/右键收笔"与"点选弧 + 拖拽重塑"两族；自由手绘（freehand）模式不做。
15. 重塑的"样条平滑"为 Catmull-Rom 过采样（几何级），非可调参 NURBS。
