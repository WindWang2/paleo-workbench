# Paleo Workbench 全系统架构审查总览 (System Review)

详见系统架构完整深度审查报告：[system_architecture_analysis.md](file:///c:/Users/wangj.KEVIN/projects/paleo-workbench/docs/audit/system_architecture_analysis.md)

## 核心架构要点

1. **分层清晰的无头服务架构**:
   - `catalog/`: 单写入口、CAS 块存储、不可变版本链。
   - `workflow/`: 8步工序状态推断与单因素插值适配。
   - `mapping/`: 矢量图层、标量栅格、拓扑自愈、Map Composer 排版与双渲染后端。
   - `agent/`: AI 意图解析、DAG 任务图、四大注册表与 8 大专业协同智能体。
   - `native/`: pybind11 C++ 原生计算扩展与对称纯 Python 回退。

2. **多技术栈解耦与对齐**:
   - C++ 高性能计算内核与 Python 业务层通过 `NativeEngineBackend` 统一调度。
   - Qt 桌面端只作为纯展示交互壳层，核心业务逻辑均可在 Headless 无界面环境下完全独立运行。
