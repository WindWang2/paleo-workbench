# Core Flow — Target State (Goal A)

本文档定义本轮 Goal A 的目标态与验收口径。来源：`/goal` 指令 + current-state 审计。实现按 Work Package A0–A9 推进，每项完成后在本文档勾选。

## 验收总则

- 功能闭环真实可用、状态一致、科学语义可靠、工程可保存/恢复、模块间共享上下文与成果。
- 暂缓 100GB 地震体压测；保留 window/ROI/chunk/out-of-core 接口语义不回退。
- 不依赖线上 CI；本地分层验证（changed-area → package → integration → regression → final）。

## A1 工程/工区根对象

- [x] 审计确认工程已是所有工作的归属根（ProjectDocument + artifacts 目录树 + catalog）。
- [ ] `safe_rmtree` 不再双层吞异常（#1190）——Save-As 迁移失败必须可观测、可回滚。
- [ ] load/save 对称：未知段落保留不丢（#1170）。
- [ ] RAW immutability 由 DataStage 枚举 + 只读位 + 唯一写入口保证（已达成，回归测试覆盖）。

## A2 Catalog / Version / Tag / Provenance

- [ ] #1139：batch 内不自增 document revision（或新鲜度检查感知 batch 窗口），批量导入不再 O(M×N)。
- [ ] #1138 残留：adapter 剩余 2 处 `_save()` 走 dirty 增量。
- [ ] #1140：`resolve_path` 移除 basename/末两段兜底（或仅显式 opt-in），外部 RAW 丢失宁可显式 missing 不静默错绑。
- [ ] #1175：asset.id 路径段消毒与 version_id 对齐。
- [ ] #1172：`export_manifest` 增加 stale write 防护。
- [ ] #1149：grid_artifact 临时文件唯一名 + fsync + 原子 rename。
- [ ] #1183/#1182/#1173/#1171：close/export 增量序列化、tags 快照仅失败路径、行选择 tag 映射缓存、fs 探测缓存覆盖 catalog 路径。
- [ ] 反查能力：output→run→inputs 已有，补按 parent/run 的直接 SQL 谓词（可选）。

## A3 测井业务闭环

- [ ] #1193：loader 显式返回 decimation 元数据（truncated/sampled 标志 + 原始采样数）；ML 推断路径使用抽稀数据时必须在 payload 与 run 元数据中声明；或按需取全分辨率。禁止静默混用。
- [ ] #1151：移除 `z→R_s→H_t` 逐行回退——导出/QC 按 factor 类型显式选择物理量列，缺失即跳过并记录。
- [ ] 深度域：ft 井进入米制上下文时显式标注/换算（不静默）；`seismic_to_well` 哨兵消除歧义。

## A4 地震功能闭环（中小体积优先）

- [ ] #1136：取消路径——reader 线程可退出（哨兵/poison pill）、join 有界且线程清理、segyio 句柄单一所有权关闭。
- [ ] #1141：`_validate_existing` 比对 source identity（source_path + 文件身份），换源拒绝续算。
- [ ] #1192：`resume_pending` 先查已存在完整 DERIVED，存在则复用不重转码、不误标 stale。
- [ ] #1194：band 完成标记 fsync 对称（数据 + marker 内容 + 目录）。
- [ ] #1161：band 完成标记身份化（band 首-inline 编号或内容指纹），重开校验 band_inlines/shape。
- [ ] #1146：band 尺寸与 ResourceBudget 内存预算耦合（按 active_budget 推导），provider 准入估计对齐。
- [ ] #1160：finite_ratio 用 `np.isfinite`。
- [ ] #1188：C++ prefetch 越界地址修正。
- [ ] #1189：死测试文件清理（保留仍有效用例，标题如实）。

## A5 单因素图 / 地质计算

- [ ] #1150：井点坐标解析显式 None 判断（0.0 是合法坐标），键选择带 CRS 语义不混用。
- [ ] #1162：label/well 坐标长度守卫（不足即诊断，不 IndexError 不静默 (x,0)）。
- [ ] #1159：后台制备 commit 前校验 live 工程状态，迟到默认任务不追加。
- [ ] #1168：JobCancelled 与 Exception 分流，cancelled 不计入 failed_n，取消标志不丢失。
- [ ] #1174：harness `create_factor_map` factor_name 消毒 + 落盘路径 containment。

## A6 古地理综合业务链

- [ ] MapProduct：补 save→reopen roundtrip 集成测试。
- [ ] 溯源查询：提供一步式 describe API（用了哪些井/解释版本/factor map 版本/参数/输出位置）——在现有 run/lineage 之上封装，不建第二套。

## A7 Provider / Harness / Agent 可信化

- [ ] #1137：TaskCancelled 全链传播——provider 层不包装为 ProviderExecutionError；execute_provider 不捕 BaseException 吞 Ctrl-C；DataRun 终态区分 failed/cancelled。
- [ ] #1178：schema 校验强制嵌套 required/additionalProperties/array items/enum/numeric；output_schema 生效（至少校验 provider 输出顶层结构）。
- [ ] #1180：governor ImportError 不静默——显式 fallback 策略 + degraded 记录 + 日志。
- [ ] #1185：ToolRegistry 拒绝同名覆盖；execute 走 schema 校验。
- [ ] #1186：agent_panel 默认权限收敛为 READ+COMPUTE（WRITE 显式授予）；ActionRisk 与实际副作用对齐（写盘/catalog 登记的动作至少 WRITE）。
- [ ] swarm 剩余 4 个 agent（gis/carto/seismic/viz）与 #1143 对齐：未验证结果必须标注 stub/unverified，禁止伪造宣称。

## A8 Prediction / Model Security

- [ ] #1152：溯源信封保留键先行合并（`{**result, **envelope_overrides}` 或显式过滤），provider 不能覆写。
- [ ] #1176：model_path 必须解析到已注册 ModelVersion（artifact_uri + checksum 执行时复核）；未注册模型拒绝或显式标记 untrusted 且不携带注册身份。
- [ ] #1167：生产入口接 cancel 回调；取消返回完整协议字段（含 shape）。
- [ ] #1169：轮询循环接 cancel 检查点。
- [ ] #1184：`register_provider` 同名拒绝（与主 SDK 注册表一致）。
- [ ] #1187：batch/classes 字节上限（softmax 中间量预算）。
- [ ] `online_model_version_id` 参数覆盖收紧（白名单校验）。

## A9 保存/恢复/Crash Consistency

- [ ] 关键业务端到端 roundtrip 集成测试：create→import→interpret→derive→save→close→reopen→verify（覆盖 well 解释、seismic 解释、factor map、MapProduct、tags、versions、provenance、runs）。
- [ ] incomplete output 不注册为 complete（band done marker fsync + resume 校验，与 A4 联动）。

## 明确不做（本轮）

- 100GB SEG-Y 构造与全量 benchmark（保留可扩展接口）。
- UI 层大规模改动（Goal B 域）：#1133/1135/1142/1147/1153-1158/1163-1166/1179/1181/1186 的 UI 部分仅做最小接口适配。
- arbitrary line / depth slice / gain/clip/colormap 新视图功能（记录为 deferred，除非核心闭环受阻）。
- well 滤波/平滑/归一化/重采样全家桶（现有 3 操作 + 引擎能力已满足最小闭环；记录 deferred）。
