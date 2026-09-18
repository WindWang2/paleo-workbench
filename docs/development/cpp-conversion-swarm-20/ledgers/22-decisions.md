# 22-decisions — geomodel 契约层

- **D1 切分**:本切片 = geomodel 契约层(domain 对象模型 + QC 编排 + 导出写器/解析器 + advisor + lithology + builders 构造器半),全部纯函数/纯数据。scene_adapter(Qt/GL 桥)、analysis(geoviz 委托)、demo(geoviz+非生产)不迁;几何核已在 conv-12。
- **D2 对象表示**:C++ 不镜像 6 个 dataclass 层级——单一 `DomainObject` 结构(kind 由 object_id 前缀导出 + 全字段 optional 超集)。依据:Python 构造器强制 object_id 前缀与类绑定,qc/geometry_stats 的 isinstance 分派在行为上等价于前缀分派;fixture 以 JSON spec 表达构造参数。from_meta 语义(meta 恢复、数组缺席)用 `DomainObject::from_meta` 表达:构造仅取 meta 键、数组留空。
- **D3 数组表示**:顶点/面/格网用 `std::vector` + `HorizonGrid`/`Vec3`(conv-12 类型复用);NaN 用 `quiet_NaN`,JSON 侧按惯例 null 化(fixture 不含裸 NaN)。
- **D4 错误即数据 vs 异常**:构造校验/`_mesh_of`/读解析失败走 `DomainError`/`ExportError` C++ 异常类型(对齐 Python ValueError/RuntimeError 类别);`apply_meta` 按 Python 语义静默吞错只记 restored 列表;`qc_object` 的审计崩溃路径(QC_AUDIT_FAILED)在 C++ 侧捕获 std::exception 等效。
- **D5 QCBlockerError**:C++ 异常携带 message(逐字)——`.report` 属性无等价需求(冻结只查消息文本)。
- **D6 写器 API 形状**:`export_*` 返回 `{file_text|file_bytes_b64, sidecar_json}`——文件 I/O 是薄壳,mkdir/write 由调用方;oracle 冻结**内容**(STL bytes 以 base64 入 JSON)。`read_*`/`validate_export` 接受文本/字节串返回 JSON 结构或抛 ExportError。
- **D7 格式化**:文本写器逐字节对齐 Python `%` 格式:`{x:.4f}`/`{x:.6f}`/`{v:.6g}` 用 snprintf 等价;`{nan_fraction:.0%}`/`{degenerate:.2%}` 同 conv-21 的半偶舍入惯例(f-string % 格式 = 精确十进制半偶)。ET.indent 的 XML 输出按 Python ElementTree 形态手写(声明行 + 2 空格缩进 + 自闭合 `/>` 与属性顺序)。
- **D8 文件名/stem**:sidecar 名 `stem + ".provenance.json"`;`Path.stem` 语义由 ingest `split_path_parts` 不可直用(conv-21 已证 `..`/`a.` 分歧),C++ 用与 conv-21 相同的忠实 stem 实现(仅 `0<rfind('.')<len-1` 时有 suffix)。
- **D9 分派**:qc_object 未知 kind→UNKNOWN_KIND issue(非异常);validate_export 未知后缀→ExportError;`_mesh_of` 非 mesh 类→ExportError。
- **D10 dict 语义保留**:advisor 的 dict→record 默认(`l.get("top",0.0)`)、quality dict `q.get(k,0) or 0`、provenance `meta or {}`、formation_tops `list(t)` 等 Python 语义全部按值保留;`str()`/`float()`/`int()`/`bool()` 强转点逐一对照。
- **D11 线程**:`ModelAssembly._lock` 为 RLock;C++ 用 `std::recursive_mutex` 保持同一可观察语义(单线程 oracle 下等价)。
- **D12 oracle 协议**:沿用 conv-21 惯例——`indent=1 ensure_ascii=False`、`$FX` 占位(STL bytes→base64、写器产物→文本)、raises 类名 + 消息双断言、`run_case` 按 fn 分派、dump/parse 归一化比较、生成器自断言案例数与逐字节确定性。
- **D13 偏差记档**:ET.indent/ElementTree.write 的字节细节(XML 声明大小写、自闭合空格形态)与手写 XML 可能存在尾差——oracle 对 `export_mesh_vtp` 冻结**解析后结构**(read_vtp round-trip + 全文本字节),字节级断言以首次冻结产物为准;`np.median`/`searchsorted`/`unique` 在 regrid 中的语义按值实现;`%.6g` 的 Python repr 与 printf `%g` 在指数形态上若有分歧按冻结产物为准。`logger` 不迁。
- **D14 非目标**:scene_adapter/analysis/demo 三个 Qt/GL/geoviz 模块、measurements/section/fault_displacement/sculpting/mesh_qc/volume(已在 conv-12)、catalog 持久化接线、UI 面板、pytest 迁移。
