# 07 — Review findings

三轮独立 review（goal 要求）。R1 = correctness/regression/GIS semantics；
R2 = architecture/duplication/authority；R3 = UX/performance/adversarial/
lifecycle。R1/R2 由独立 agent 全量审计 diff 并实跑验证；所有 P0/P1 修复
均附回归测试。

## Round 1（correctness / GIS semantics）— 0 P0, 5 P1, 9 P2

| # | 级 | 发现 | 处置 |
|---|---|---|---|
| 1 | P1 | 复合 undo 可从传播层绕过（pending_compound 只认 origin 会话） | ✅ 修复：传播命令为栈顶同样命中 → undo_compound |
| 2 | P1 | 复合 redo UI 不可达（can_redo 只看单层 redo 栈） | ✅ 修复：can_undo/can_redo 复合感知（两处状态源） |
| 3 | P1 | 残余已撤销组吞掉 redo 入口（无单层回退） | ✅ 修复：组拒绝后回退 session.redo() |
| 4 | P1 | facade centroid 洞矩缺失（非对称洞错值；对称洞侥幸对） | ✅ 修复：Σ(A_ext·C_ext − ΣA_hole·C_hole)/Σ净面积 + 非对称洞回归钉 |
| 5 | P1 | QgsLayerTreeViewIndicator 泄漏（removeIndicator 不销毁；每次刷新累积） | ✅ 修复：removeIndicator + deleteLater（行指示器与 ✏ 铅笔两处） |
| 6 | P2 | _geometry_hit 洞内点顶点回退被放宽（39/20000 fuzz 差异） | ✅ 修复：恢复迁移前精确语义（外环内直接返回） |
| 7 | P2 | 手工解析丢弃空要素（OGR 保留）→ fid 配对错位 | ✅ 修复：features 数组成员一律保留 |
| 8 | P2 | 类型不符静默截断/猜值（"3.9"→3、"true"→false） | ✅ 修复：严格类型收窄，不符 → NULL |
| 9 | P2 | applyFieldSchema 等价性忽略 length/precision | ✅ 修复：加入等价判定（漂移即重建） |
| 10 | P2 | discard_compounds 未覆盖全部会话终结路径 | ✅ 修复：discard_ended_session_compounds 统一收口 + 编图页补线 |
| 11 | P2 | merge/split 丢 is_empty 守卫 | 记录：门面 union/split 产空几何时类型过滤拒收；VectorFeature 输入侧已有验证。观察项 |
| 12 | P2 | inclusive 内核 docstring 夸大（cross-product ≠ 距离 epsilon） | ✅ 修正措辞（阈值=面积 epsilon，语义与旧 domain 一致） |
| 13 | P2 | launcher 硬编码本机路径 / sitecustomize 默认开 | ✅ 缺路径时响亮报错（PALEO_QGIS_BUILD_DIR 指引）；bootstrap 仅经 launcher 注入 |
| 14 | P2 | QC 定位点在退化面上从顶点均值变 None | 记录：fail-open（定位缺失不掩盖问题），D3 已声明 |

## Round 2（architecture / duplication / authority）— 1 P0, 2 P1, 7 P2

| # | 级 | 发现 | 处置 |
|---|---|---|---|
| 1 | P0 | **W2 复合组生产路径从未生效**：_commit_vertex 在打开的宏内触发传播回调，登记恒拒绝——真实工具流实测 compound_registered=0、跨层 undo 非原子；测试以直接 set_vertex 绕过了宏 | ✅ 修复：回调移到 end_edit_command 之后（map_tools._commit_vertex）；同层/跨层生产路径回归钉（真实 _commit_vertex 驱动） |
| 2 | P1 | 编图页无 discard 接线；undo 拦截为死代码（因 #1） | ✅ 修复：discard_ended_session_compounds 接入 save_draft/rollback；拦截随 #1 激活 |
| 2b | P1 | D2 文档错误归因（编图页同层原子性来自 V7 宏合并，非复合机制） | ✅ 修正 03-decisions D2 |
| 3 | P2 | 命令"身份制"被 dataclass __eq__ 破坏（== 按值匹配） | ✅ 修复：pop_command/undo_compound 改 `is` 身份索引 |
| 4 | P2 | length/precision 漂移静默不应用 | ✅ 同 R1-9 |
| 5 | P2 | 死代码：_coordinates / _iter_leaf_coordinates / fields_sig 全套 | ✅ 删除（fields_sig 从未被动读——等价性判定才是零抖动来源） |
| 6 | P2 | C++ 侧硬编码 glyph/tooltip/色板（与 tokens.py 无单一真源） | 记录：kinds 词汇 host 权威 + 未知跳过已按 M10 边界；呈现常量漂移风险入 08 观察项（面板 parity 测试可后续钉） |
| 7 | P2 | 残余重复：joint_well_pick._dist_point_to_segment；inclusive 内核自带 crossing 环 | ✅ 前者迁移内核；后者保留（on-edge 循环结构所需，注释声明与 _ray_crosses 的语义关系） |
| 8 | P2 | launcher 默认路径静默 no-op | ✅ 同 R1-13 |
| 9 | P2 | hpp 声称 host handshake 消费（实际暂无） | ✅ 措辞修正（当前消费者=测试，host 接入为后续） |

R2 同时确认：W1 权威边界干净（bridge 只应用不发明；自省=能力事实）；
W5 setSyncMode(Manual)+model()->rootGroup() 是 setCustomLayerTree 私有化
后的公开等价路径，工程本树被测试钉死不变；ui/workstation 冲突面与
00-audit 预告一致（composite_document 未触碰）。

## Round 3（UX / performance / adversarial / lifecycle）— 见 06/08 与最终验证

主 agent 执行：100× 工程切换 / 100× 工具循环 / 30× 树重建 / 指示器共存
循环 / perf 门（附录 06）；对抗面由 R1 的 fuzz（20k 随机点几何）与
R3 的 stress 套件覆盖。发现项已并入上表处置。R3 追加：

| # | 发现 | 处置 |
|---|---|---|
| 1 | topology_conflict 信号无 workstation 生产消费面（"不静默"仅测试成立） | ✅ 接 composite_document.status_message（状态条可见） |
| 2 | 指示器整组替换在每帧装饰刷新时 remove+recreate（视觉抖动风险） | 记录为观察项（16px 图标重绘开销低；kind 集合不变时可后续短路） |
| 3 | 单进程多文件电池受既有 offscreen Qt 污染（V7 已记录） | 分批复跑全绿（05-verification 的批驱动法） |

## 修复验证

全部修复后：W1/W4/W5 qgis-marked、W2 复合组（含生产路径）、W3 内核
parity、W6 stress 套件全绿（05-verification 清单）；受影响回归批次
（composite/authoring kernel/geometry/layout/mapping page）全绿。
