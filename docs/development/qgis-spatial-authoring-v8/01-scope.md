# 01 — Scope（V8 增量定案）

依据 [00-overlap-audit](00-overlap-audit.md)，本 goal 实际交付以下增量（W*），
其余 M 条目按审计裁定为 DROP-AS-DUPLICATE / 决策文档（见 03-decisions）。

| 增量 | 对应 M 条目 | 内容 | 状态 |
|---|---|---|---|
| W1 | M1 | fields_json 在桥端真正落地：typed QgsFields + 约束 + 别名 + 编辑器控件 + 默认值 + GeoJSON properties 的 typed 属性往返（upsert/新层/delta/漂移重建/陈旧清理） | ✅ |
| W2 | M3 | 跨图层拓扑传播的复合撤销组：一次用户级地质动作 = 一次 undo/redo；冲突显式拒绝（拓扑服务 + 双宿主接线） | ✅ |
| W3 | M4 | 第二套 GIS 清理：4 个幸存 PIP、8 个 bbox 构建器、线段距离内核、CRS/修复 facade 旁路、facade 补缺（centroid / bbox_intersects） | ✅ |
| W4 | M5 | 桥通用行指示器 API（state_language 词汇对齐）+ 原生面板投影 | ✅ |
| W5 | M8 | legend `filter_layers` 窄扩展（setSyncMode(Manual) 克隆剪枝，工程本树不动） | ✅ |
| W6 | M9 | 生命周期加固：StackEvents singleShot context 守卫（#951 根因类）+ 30×/100× 压测矩阵 | ✅ |
| W7 | M2/M6/M7/M10 | 决策记录（不加编辑按钮的理由 / perf 无回归验证 / 已交付验证） | ✅（03/06） |

## 明确不做（含理由）

- **100GB seismic**：硬排除，任何形式（详见 PR body）。
- **第二套渲染/树/捕捉/索引**：V7 已交付唯一权威（00 审计）。
- **F7 双网格索引合并**（FeatureQueryIndex vs FeatureSpatialIndex）：
  两者服务不同生命周期（前者 legacy geoviz 编辑场景、后者统一画布工具
  链），合并需同时改动两条已冻结路径的调用面，风险大于 ~200 行重复的
  维护成本；待 legacy geoviz 编辑场景退役时一并删除。见 03-decisions。
- **map_qa_rules 逐点越界判定的 facade 化**：逐坐标热循环里两个比较式
  的函数调用开销不可忽视，且语义（点在 bbox 内）与 bbox_relate 不同；
  保持内联并注释。见 03-decisions。
- **CI workflow 修改**（#1230 的 CI 部分）：goal 明确排除；产品侧的
  stale-QTimer 风险已由 W6 处理。
