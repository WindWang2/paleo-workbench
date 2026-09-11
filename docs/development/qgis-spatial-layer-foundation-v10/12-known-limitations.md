# 12 — Known limitations（V10）

编号续 V9 惯例（docs/development/qgis-geological-authoring-v9/09-known-limitations.md）。
00-baseline.md §B 列出的起点缺口中，被 V10 关闭的项在对应主题文档
记录；**未关闭且预计跨批存续**的收敛于此。

1. **edit_tools measure 读 `QgsProject::instance()`，即使触发栈是
   display 画布**（wrong-context 泄漏）：display 栈各自持 project，
   但测量工具的椭球/CRS 上下文固定读单例工程；display 栈的自有工程
   不经 `set_project_crs` 推送（推送只作用于 authoring 共享工程，
   03-qgsproject-authority.md §2）。修复需 C++ 侧 per-canvas project
   routing，本批不做。
2. **provider 单一栽培（monoculture）**：只有 memory provider 活着；
   capability snapshot（06-provider-schema.md §1）只对 memory 有实证
   覆盖——ogr/gdal 路径的 flag 语义未经实跑验证。
3. **QgsAttributeForm/QgsDualView 未收编**：维持 V9 D3 决策
   （docs/development/qgis-geological-authoring-v9/03-decisions.md D3）
   ——双写风险高于收益，自定义会话权威属性表保留（决策 J 谱系）。
4. **表达式约束不 Python 执行**：只在 provider 侧（QGIS 消费），
   Python 会话不复刻表达式引擎（06-provider-schema.md §4）。
5. **`MapDocument.crs` wire 默认 "EPSG:4326" 保留**：消费契约已覆盖
   （02-crs-transform.md §5 记录在案）；改默认动持久化兼容，不做。
6. **默认（self-contained vendor）配方要求 PySide6 6.8.x**：PySide6
   6.11.2 机器上须走 conda 配方（01-qgis-runtime.md §6）。该运行时
   漂移现由 health 模块诊断（00-baseline.md §C），但不是被修复。
   6a. **osgeo python 绑定 ABI 锁**（V8 限制 #1 家族延续）：标量栅格
   路径需要 osgeo 与 venv 同 ABI——本机 deps 前缀的绑定是 cp314而
   venv 是 cp312，3 个标量栅格 qgis 测试按配方约束诚实跳过
   （`qgis_scalar_pipeline_ready` 守卫，11-review-findings.md §3）。
7. **栅格镜像无 scale-range 通道**（vector only）：07-rendering.md §2
   的 min_scale/max_scale 只在矢量 upsert 路径。
8. **`probe_qgis_runtime` 首次调用构造 display `QgisMapStack`**：
   一次性 ~100ms（进程级缓存，测试经 `reset_runtime_probe_cache`
   显式失效）——探针需要活栈承载 runtime_facts 调用。
9. **跨栈镜像收养（R3）靠纪律不靠构造**：单活 authoring shim +
   `shutdown_live_shims` 约束同一时刻一个活编辑面；构造上不阻止
   第二活栈（04-layer-registry.md §3）。
10. **proj.db 部署改写共享 vendor build 树**：`<vendor>/output/share/proj`
    是机内共享构件（幂等、记日志，01-qgis-runtime.md §4）——多机/
    CI 需各自供给或依赖 conda deps 前缀。

另：100GB seismic 零接触（00-baseline.md §E，沿 V9 限制 #10 谱系）。
本清单在审查轮次（11-review-findings.md）回填后复核——新增限制
续编号，不重排既有条目。
