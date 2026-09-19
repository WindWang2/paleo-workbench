# 06 — acceptance（能力四列清单 + 验收门）

## 能力清单（implemented / merged / wired / verified）

| 能力 | implemented | merged(main) | wired(产品链) | verified(本线证据) |
|---|---|---|---|---|
| joint 核 11 组件（survey/registration/fence/probe/TD/…） | ✔ (C线) | ✔ | ✔（host 已注入产品 shell） | C 线 oracle 9/9 + 本线 6/6 |
| VizCJointHost 真实 host（open_volume 走 JobCenter） | ✔ (C线) | ✔ | ✘（shell 用 stub） | C 线示例 |
| shell 页面注入真实 host（替换 UnavailableJointHost） | 本线 R1 | – | 本线 R1 | 本线 |
| pwb_job_center property 错位修复 | 本线 R1 | – | 本线 R1 | 本线 |
| 时间平面切片异步（prepared-slice 走 JobCenter） | 本线 R2 | – | 本线 R2 | 本线（测试+示例） |
| 3D 帘幕/切片 mesh worker 化（快速切片不阻塞） | 本线 R2 | – | 本线 R2 | 本线（测试+示例） |
| 多 fence 同时渲染 + 管理（激活/删除/可见性） | 本线 R3 | – | 本线 R3 | 本线 |
| 状态保存重开 + 工程身份键 | 本线 R1/R4 | – | 本线 R4 | 本线 roundtrip 测试 |
| readiness_inputs 锁定投影读 | 本线 R4 | – | 本线 R4 | 本线 |
| 坐标/单位说明 | 本线 R4 | – | 本线 R4 | 本线 |
| GL 双路径证据（软件 GL / 无 GL 降级） | – | – | – | 本线示例运行 |

## 验收门

1. 最小回归：geo3d + viz_c + platform 受影响集 ×2 全绿（预存失败 F7 除外，逐条对账）。
2. 示例 offscreen（无 GL 诚实降级证据）+ Wayland llvmpipe（软件 GL 截图+关键像素）双路径 exit 0。
3. 快速切片/取消/销毁：异步 generation 守卫测试（迟到结果丢弃、无 UAF、无越界）。
4. 工程身份：状态键随工程切换隔离（roundtrip 测试断言不串）。
5. 无 GPU/无数据：诚实占位路径测试不断言崩溃/假成功。
6. MALLOC_CHECK_=3 跑 viz_c+platform 受影响面。

## 验证证据（2026-09-20 收口，含审查修复后复验）

- 构建：native-product 全闭包（PLATFORM+DATA+SCIENCE+GEO3D_VIZ+SEISMIC_IO+
  SEISMIC_SERVICE+SEISMIC_VIEWER+INTEGRATION_TESTS），0 error。
- 受影响回归 ×2（viz_c/geo3d/data./ui_wellseis/platform./seismic_service/
  integration 共 67 项）：66/67 ×2；唯一失败 integration.attribute_chain =
  C 线 ledger 记录的预存失败（origin/main 同败，断言过期，归 D/属性线）。
- viz_c.joint3d_closure（本线新测试）6/6 ×5 连跑 + ×2 轮，全程 MALLOC_CHECK_=3。
- GL 双路径：xcb 真实 GL 截图 800×600（43 distinct colors、地震蓝红 699、
  井黄 168 采样像素）；offscreen 无 GL 诚实降级 15/15 exit 0。
  Wayland 合成器缺失（环境限制）→ 软 GL 证据以 xcb+llvmpipe 直渲染替代记录。
- 快速切片/取消/销毁：rapid_slice_changes_converge_without_blocking（每步
  GUI 调用 <100ms）+ teardown_with_inflight_job_is_safe + prep_finished 竞态
  修复后 5 连跑稳定。
- 工程身份：project_identity_scopes_persisted_state（A→B 清场、B→A 恢复）。
- 预存失败对账：integration.attribute_chain（tests/cpp/integration/
  test_attribute_chain.cpp:249，与 viz-c ledger 第 3 轮记录同一断言，非本线引入）。

- 独立审查（单 subagent，只读）：P0×1（持久切片号经 apply_pending_slice_numbers
  的无界递归——消费后应用修复）+ P1×2（身份切换未失效 prep 管线/未清旧工程体井
  ——generation 失效 + 双分支清场修复）+ P2×7 全部采纳；复验：闭包 6/6 ×6、
  受影响面 66/67 ×2（唯一失败=预存 attribute_chain）、xcb GL 截图 800×600、
  offscreen 降级 6/6。
