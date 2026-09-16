# CPP-A 平台/QGIS 线 — 测试计划（A0）

CTest 命名一律 `platform.` 前缀（协议 §独立验证）。0 tests / 全 skip / stub 输出不算通过。测试框架：轻量自研断言宏 + 独立 exe（避免引入 Catch2/GTest 新依赖；QtTest 仅在需要 QSignalSpy 时用）。所有 QGIS GUI 测试 offscreen（`QT_QPA_PLATFORM=offscreen`）。

## T1 构建与链接（Oracle 1）

| 测试 | 内容 | 判定 |
|---|---|---|
| platform.configure | 根 CMake 只开 platform（DATA/SCIENCE=OFF）configure 成功 | exit 0 |
| platform.configure_missing_module | `PWB_BUILD_DATA=ON` 而模块缺失 | configure FATAL_ERROR（负例） |
| platform.link_audit | 主 exe 的 DLL 依赖表不含 `python3*.dll`/`qgis_render_bridge`/`pyside`（dumpbin/依赖扫描） | 0 命中 |

## T2 真实 QGIS smoke（Oracle 2）

| 测试 | 内容 |
|---|---|
| platform.qgis_smoke | QgisRuntime::acquire → MapSession → canvas+tree 创建 → 打开矢量 fixture（GeoPackage）+ 栅格 fixture（GeoTIFF）→ provider 有效、CRS 验证（4326/4490）→ 渲染一帧（同步 job）→ PNG 输出非空非纯白 → teardown → 进程退出码 0 |
| 失败语义 | provider/CRS 错误必须带诊断文本；禁止把失败当 fallback 成功 |

fixture：测试自带最小 GeoPackage（点/线/面各一）+ 256×256 GeoTIFF，由测试代码运行时生成（GDAL 内存/临时文件），不依赖主仓大数据。

## T3 ToolPolicy（Oracle 3）

| 测试 | 内容 |
|---|---|
| platform.toolpolicy.matrix | 参数化快照 × 80 工具全矩阵：active/current/edit 一致与失配、无工程、只读 provider、RAW/frozen 角色门、阶段限制（3 阶段+未知 fail-closed）、dirty/capture/committing、undo/redo 栈空、选集 0/1/N、取消豁免 |
| platform.toolpolicy.invariants | enabled ⇒ 无 reason/severity；invisible ⇒ !enabled；checked 派生正确 |
| platform.toolpolicy.action_parity | QAction 构建器把 evaluate 结果映射到 enabled/checked/tooltip；同一快照下 QAction 状态 == policy 输出（Oracle 3 的 QAction 一致性） |

## T4 编辑闭环（Oracle 4）

| 测试 | 内容 |
|---|---|
| platform.edit.vertex_cycle | 编辑开启 → 移动一个顶点（edit buffer 直改 + edit command 宏）→ dirty=true → undo（几何复位）→ redo（几何=移动后）→ commit → staged asset（GeoJSON+sha256）→ 重读 staged 与属性一致 |
| platform.edit.topology_block | 构造自相交/重叠非法几何 → 拓扑校验报错 → commit 被拒（缓冲保留）→ 修复后 commit 成功 |
| platform.edit.readonly | 只读 provider（只读 GPKG 连接串）startEditing 拒绝或 commit 失败有诊断 |

## T5 生命周期（Oracle 5）

| 测试 | 内容 |
|---|---|
| platform.lifecycle.cycles | ≥20 次 自动 open(session+canvas+tree+layer) → 编辑一次 → close（按契约顺序）循环；统计 crash=0；进程退出码 0。500 次 soak/ASan 列为集成阶段门禁（本轮明确未跑） |

## T6 导出（Oracle 3/A3）

| 测试 | 内容 |
|---|---|
| platform.export.layout | QgsPrintLayout：A4 页 + map item（真实图层）+ legend → PNG/PDF/SVG 三格式非空（PNG 像素抽查、PDF magic bytes、SVG 根元素） |

## T7 部署 manifest（Oracle 6）

| 产物 | 内容 |
|---|---|
| `runtime-manifest.md` + `deploy/` | Qt/QGIS/GDAL/PROJ/provider/plugin/data 清单（文件+来源+版本）；最小 Windows package：无 Python 启动 → 加载 fixture → 渲染 smoke（干净 PATH） |

## T8 集成（Oracle 8）

| 测试 | 内容 |
|---|---|
| platform.adapters.substitutes | B/C port 替身在 `tests/cpp/platform/` 完成平台侧接线单测，报告标注「仅模块验证」 |
| 集成 gate（后续） | 真实 B/C E2E 后单独记录，不在本轮宣称 |

## 运行约束

- 所有编译/测试经 `Invoke-ResourceGate.ps1`（2 jobs、8 GiB 门槛、exit 75=资源拒绝非失败）。
- GUI 测试 offscreen；每测试 timeout 180s；CTest `--no-tests=error`。
