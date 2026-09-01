# Paleo Workbench UI/UX Audit 与信息架构

## 审计范围

本审计基于当前 PySide6 主程序、15 张实际运行截图、`project_area` 真实工程、
`geo-viz-engine`、`well-log-engine`、现有 prototypes、Harness Agent、任务调度器和
现行 light/dark/high-contrast 主题。桌面尺寸覆盖 1180x720、1440x900、DPR 1.25/2.0。

## 结论

现有功能并不薄弱，问题在于功能被组织成 Ribbon 后面的独立模块页。项目对象、
显示文档、图层、参数、后台过程和 Agent 动作缺少共同的交互模型。新版采用项目中心、
多文档、上下文工具和统一过程中心；保留业务服务和渲染引擎，用 Qt 适配器逐步迁移。

## 主要问题

### P0

1. 顶层以数据、井、地震、编图、可视化模块组织，选择上下文不能稳定跨模块传递。
2. Map、Well、Seismic、Section、3D、Plot 没有统一 Document/Workspace 契约。
3. Data Manager 暴露 `meta.json`、`payload.npz` 等缓存，而没有优先呈现地学对象。
4. QC 在没有检查项时可表现为“全通过”，零状态不应授权导出。
5. 长任务散落在页面内，项目切换时缺少统一所有权、进度、取消和结果入口。
6. Agent 的 typed action 能力与 GUI 割裂，执行后不能形成可见工作区事务。
7. OpenGL 页面被提前构造，影响启动、远程显示和自动截图稳定性。

### P1

8. Ribbon、Hub pills、页内 toolbar、canvas toolbar 和侧栏重复提供同类命令。
9. 各模块的左/右面板职责不同，用户不能迁移已有操作习惯。
10. 项目数据与当前文档图层没有清晰区分。
11. Command Palette 实际只跳页，Global Search 实际只过滤一个数据表。
12. 空状态占据大面积中心画布，却不推荐已有工程中的下一步对象。
13. 结果、输入、衍生数据、解释版本、QC 与导出之间的血缘不直观。

### P2

14. 原暖纸/铜色主题与大量带边框容器削弱了科学画布的中性和密度。
15. 1180x720 下 toolbar 截断、表格溢出，空 Inspector 仍占固定宽度。
16. dark theme 中仍有浅色原生子表面和低对比图标。
17. 浮动面板几何没有统一按当前屏幕 availableGeometry 钳制。
18. 对话框、DPI 和导出尺寸缺少统一验证矩阵。

## 应保留的基础

- `SelectionContext`、`CoordinateTransformHub`、`ViewCoordinationController`。
- typed Harness actions、风险权限、校验、回执和任务调度器。
- 项目域模型、数据目录、井/地震/GIS/编图/QC/导出业务逻辑。
- geo-viz-engine 与 well-log-engine 的真实渲染能力。
- 现有 light/dark/high-contrast 主题切换机制。
- 旧页面的自动化测试与确定性 worker teardown。

## 新信息架构

```text
Project
└── Survey / Area
    ├── Data
    │   ├── Well / Well Log
    │   ├── Seismic Volume / Line
    │   ├── Raster / Vector / Table
    │   └── Surface / Horizon / Fault
    ├── Interpretation
    │   ├── Stratigraphy / Correlation
    │   ├── Facies / Attribute / Boundary
    │   └── Scenario / Version
    ├── Visualization
    │   └── Map / Well / Seismic / Section / 3D / Plot
    ├── Result
    │   └── QC / Provenance / Version
    └── Export
```

默认左侧显示地学对象；文件、缓存和 payload 只在高级存储/血缘视图出现。

## Shell 职责

| 区域 | 建议尺寸 | 职责 |
|---|---:|---|
| App Bar | 46px | 工程、全局搜索/命令、任务状态、Agent |
| Activity Rail | 54px | Project、Data、Layers、Search、History、Workspace 模式 |
| Object Explorer | 246px | 工程或数据对象；不混入工具和当前对象参数 |
| Document Host | 剩余空间 | tabs、split、maximize、link selection、lazy view |
| Inspector | 280-360px | 当前对象的属性、解释、样式、历史 |
| Process Hub | 180-280px | Agent、Task、Processing、Logs、Console |
| Status | 26px | CRS、坐标/深度/时间、renderer、link、GPU/错误 |

## Data 与 Layer

- Data Explorer 是 project-scoped，管理持久对象、版本、元数据、校验和血缘。
- Layer Manager 是 document-scoped，管理显示实例、顺序、可见性、样式和范围。
- Data 添加到 Document 后形成 Layer；删除 Layer 不删除 Data。
- 两者使用同一对象 identity，因此选择会更新同一个 Inspector。

## Agent 事务

```text
用户意图
-> 当前 Project/Document/Selection/Extent/Parameters 快照
-> typed action plan
-> 参数、权限和风险校验
-> Task Center 可观察执行
-> GUI transaction
-> 结果验证、回执、撤销/重试
```

当前首批闭环覆盖：显示全部井位、打开指定井、GR 第一轨显示、聚焦井震联合工作区。

## 渐进迁移原则

1. 先建立 Shell、Document Host、Inspector、Process Hub 和 tokens。
2. 旧页面作为“项目工作流”文档继续可达，不做一次性重写。
3. 优先迁移 Data -> Map/Well/Seismic -> Inspector -> Task/Agent 的纵向工作流。
4. 重型 renderer 只在文档可见且平台允许时创建，并由文档统一关闭。
5. 每个迁移批次验证 1180x720、1440x900、DPR 1/1.25/1.5/2、light/dark。
