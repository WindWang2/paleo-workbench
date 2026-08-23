# Paleo Workbench AI Harness 深度审查与升级方案 (Harness Review)

## 1. 当前 AI/Agent 流程诊断与闭环评估

### 1.1 现状审查
当前 Paleo Workbench 在 `paleo_workbench/prediction/` 模块中实现了 `ModelRegistry` 与 `InferenceService`，但其设计本质上是针对传统启发式/统计预测模型（如 `DemoModelProvider` 和 `LocalAssetProvider`）的批处理执行器。

```
[用户输入] ───(当前为固定按钮点击)───> [选择硬编码任务] ───> [调度固定 Provider] ───> [生成固定 DERIVED 资产]
```

### 1.2 闭环缺口分析 (Gaps)

1. **意图理解层缺失 (Intent Understanding Gap)**:
   - 系统无法解析自然语言或复杂领域指令（例如：“分析川西凹陷须家河组各井砂岩厚度空间展布并生成单因素图” 或 “提取第3口井至第8口井连井剖面并在标志层拉平”）。
   - 无法自动识别任务类型（GIS 分析、测井解释、地震切片、古地理制图）、无法自动分析数据依赖前置条件。

2. **四大注册中心割裂 (Registry Fragmentation)**:
   - 缺乏全局的 **Tool Registry**（工具注册表）：各种算法（如 `DTWLogMatcher`、`fast_slice_extract`、`generate_constrained_idw`）散落在不同文件中，缺乏统一的 Schema、参数校验与可执行接口。
   - 缺乏 **Skill Registry**（技能注册表）：高阶业务流程（如“自动层序格架对比流程”、“断层遮挡单因素图生成流程”）未被封装为复合技能。
   - 缺乏 **Algorithm Registry**（算法注册表）：原生 C++ 与纯 Python 算法未通过统一的元数据标准对外发布。
   - 缺乏 **Template Registry**（模板注册表）：地图整饰模板、图例样式配置与色标方案缺乏统一注册索引。

3. **缺乏自主多 Agent 协作网络 (Multi-Agent Swarm Missing)**:
   - 目前没有 Task Graph 编排器，无法将复杂的地质综合任务分解为多 Agent 并行或串行子任务，无法实现数据验证→计算→制图→质检的自闭环纠错。

---

## 2. 智能化闭环场景推演与能力要求

以典型地质/GIS 任务为例：
> **用户指令**: *“基于工区内所有测井数据，自动对齐须家河组一段顶界，计算各井砂地比，结合断层多边形生成各向异性单因素砂体分布图，并输出带标准图例与指北针的成果图件。”*

理想 AI GIS Harness 的全自动执行流程应为：

```mermaid
graph TD
    User([用户自然语言 / 结构化指令]) --> IntentParser[1. 意图解析器 (User Intent Parser)]
    IntentParser --> Planner[2. 任务图规划器 (Task Graph Planner)]
    
    subgraph Swarm ["3. 协同智能体集群 (Specialized Agent Swarm)"]
        Planner --> DataAgent[Data Agent (数据发现/校验/血缘追踪)]
        DataAgent --> WellAgent[Well Agent (测井曲线对齐/标志层解释)]
        WellAgent --> GISAgent[GIS Agent (断层拓扑提取/空间关系构建)]
        GISAgent --> CartoAgent[Cartography Agent (各向异性IDW插值/等值线生成)]
        CartoAgent --> VizAgent[Visualization Agent (QGIS多图层渲染/地图排版)]
        VizAgent --> QAAgent[QA / QC Agent (拓扑闭合/地质合理性/精度质检)]
    end
    
    QAAgent -->|质检未通过: 自动微调参数| Planner
    QAAgent -->|质检通过| ResultAgent[4. 成果交付智能体 (Result Agent)]
    ResultAgent --> Delivery([最终成果交付: 项目保存 + 报告 + 导出 SVG/PDF/GeoTIFF])
```

---

## 3. 四大核心注册表架构设计 (The 4 Fundamental Registries)

### 3.1 Tool Registry (工具注册表)
所有底层可调用原子能力通过强类型、自动生成 JSON Schema 的装饰器 `@register_tool` 注册：
- `catalog.import_asset`
- `well.dtw_correlate`
- `well.flatten_datum`
- `seismic.extract_slice`
- `seismic.compute_coherence`
- `single_factor.generate_constrained_idw`
- `gis.validate_topology`
- `gis.build_buffer`
- `mapping.compose_layout`
- `mapping.export_map`

### 3.2 Skill Registry (技能注册表)
将多个原子 Tool 组合为可重用的复合技能脚本与 SOP：
- `skill.well_correlation_pipeline`: 测井数据加载 → 深度归一化 → DTW 自动对比 → 标志层生成
- `skill.single_factor_mapping_pipeline`: 井位提取 → 断层空间遮挡 → 约束 IDW 插值 → 自动平滑 → 等值线追踪
- `skill.comprehensive_paleomap_pipeline`: 多因素叠加 → 岩相多边形拓扑生成 → 编图排版

### 3.3 Algorithm Registry (算法注册表)
记录算法名称、实现版本（C++ SIMD / Python Fallback / OpenMP / GPU）、时间与内存复杂度、支持的数据维度、输入输出约束。

### 3.4 Template Registry (模板注册表)
集中管理地图版式模板（A3/A4 横向/纵向、标准地学图件边框、比例尺样式、国际地质年表色标表、标准测井道模板）。

---

## 4. Paleo AI GIS Harness 架构与代码改造方案

在 `paleo_workbench/agent/` 目录下构建工业级 AI Harness 核心：

```
paleo_workbench/agent/
├── __init__.py
├── harness.py               # 核心 Harness 入口与执行引擎
├── intent.py                # 意图理解与语义解析器
├── planner.py               # DAG 任务图生成与状态追踪器
├── registries/
│   ├── __init__.py
│   ├── tool_registry.py     # 工具注册中心 (ToolRegistry)
│   ├── skill_registry.py    # 技能注册中心 (SkillRegistry)
│   ├── algorithm_registry.py# 算法注册中心 (AlgorithmRegistry)
│   └── template_registry.py # 模板注册中心 (TemplateRegistry)
├── agents/
│   ├── __init__.py
│   ├── base.py              # Agent 基类与通讯协议
│   ├── data_agent.py        # 数据治理与发现 Agent
│   ├── well_agent.py        # 测井地质 Agent
│   ├── seismic_agent.py     # 地震解译 Agent
│   ├── gis_agent.py         # 空间分析与拓扑 Agent
│   ├── carto_agent.py       # 单因素与综合制图 Agent
│   ├── viz_agent.py         # 可视化与排版 Agent
│   ├── qa_agent.py          # 成果质检与自愈 Agent
│   └── result_agent.py      # 报告生成与交付 Agent
└── tools/
    ├── __init__.py
    ├── catalog_tools.py
    ├── well_tools.py
    ├── seismic_tools.py
    ├── single_factor_tools.py
    ├── topology_tools.py
    └── mapping_tools.py
```

---

## 5. 改造落地收益

1. **实现自然语言与高阶工作流闭环**: 无论是桌面端 AI 对话悬浮窗还是无头脚本，均可通过统一 Harness 完成端到端复杂分析。
2. **彻底解耦 UI 与底层业务**: UI 成为 Harness 的一个交互视图，支持自动化批量处理与离线云端执行。
3. **自愈式质检闭环**: QA Agent 可根据拓扑合规性检测与地质残差指标，自动反馈修正插值参数与断层容差，大幅减少人工干预。
