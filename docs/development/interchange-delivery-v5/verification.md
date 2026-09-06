# Verification — Geoscience Interchange, Project Packaging & Batch Delivery V5

Branch `feat/interchange-delivery-v5`（base `origin/main` @ `049423ab`）。
所有验证在本地完成（`run_env_io.sh`，offscreen Qt，python3.13）。

## 测试结果

| 套件 | 结果 |
|---|---|
| 新增 interchange 全套（14 个测试文件） | **177 passed**（修复后最终跑） |
| 回归：resources（import/export/preview/classifier） | 43 passed |
| 回归：project + catalog seam + grid artifact | 71 passed |
| 回归：catalog crash safety / reference layers / LAS provider / transcode | 48 passed, 1 skipped, **1 failed（既有问题，见下）** |

### 既有失败（非本分支引入）

`tests/test_transcode_segy_zarr.py::test_resume_rejects_swapped_source` 在
**纯净 `origin/main` worktree 上同样失败**（已复现验证）。该测试对同一文件
两次写入后依赖 mtime_ns 身份判别，属 seismic 转码方向的既有 flaky，本分支
未触碰 `seismic_transcode.py`，不予修改（不掩盖、不删测试、不在本方向越界修复）。

## 分阶段验证记录

1. **I0 审计** — 三路并行源码审计（well-log/tabular/segy、GIS/raster/3D、
   catalog/project/providers），产出 baseline.md 能力矩阵。所有后续实现均以
   "包装既有 parser" 为前提，无第二套 parser。
2. **I1-I2** — contract/registry/sniff + preflight/executor；
   fail-closed 断言（preflight 拒绝 ⇒ catalog 零资产）有测试钉死。
3. **I3-I8** — LAS/CSV/TSV/Excel/GeoJSON/vector(GDAL)/raster(rasterio)/SEG-Y/
   FLAC3D/Abaqus adapters；DLIS/VTK/OBJ/STL/SEG-Y-export 明确 capability-
   unavailable；导出全部带结构化 verify（重读+计数+bounds+checksum）。
4. **I10-I12** — portable package（目录 + `.paleopkg.zip`）、Manifest V2、
   verify_package、跨根 reopen（重定位后 managed 解析 + sha256 一致）。
5. **I13/I14** — 依赖审计（valid/missing/changed/unknown/relink；size+hash
   身份判定，basename-only 永不自动重连）；批量服务（bounded workers、失败
   隔离、取消、确定性命名）；1000 文件批量无 FD 泄漏（/proc/self/fd 断言）。
6. **I15/I16** — 5 个内置交付 profile + JSON/Markdown QA 报告；
   UNVERIFIED 永不渲染为 Verified（有逐字断言）。
7. **I17** — traversal/绝对路径/symlink/NFD/大小写碰撞/Windows 保留名/尾点
   空格/超长路径 全部 fail-closed；zip 解包 validate-then-write。
8. **I18** — normal/damaged/cross-root 三类 fixture 矩阵，全部程序化生成。
9. **I19** — headless Qt 模型（offscreen QApplication 测试）。
10. **I20** — ENOSPC mid-copy、transform 中途失败、导出崩溃/取消、打包中途
    崩溃、全故障后 reopen 一致性。

## 三轮 Review 与修复

并行三路审查（correctness / architecture / adversarial-performance），
每条发现均经审查 agent 实际运行代码证实后修复：

### 第一轮 Correctness（4 P1 + 15 P2，P1 全修）
- [P1] 文本嗅探把任意 ≥3.6KB 文本判为 SEG-Y 并拒绝导入 → 嗅探改为强证据
  （3500 偏移 revision 标记）+ 扩展名门控；preflight 对 medium/low 嗅探冲突
  降级为建议而非硬错误（D11）。
- [P1] raster dtype 转换导出必然 verify FAILED → probe 前施加同款转换；
  nodata 越界时按目标 dtype 解析（越界丢弃优于损坏文件）。
- [P1] TSV→CSV 导出不转换分隔符却判 VERIFIED → 按嗅探到的源分隔符读取。
- [P1] zip 交付缺 QA 报告 → 目录先构建、报告写入后再压缩。
- [P2] `ExportVerification` 位置参数把 detail 串进 warnings（12 处）→ 全部
  改 keyword；LAS null 深度污染方向锁；>64MB LAS 误报空数据区；package
  stale 双记录；build_zip 原子化；symlink 目录静默跳过 → 改为显式拒绝；
  vendor 路径加 version_id 防碰撞；拷贝后哈希（TOCTOU）；SEG-Y 单位口径
  统一 us；无表头 CSV 行数偏差。

### 第二轮 Architecture（1 P1 + 4 P2，P1 修复）
- [P1] ExportExecutor 绕过仓库唯一导出 provenance 咽喉点 → 接入
  `lifecycle.register_export_output`（与 record_export 同实现），
  `ExportPlan` 增加 `source_version_ids`/`linked_id`，失败导出记录 failed
  run（D3 修订）；`artifact_dir_for` 复用 project.paths；ui 模型迁至
  `ui/pages/interchange_models.py`；import provenance 反向指针缺口记录在案。
- 确认无第二权威/无循环导入/纯增量提交（41 文件全部为新增）。

### 第三轮 Adversarial（6 项必须修复，全部完成）
- relink 在 size/hash 全缺失时把任意文件当候选 → 无身份即拒绝。
- 目录形包 copytree 解引用符号链接（内容内联/无限拷贝）→ validate-then-copy。
- zip 校验器接受重复 manifest 条目与目录条目 → validate_paths 加碰撞检查、
  目录条目按错误处理。
- `com1 `/`file.txt.` 绕过 Windows 保留名与覆盖防线 → 尾点/空格拒绝。
- 串行批量中单个 job 的 CancelledError 中止整批 → 仅共享 token 取消才中止。
- progress 回调异常丢失批次结果 → 回调降级并保证返回结果。
- 附带：manifest `total_size_bytes` 谎报检测、`schema_version` 严格整数、
  zip 校验器 catalog.json 解析对齐。

修复后全部回归通过（177 interchange + 162 既有相关）。

## 规模与性能观察（审查 agent 实测）

- 1000 文件批量：0 失败、FD 增量 <50、确定性输出命名。
- 210MB artifact 打包：sha256 每文件恰一次，2 读 1 写流式，无内存整载。
- 100k 文件目录 relink 候选扫描：~1.2s。
- 62MB LAS inspect：≤2 遍有界扫描；>64MB 自动降为 header-only。
- 10k 行 BatchResultModel：set_result 4.5ms。

## 资源约束遵守

- 未重建 vendored QGIS / GDAL；未运行 qgis-marked 测试。
- 并发 ≤2；pytest 未使用无界 -n；SEG-Y 仅 tiny synthetic（196KB）。
- 磁盘全程监控无异常增长；临时目录均显式清理。
