# Seismic Native Stack 台账 v3（feat/cpp-seismic-native-stack）

> 目标：Native IO → Native attribute pipeline → Native viewer/service，
> 清理 seismic Python runtime/glue。上限 12 轮。
> Scope/契约见同目录 v3-contracts.md。

| 轮 | 改动 | 验证结果 | 判定 | 下一步 |
|---|---|---|---|---|
| S1 | 环境与事实核查：origin/main `ff67dcf3`；open PR 无 seismic 命名分支；盘点 agent 只读报告（Python production 面 / C++ 覆盖 / 差距表）；oracle 语义实测（loader/models/cache/attributes 源码冻结）；venv-oracle py3.14+numpy2.5.3+scipy1.18.1 就绪；tiny.sgy = format 5 唯一真实样本；契约/ledger 落地 | 全部实测非猜测 | 通过 | IO 实现 |
| S2 | IO/service 实现：VolumeDescriptor/BinGridGeometry/CancelFlag、inspect_segy（bin-grid 推断+SourceGroupScalar）、tile_read（SEG-Y/PWBVOL1 半开窗+取消）、TileCache（字节预算 LRU）、tiled ISeismicVolume、SeismicVolumeService+空间 JSON codec；segy_reader 重构为 inspect+window 组合 | 语法零告警；提交 `019383ee` | 通过 | kernels |
| S3 | 6 个 S-line kernels + detail/attribute_math.hpp 抽取；注册 4→10；sl_* oracle fixtures（8 case，负自检抓到 curvature 比较器空洞通过并修复）；io oracle fixtures（4 case，segyio 交叉校验，自写 SEG-Y 字节器）；C++ 测试 sline/tile_read/tile_cache/service + registration 更新 | 首轮 ctest 暴露 5 个真实缺陷（见 S4） | 部分通过 | 修 |
| S4 | 缺陷修复：①curvature 轴-2 滑窗行基址错误（identity → (l/nc)*(nc*ns)+(l%nc)*ns）②tiled 后端跨平面 tile 键碰撞（改为真 3D tile，键含固定轴 tile 号，相邻面共享缓存）③CancelFlag 默认构造为空操作（改为默认创建活标志）④IO oracle 角点 cm 编码（mm 溢出 int32）+ 期望改为 oracle `_infer_bin_grid` 实测输出（方位角镜像 quirk 冻结并记录）⑤smoke 测试浮点等值比较 | seismic-stack 14/14 绿；集成树 59/59 绿（含 platform.attribute_ui 端到端）；提交 `143ac6a3` | 通过 | review |
| S5 | Review A（独立 agent：parity+架构）：无 P0；P1×2（inspect_pwbvol 异常路径、import id 双计数器命名空间冲突）+ P2×11；逐项修复（fail-closed header 守卫、next_segy_import_id 单一进程级序列、取消静默、曲率默认窗 3、f32 atan2、死字段填充、tile_shape 归一、契约文档 5 处修正）；迁移分类台账 v3-migration.md 落地 | 修复后集成树 59/59；提交 `91499f72` | 通过 | Review B/C |
| S6 | Review B/C（独立 agent：oracle/边界+产品闭环）：结论"可合入"。oracle 链三方一致 + 字节级重放验证（56 文件 SHA、24 文件 cmp 全部一致）；PWB_WITH_* 组合矩阵闭合、零 Python 运行时依赖、冲突面与非 seismic 区域零重叠、文档如实。边界缺口清单 G1-G10（均已声明或列为后续）；本轮修复 G1（axis_steps 零/非有限拒绝）+ G3（elements 溢出加固）+ 契约文档 nearest/cache 键微瑕；流程性 P1（二进制过期）以两棵树全量重编消除 | 最终重编：seismic-stack 14/14、集成树 59/59 | 完成 | push+PR |
