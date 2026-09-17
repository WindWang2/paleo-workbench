# C++ 默认入口切换评审（M5，转换计划收口文档）

日期：2026-09-17。范围：是否/如何把桌面产品默认入口从 Python 主程序
（`pyproject.toml` 的 `paleo_workbench`）切换到 C++ 平台
（`pwb-platform`）。本文只提供决策材料，不做切换。

## 1. 就绪证据（Linux，integrated 门禁）

门禁：`scripts/cpp-migration/run-integrated-gate.sh`（configure+build+
ctest×2+MALLOC 审计），当前 **48/48 ×2 + MALLOC 14/14**。

已全程原生 C++ 且对冻结 oracle 验证的用户流程：

| 流程 | 证据 |
|---|---|
| 新建工程（文档工厂+空 catalog+bootstrap 资产） | `platform.project_session` |
| 打开 .paleo（恢复+工作副本+绑定物化） | `platform.project_session`（payload 不可变哈希证明） |
| 编辑→保存（stage→B 事务→finalize、幂等/乐观锁/失败语义） | `platform.adapters_substitutes` + `integration.project_chain` |
| 导入真实 SEG-Y（IEEE/IBM、严格网格） | `seismic_io.segy_read`（与 geoviz oracle 逐样本一致） |
| 属性计算→发布→重开读回 | `integration.attribute_chain` + `platform.attribute_ui`（与 expected_rms_w21 对账 <1e-5） |
| 体版本切片浏览（D）/ 测井 LAS（C-WLE） | `platform.attribute_ui` / qgis_smoke_app |
| catalog.json checkpoint（跨栈交换清单） | `data.manifest_export` |
| 部署级冒烟（含以上 M1-M3 链） | `pwb-platform --self-check`（env -i 可跑） |

## 2. 硬阻塞（切换默认前必须完成）

1. **Windows 全链回归**：本项目双平台交付（MSVC/Qt 6.8 预设仍在），
   C++ 侧 Windows 构建自 v3 后无机器验证。需外部环境执行
   `run-integrated-gate.sh` 的 Windows 等价物。
2. **安装包正式化**：现有部署树+自检是开发机形态；需要正式安装包
   （含 Qt/QGIS vendor 运行时闭包）与干净机器验证。
3. **长稳/性能 soak**：500-cycle、sanitizer 轮次未执行（验证文档 §6
   一直如实记录）。

## 3. 切换方案（建议）

- **不建议**直接改 `pyproject.toml` 默认入口。
- **建议**增量曝光：发布一个并行启动器（如 `paleo-cpp`，包装
  `pwb-platform` 与 vendor 运行时路径），Linux 用户可选用；Python 主程
  序保持默认，直至 §2 三项清零后再评审默认切换。
- 回滚成本为零：切换仅是启动器层面，Python 产品在转换期内持续可用。

## 4. 遗留（不阻塞切换评审，按需推进）

- models/model_versions 领域读模型（fixtures 无数据；manifest 已透传
  不丢内容）。
- B 深层功能：GC/dedup、entity view/分页、通用多产物事务。
- 井间/三维渲染、多视图联动（后续版本范围）。
