# 04 · 已知限制与本期不做清单

状态：Accepted ｜ 诚实边界，防过度承诺。

## 地质/算法边界

1. **三维空间拓扑投影畸变**：构面/共边运算全部在图层 CRS 平面域进行；跨投影（如经纬度图幅跨带）产生的度-米混算畸变不在本期处理（建议宿主先 CRS 变换，crs_chain 已有链路）。
2. **面积无测地修正**：`area` 为平面面积（等距投影下米制）。大区域纬度变形导致的面积偏差不修正——编图面积统计走既有 `area_with_unit` 通道。
3. **曲线类型**：控制线仅支持折线（GeoJSON LineString 语义）；真圆弧/贝塞尔在入库时已折线化（既有 ingest 行为），构面核不做弧段解析。
4. **相律矩阵的确定论简化**：Walther 相律被编码为 8 个内置相的秩差 ≤1 + 白名单对（三角洲↔陆棚、三角洲↔深水盆地——前缘滑塌浊积直邻深水盆地，断陷湖盆常见）。`三角洲↔碳酸盐台地`（混积陆棚场景）保持默认拦截——工程级 `facies_adjacency` 覆盖通道存在；**项目专属相/微相级邻接**同样走覆盖，微相级矩阵本期不做。
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

14. `PwbFaultCutTool` / `PwbBoundaryReshapeTool` 交互手势统一为"折线数字化 + 右键/双击收笔 + Esc 取消"族（共边重塑需先**恰好选中两个相邻面要素**，applier 自动取离曲线中点最近的共享弧——不做自由拖拽式弧拾取）；自由手绘（freehand）模式不做。
15. 重塑的"样条平滑"为 Catmull-Rom 过采样（几何级），非可调参 NURBS。
16. **剥蚀边界的 LayerRole 词条缺失**：词表无 erosion/unconformity 角色，守卫的 `erosion_boundary` 仅经显式 roles 注入（测试覆盖）；工程接入待词表扩展（`_GEOLOGY_ROLE_BY_LAYER_ROLE` 单点补一行即可）。
17. **孔洞近似**（parity xfail 钉死）：框内孤立闭合环围出真孔洞时，原生核以外环近似环形余量（面积=外环），shapely 建模为带孔面——差值恰为内环占据面积；`reshape/find_shared_arcs` 不受影响（仅外环参与）。
18. **守恒检查规模护栏**：`reshape_shared_arc` 的两两段校验上限 4×10⁶ 段对，超限返回 `PWB-GT-001` 拒绝（防 GIL 释放下的无界二次方燃烧）；超大规模重塑请先抽稀。
