# 05 — Test Plan（V14-COMPILATION-PUBLISH）

所有测试本地可复现。构建配置：`linux-ninja` preset（Release）+ `PWB_BUILD_CPP_CLOSE_02=ON` + `PWB_BUILD_CONV_17=ON`（closure_workflow 电池需要），资源门 `-j2`。

## 测试矩阵

| 类别 | 测试 | 覆盖 | 结果 |
|---|---|---|---|
| oracle/parity | `mapping_document.composer_oracle` | 63 渲染用例（全部元素类型/8 图表/dict-layer 5 种渲染器/占位/转义/裁剪）+ 20 模板文档 + 2 导出用例 + 模板库逐字段 + 实例化 + 未知 id 拒绝 + 确定性 id | **1351/1351** |
| oracle/parity | `tools/oracle/generate_composer_fixtures.py --check` | fixture 与冻结 Python 参考同步 | 通过（两次生成 byte 一致） |
| kernel negative | `mapping_document.composer_scale` | 100/1000 元素线性、100 图例线性、50 元素 <1s、模板实例化成本、唯一/定形 id、渲染确定性、像素预算拒绝/接受、unsupported 格式拒绝 | **30/30** |
| fusion 生产路径 | `closure_workflow.grid_seams` | decode round-trip（NaN/方差/溯源）、拒绝（非 JSON/非对象/错 kind/ragged/坏 cell/缺轴/零宽/null catalog/非网格 payload）、catalog pin 装载、current-from-catalog、bare task 拒绝、完整融合（freeze→pin→fuse→register→run complete→artifact 可解码→几何保持）、missing pin 拒绝、no-catalog 诚实 | **22/22** |
| provenance | `closure_review.provenance_sink` | 无 registrar → false；失败 registrar → false；成功 → true + run id（含 stored report）；抛异常不冒泡；`ProjectReviewActions` 端到端 | **5/5** |
| 回归 | `closure_workflow.{fusion,map_product,e2e,resolve}` | 既有 oracle 回放与验收环 | 14/24/49/… 全过 |
| 平台 | `platform.closure_mapping` | 模板库 9 项、模板开档（非空白 A4）、预览真实渲染（无失败文案）、headless 导出真实 SVG（mm 锚点/完整性） | 通过 |
| 平台 | `platform.closure_review_install` | review install 接线 | 通过 |
| UI | `ui_seqviz.{core_state,qt_widgets_smoke,composition_panel}` | 面板视图核心 | 通过 |
| 回归 | `cartography.*`（8） | 色带/样式/模板 oracle | 通过 |
| 回归 | `mapping_document.{roundtrip,edit_session,bridge_session}` | CONV-02/27/27d | 通过 |

## 负面/失败路径覆盖（Prompt 要求）

| 场景 | 覆盖处 |
|---|---|
| stale input（pin 失效） | `grid_seams`：fusion.missing_pin_refuses + grid_for_task stale-pin 拒绝 |
| missing factor / source | fusion_test（既有）+ grid_seams decode 拒绝 |
| export disk failure | `composer_export` 原子写失败路径 + readback 失败（文档化；真实磁盘故障由 store 契约承接） |
| invalid template | oracle：unknown template id → invalid_argument |
| cancelled export | 导出同步路径无取消点（记录为已知限制；画布导出的取消检查点由 `map_export_worker` 提供，非本线路径） |
| layout renderer unavailable | install 编排：QGIS seam 缺席 → composer 引擎；replay 缺席 → ok=false |
| source layer removed | 融合：目录版本不可解析 → 拒绝 |
| QA blocker | `map_product` 既有 publish 门禁测试（回归） |
| stale async preview | install 帧缓存 TTL 300ms（画布 repaint 在 TTL 内可见）；已知限制登记 |

## 未覆盖（登记）
- 真机 QGIS 执行器路径（`platform.composition_export` 已有覆盖；本线的 install seam 绑定未在平台测试中注入 executor——需要活 MapSession）。
- Windows/macOS（本机 Linux only）。
- ASan/UBSan（未跑：构建时间与资源约束；记录为后续）。
