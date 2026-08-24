# Paleo Workbench AI GIS Harness 流程深度分析与架构升级方案 (Harness Analysis)

## 1. 当前 AI/Agent 流程诊断与闭环评估

### 1.1 现状与痛点分析
传统地学软件依赖用户手动点击数十个对话框、配置繁琐的算法参数、手动在不同视图间切换并手动导出图件。
在 Paleo Workbench 重构升级前，系统的预测模块主要局限于静态的 `ModelRegistry` 与硬编码的 `DemoModelProvider`，缺乏统一的智能体闭环。

```
[传统模式]: 用户手动点击按钮 ──► 选择固定资产 ──► 运行单一脚本 ──► 手动截图/导出
```

### 1.2 现代 AI GIS Harness 闭环七大能力对照

| 核心能力维度 | 旧版实现状态 | 当前已升级落地实现 | 评估结论 |
|---|---|---|---|
| **1. 意图理解层 (Intent Parsing)** | 无。仅支持固定 UI 点击 | 实现 `IntentParser`，支持自然语言识别地学领域、目标层位（如须家河组）与分析因子（如砂地比）。 | 优秀 |
| **2. 自动任务规划 (DAG Planner)** | 无。工序固定死板 | 实现 `TaskPlanner`，自动生成有向无环图（DAG），解析任务依赖拓扑，支持并行节点发现。 | 优秀 |
| **3. 工具动态选择 (Tool Registry)** | 无。函数硬编码调用 | 实现 `ToolRegistry`，支持类型注解自动推断参数、导出标准 JSON Schema，支持动态执行。 | 优秀 |
| **4. 上下文管理 (Context Manager)** | 局部传递参数字典 | 实现 `HarnessExecutionContext`，在节点间流转资产状态、几何图层快照与中间计算矩阵。 | 良好 |
| **5. 状态机与断点恢复 (State Recovery)** | 依靠 project.json 手动保存 | `TaskGraph` 具备 PENDING/RUNNING/COMPLETED/FAILED 状态机，支持单节点重试与错误捕获。 | 良好 |
| **6. 质检与自愈机制 (Self-Healing)** | 简单的字段缺失提示 | 实现 `QAAgent` 与 `repair_invalid_geometry`，自动闭合多边形、修复拓扑并评估拟合残差。 | 优异 |
| **7. 结果交付与血缘归档 (Delivery)** | 手动点击菜单导出 | 实现 `ResultAgent`，自动包装最终综合报告、记录 DataRun 血缘并生成发布包。 | 优秀 |

---

## 2. 现代 AI GIS Harness 架构体系

```mermaid
graph TD
    User([用户自然语言 / 结构化指令]) --> IntentParser[1. 意图解析器 (IntentParser)]
    IntentParser --> Planner[2. DAG 任务图规划器 (TaskPlanner)]
    
    subgraph Registries ["四大核心注册中心 (Fundamental Registries)"]
        ToolReg["ToolRegistry (原子工具与 JSON Schema)"]
        SkillReg["SkillRegistry (复合业务 SOP 技能)"]
        AlgoReg["AlgorithmRegistry (计算核函数与性能模型)"]
        TemplateReg["TemplateRegistry (制图版式与地质色阶)"]
    end
    
    subgraph Swarm ["3. 协同智能体集群 (Specialized Agent Swarm)"]
        Planner --> DataAgent[Data Agent (数据发现/校验/血缘追踪)]
        DataAgent --> WellAgent[Well Agent (测井曲线对齐/标志层解释)]
        WellAgent --> GISAgent[GIS Agent (断层拓扑提取/空间关系构建)]
        GISAgent --> CartoAgent[Cartography Agent (各向异性IDW插值/等值线生成)]
        CartoAgent --> VizAgent[Visualization Agent (QGIS多图层渲染/地图排版)]
        VizAgent --> QAAgent[QA / QC Agent (拓扑闭合/地质合理性/精度质检)]
    end
    
    Registries -.-> Swarm
    QAAgent -->|质检未通过: 自动触发拓扑自愈与参数微调| Planner
    QAAgent -->|质检通过| ResultAgent[4. 成果交付智能体 (Result Agent)]
    ResultAgent --> Delivery([最终交付物: 报告 + 工程状态 + SVG/PDF 矢量图件])
```

---

## 3. 四大核心注册表深度设计

### 3.1 Tool Registry (`paleo_workbench/agent/registries/tool_registry.py`)
- **功能**: 所有底层原子功能均通过 `@tool_registry.register` 注册，提供强类型参数校验与标准 JSON Schema 导出。
- **已注册核心工具**:
  - `catalog.import_asset`: 数据资产单遍哈希导入与只读放置
  - `well.dtw_correlate`: 井间曲线形态非线性对齐
  - `seismic.extract_slice`: 三维地震正交切片提取
  - `cartography.interpolate_idw`: 断层约束各向异性反距离加权插值
  - `gis.auto_heal_topology`: 空间多边形自相交与未闭合环自动修复
  - `composer.export_layout`: 标准地图版式矢量 SVG/PDF 导出

### 3.2 Skill Registry (`paleo_workbench/agent/registries/skill_registry.py`)
- **功能**: 组合原子工具，形成面向地质任务的高阶业务技能 SOP。
- **典型技能**:
  - `skill.well_correlation_pipeline`: 测井加载 $\rightarrow$ 深度归一 $\rightarrow$ DTW 弯曲 $\rightarrow$ 标志层投影
  - `skill.single_factor_mapping_pipeline`: 井位提取 $\rightarrow$ 断层空间阻隔 $\rightarrow$ 约束 IDW $\rightarrow$ 等值线提取
  - `skill.comprehensive_paleomap_pipeline`: 多因素叠加 $\rightarrow$ 相带划分 $\rightarrow$ 拓扑校验 $\rightarrow$ 模板排版

### 3.3 Algorithm Registry (`paleo_workbench/agent/registries/algorithm_registry.py`)
- **功能**: 维护算法的实现形态（C++ SIMD / OpenMP / Python）、时间/空间复杂度、数据约束与推荐计算规模，供 Planner 智能选型。

### 3.4 Template Registry (`paleo_workbench/agent/registries/template_registry.py`)
- **功能**: 统一管理 A4/A3 标准地质出版图幅、国际地质年表色标、岩性符号图案与连续色带配置。

---

## 4. 下一阶段演进路线图

1. **LLM Function Calling 实时对接**:
   - 对接 DeepSeek / OpenAI / Gemini 大模型 API，将用户对话实时编译为 `ToolRegistry.export_schemas()` 驱动的函数调用链条。
2. **多 Agent 状态断点与持久化存储**:
   - 将 `TaskGraph` 执行快照写入 `.artifacts/metadata/runs/`，支持长时间计算任务的暂停、断点续跑与云端异步调度。
3. **交互式 AI 参数顾问 (AI Parameter Advisor)**:
   - 在前端界面为各算法参数输入框提供“AI 智能推荐”微调按钮，根据工区地质背景自动推断最佳 IDW 搜索半径与断层影响廊道宽度。
