# 19-findings — 资源扫描/井顶/井位 XML/预览解析核(逐符号)

> 范围:§5 列出的全部源文件,全文阅读后逐公开符号记录:输入、输出、空/失败/并列语义、与已有 C++ 核(mapping_kernel/seismic_io)的关系、测试缺口。
> 索引按文件名;标注【移植】= CONV-19 C++ 移植目标(oracle 冻结),【只读】= 本切片不移植(原因注明),【宿主】= 留给 UI/catalog 接线层。

## 1. paleo_workbench/resources/__init__.py 【只读(3 行 re-export)】

仅 `from .scanner import scan_resources`。无逻辑。测试缺口:无。

## 2. paleo_workbench/resources/well_tops_parser.py 【移植 → libs/ingest well_tops】

### `WellTop`(frozen dataclass)
- 字段:`well_name: str, top_name: str, md: float, tvd: float | None = None`。
- 纯值对象;C++ 对应 `struct WellTop {std::string well_name, top_name; double md; std::optional<double> tvd;}`。
- oracle 序列化:四字段;tvd null 显式区分缺列与解析失败(两者都 → None)。

### `parse_well_tops(path) -> list[WellTop]`
- 输入:UTF-8(errors="replace")读全文,`splitlines()` 按 \n/\r/\r\n 切(容忍 CRLF)。
- 逐行:strip 后空行/#开头跳过;`split()` 分词;`len(tokens) < 3` 跳过(短行容忍);
  `float(tokens[2])` 失败(ValueError)跳过整行(garbage 行容忍);`len>=7` 且 `float(tokens[6])` 成功 → tvd,否则 None。
- 输出:保持文件顺序的 WellTop 列表;无去重、无排序。
- float 语义:Python `float()` 接受 "1e3"/"inf"/"nan"/"+5"/"1_0"(下划线,PEP 515)、前后空白;C++ 需 Python-兼容 float 解析器(拒绝十六进制/逗号)。NaN md 不会失败——`float("nan")` 合法 ⇒ md=NaN 的行会产出(测试缺口:现有 4 个 pytest 未覆盖 NaN/inf 行,oracle 生成器补)。
- 空文件/纯注释 → `[]`。
- 与已有核:无重叠(seismic_io 是二进制 SEG-Y;此处是文本井顶)。
- 测试:tests/test_well_tops_parser.py 4 案(基本行/垃圾行/缺 TVD/空文件);fixture tests/fixtures/realdata/DC.dat(SMI 真实 4 井 4 顶,列 8)。

## 3. paleo_workbench/resources/well_location_xml.py 【移植 → libs/ingest well_location_xml】

### 常量键集(全部经 `_key` 归一)
- `_NAME_KEYS = {well, wellname, wellid, wellno, uwi, 井名, 井号, 井号名称}`
- `_X_KEYS = {x, xcoord, xcoordinate, easting, east, 经度, 东坐标, x坐标, longitude, lon}`
- `_Y_KEYS = {y, ycoord, ycoordinate, northing, north, 纬度, 北坐标, y坐标, latitude, lat}`
- `_Z_KEYS = {z, elevation, elev, kb, 海拔, 井口高程, 高程}`
- `_UWI_KEYS = {uwi, api, wellid, 井号}`;`_CRS_KEYS = {crs, srs, srsname, coordinatesystem, 坐标系}`
- **歧义风险**:`_first`/`next(...)` 遍历的是 Python **set** 迭代序(hash 序,非声明序)。同族多键同时命中时选中哪个键不确定。oracle 案例必须保证每族至多一个键命中(真实交付文件即如此);C++ 按声明序取首个命中(确定性),与单键命中情形可证等价(decisions D5)。

### `_local_name(v)` / `_key(v)`
- local_name:剥 `}` 命名空间(`ns}tag` → 最后一段)与 `:` 前缀(`pfx:tag` → 最后一段)。注意 ET 的 tag 形如 `{uri}local`;`: ` 只对未解析前缀文本生效。
- `_key` = local_name 后删除所有非 `[0-9A-Za-z\u4e00-\u9fff]` 字符再 casefold(`"Well-Name "` → `"wellname"`;`"X坐标"` → `"x坐标"`)。
- C++:casefold 对 ASCII 等价 tolower;CJK 不变形;按 UTF-8 码点处理(非 ASCII 字符逐字节删除规则需按码点判断 ∈ CJK 区 U+4E00-9FFF)。

### `XMLWellLocation`(frozen dataclass)
- `name: str, x: float, y: float, z: float|None=None, uwi: str="", source_crs: str=""`。

### `_float_or_none(v)` 
- `float(str(v).strip())`;TypeError/ValueError → None。接受 "1e5"/"nan"/"inf"(nan/inf 会产出 x=NaN 的记录——不拒绝!与 well_tops 一致的 Python float 语义)。

### `_record_from_values(values, inherited_crs, allow_plain_name)`
- name:按 _NAME_KEYS 首个非空;无则 `allow_plain_name` 时用 `name` 键(仅 `<Well>`/含"井"元素放行——防普通 GIS 点 XML 变井)。
- x/y:各按 _X_KEYS/_Y_KEYS 首个非空键后 `_float_or_none`;任一为 None 或 name 空 → None。
- z:`_first(_Z_KEYS)` 首个非空值再 `_float_or_none`(不解析则 z=None)。
- uwi:`_first(_UWI_KEYS)`;source_crs:`_first(_CRS_KEYS) or inherited_crs`(**V10 M-B 静默 4326 收敛**:lon/lat 形键名不再当 CRS 声明;""=未变换透传,消费方 domain_binding.project_coordinates 如实标记 UNTRANSFORMED)。
- 属性与子文本合并处:attrib **覆盖**同名子文本键(`values.update(attrib)`)。

### `_text_of_cell(cell)`
- 深度优先 `cell.iter()`:首个 `_key(tag)=="data"` 且有 text 的后代 → 其 strip 文本;否则 cell 自身 text。SpreadsheetML `<Cell><Data>` 解法。

### `_spreadsheet_records(root, inherited_crs)`
- 遍历 `root.iter()`(文档序)找 worksheet(`_key(tag)=="worksheet"`);其内行=`_key=="row"`,行内 cells 按 `_key=="cell"`。
- `len(rows)<2` 跳过;headers=_key(row0);要求 headers 中**至少一个 ∈ _NAME_KEYS 且一个 ∈ _X_KEYS 且一个 ∈ _Y_KEYS**(显式井名列硬要求;`名称+X+Y` 不认)。
- 数据行:`values = {header: cell.strip() for 非空 header 且 index<len(row) 且 cell 非空}` → `_record_from_values(allow_plain_name=False)`。
- 全局上限 `_MAX_RECORDS=100_000`,达到即 return。

### `extract_well_locations_xml(path) -> (records, warnings)`
- 解析失败:`([], ["XML 井位解析失败: {ExcClassName}"])`——defusedxml/ET 均为 `ParseError`;**用户面 warning,从不抛异常**。
- 成功:root attribs(非空值)→ `inherited_crs=_first(_CRS_KEYS)`;先 `_spreadsheet_records`,非空即返 `(records, [])`。
- 否则通用元素扫描:每个有子元素的 element,`values` = 子元素文本(非空)按 `_key(child.tag)`,再 update element attrib(同名 attrib 胜);`allow_plain_name = "well" in tag or "井" in tag`(tag 已 `_key` 归一,子串判断)。
- 去重键 `(name,x,y)`(seen set,首见保留);上限 100k break。
- 顺序 = 文档序(SpreadsheetML 优先;否则元素序)。

### `is_well_location_xml(path) -> bool`
- `bool(records)`;分类器用它认领 `well_head/xml`。

- C++ 关系:纯 DOM+文本解析,零外部依赖;XML 基建与 well_log_xml/preview 共用(libs/ingest 内置 mini XML 解析器,ET 兼容语义)。
- 测试缺口:无错误分支的 warning 文案测试;oracle 补(坏 XML → "XML 井位解析失败: ParseError")。

## 4. paleo_workbench/resources/well_log_xml.py 【移植 → libs/ingest well_log_xml】

### `_local_name(v)`(与 well_location 的 `_key` **不同**)
- 剥命名空间/前缀后 `strip().casefold()`,**不删**内部标点(`"Log-Curve"` 保留连字符)。

### `is_well_log_xml(path) -> bool`
- 解析失败 → False(静默)。
- 遍历 `root.iter()` 上限 `_MAX_ELEMENTS=200_000`(达到即 break):收集 tag 集;
  `has_log_element: tag=="log"`;`has_log_curve_info: tag ∈ {logcurveinfo, curveinfo}`;`has_log_data: tag=="logdata"`;
  worksheet 元素 attrib 值(strip+casefold)任一 ∈ `_SPREADSHEET_NAMES={测井曲线, welllog, well log, log curves}` → has_named_well_log_sheet。
- `root_tag` 子串含 "witsml" **或 tag 集**恰含元素 "witsml"(注意:`"witsml" in tags` 是集合成员、`in root_tag` 是子串——两种语义混用,C++ 必须分别实现)。
- 返回 `(has_log_element ∧ has_log_curve_info ∧ has_log_data) ∨ (is_witsml ∧ has_log_curve_info ∧ has_log_data) ∨ has_named_well_log_sheet`。
- 不用文件名提示(regional_delivery.xml 靠内容识别——tests/test_resources_classifier.py 两案钉死)。
- C++:与 well_location_xml 共用 XML 基建;`__all__` 只导出 is_well_log_xml。

## 5. paleo_workbench/resources/preview_parsers/models.py 【移植 → libs/ingest preview models】

### 常量表(扩展名集合,全小写)
- `MAX_TEXT_PREVIEW_BYTES=256KiB; MAX_TABLE_ROWS=200; MAX_TABLE_COLUMNS=40; MAX_JSON_PARSE_BYTES=5MiB; JSON_ARRAY_COLLAPSE_THRESHOLD=100`。
- `TEXT_FORMATS={txt,text,log,dat,xml}; TABLE={csv,tsv}; EXCEL={xlsx,xls}; IMAGE={png,jpg,jpeg,tif,tiff,bmp}; PDF={pdf}; LAS={las}; SEGY={sgy,segy}; MARKDOWN={md,markdown,htm,html}; HTML={htm,html}; JSON={json,geojson}; GEOTIFF={tif,tiff}; AUDIO={wav,mp3,flac,ogg,m4a}; VIDEO={mp4,mov,webm,mkv,avi}`。
- C++:`constexpr` 集合 + 查询函数;oracle 逐集合对账。

### `PreviewMode`(Literal 14 值)
- empty/geoviz/pdf/image/text/table/well_log/seismic/message/rich_text/json_tree/geotiff/media/web_document。C++ enum + 字符串映射。

### `PreviewResult`(frozen dataclass,~28 字段)
- 全字段默认空;`image_bytes/pdf_bytes: bytes`;`json_payload: object|None`;`seismic_volume: ndarray|None`(仅 seismic 预览,本切片 C++ 侧不载体积)。
- C++:`struct PreviewResult` 精简为移植 parser 实际产出的字段(mode/title/path/revision/format/status/type_label/message/warning/text/table_headers/table_rows/summary_rows/sheets/truncated/image_bytes/rich_html/json_truncated/media_path/estimated_bytes/visualization_available/cacheable/retryable/data_headers/data_rows);json_payload 只记 ok/fail(json_preview 的 payload 树不进对账,见 decisions D7)。

## 6. paleo_workbench/resources/preview_parsers/__init__.py 【只读】

re-export models 常量;无逻辑。

## 7. paleo_workbench/resources/preview_parsers/table_parsers.py 【移植 → libs/ingest preview text/table】

### `safe_stat`(=project.paths.safe_file_stat 别名)
- `(st_size, st_mtime_ns)` 或 OSError→None。C++ 返回 revision 对;mtime_ns 精度 std::filesystem 无法直接给 ns(linux stat 可),oracle 只冻 size(mtime 注入固定值)。

### `parse_error_preview(resource, message)`
- message 模式 PreviewResult,message+warning 双写同文。

### `read_preview_chunk(path, limit_kib) -> (bytes, truncated)`
- `stat().st_size` 与 `read(limit)`;`truncated = st_size > limit`。上限 = limit_kib*1024。

### `decode_text_with_fallback(raw_bytes)`
- utf-8-sig 严格 → 失败试 gb18030 → 失败 utf-8-sig errors=replace。
- **C++ 分歧(决策 D6)**:gb18030 解码表需 ICU 级依赖,本切片实现 utf-8-sig 严格 → 失败 replace 两级;非 UTF-8 中文 GBK 文件的第三级差异在 decisions 声明,oracle 不冻 GB18030 专属案例。

### `text_preview(resource, settings)`
- chunk + fallback 解码;warning=`"仅显示前 {kib} KiB"`(truncated 时);mode=text。

### `dat_preview(resource, settings)`
- chunk;若 byte 截断且末尾非 \n/\r:回退到最后一个换行(无则空)——丢弃半行。
- 逐行:strip;空跳;`#` 注释行 shlex 剥 `#` 后分词;数据行直接 shlex 分词(shlex.split POSIX 语义:单双引号、转义;失败 ValueError → **整体回退 text_preview**)。
- 注释行归类:`first=tokens[0].casefold().rstrip(":")`;`"field"/"type"` 开头或整行含 `"file from smi"` → 表头候选**排除**;其余注释行进 header_candidates(保序)。
- 结构门槛:数据行 ≥2;首行宽 ≥2;全部数据行等宽;否则回退 text。
- 表头:`reversed(header_candidates)` 中首个宽度匹配;否则 `("列 1".."列 N")`。
- 截断 = byte_truncated ∨ 数据行 >max_rows ∨ 宽 >max_columns;warning=`"数据列表已按预览上限截断"`。
- C++:需忠实移植 **shlex POSIX 分词**(shlex: whitespace 切分、'…' 全字面、"…" 内 \" \\ 转义、\ 转义任意字符、未闭合引号 ValueError)。oracle 用真实 shlex 冻结(含引号/转义/未闭合失败案)。

### `table_preview(resource, delimiter, settings)`
- chunk → utf-8-sig decode(errors=replace) → `csv.reader`(field_size_limit 提到 max(len(bytes),256KiB,默认))。
- 行循环:`row_index > table_max_rows` → truncated+break(**读到 201 行 break,rows 保留 200**;headers 不占计数);`len(row)>max_columns` → truncated;append `row[:max_columns]`。
- csv.Error → parse_error_preview(`"表格解析失败: Error"`);headers=parsed_rows[0],body=rows[1:];warning=`"表格预览已按行列上限截断"`。
- Python csv 语义细节(C++ 移植点):默认 dialect excel——`quotechar='"'`、双引号转义、引号字段可含 delimiter/换行(test_preview_provider quoted-newlines 案)、`\r\n` 归一;无引号字段的引号出现按字面(分歧点 `doublequote`/`QUOTE_MINIMAL` 只影响写出)。

### `excel_preview` / `_dataframe_rows` 【只读(pandas)】
- 依赖 pandas;本环境 ImportError → `parse_error_preview("Excel 预览失败: ImportError")`——该**依赖缺失回退**是 C++ 常态(pandas 无 C++ 对应),oracle 冻结回退行为(decisions D8)。NaN 显示:`value != value → ""`(_dataframe_rows)。

## 8. paleo_workbench/resources/preview_parsers/document_parsers.py 【移植 → libs/ingest preview document】

### `resource_revision_token(asset, safe_stat_fn)`
- `("resource", id, path, type, format, status, checksum, stat_tuple|None)`。C++:revision 数组;oracle 冻结(stat 注入)。

### `artifact_preview(artifact)`
- mode=message;title=basename(output_path) 或全路径;`"成果文件 · 关联对象 {linked_id}"`;status=generated。

### `image_fallback(resource, revision, warning)`
- 读 bytes(OSError→b"");mode=image + image_bytes。

### `geotiff_preview` 【只读(rasterio)】
- ImportError/异常 → `image_fallback(warning="地理元数据读取失败，仅显示图像")`(C++ 常态回退,oracle 冻回退)。

### `markdown_rich_preview` / `markdown_to_html(markdown)`
- chunk+utf-8-sig decode;mode=rich_text;warning 同 text。
- 行级渲染:``` 切换 code block(未闭合时结尾补 `<pre><code>`);`html.escape`(转 `& < > " '` 五符,`&#x27;` 形式)逐行;
  空行 flush 段落+列表;`^(#{1,6})\s+(.*)$` → h1-h6;`^[-*]\s+` → ul、`^\d+\.\s+` → ol(列表类型切换时先闭合);段落数组 join 空格后 `<p>…</p>`。
- 输出 `"\n".join(rendered)`。纯字符串 → 完整移植;oracle 真实函数冻结(含转义/嵌套/未闭合 fence)。

### `json_preview(resource, settings)`
- stat 失败 → `"文件不存在"`;`limit=json_limit_mib MiB`;`truncated=size>limit`;读 `min(limit, size)` 字节(truncated)否则 limit+1。
- utf-8-sig decode(replace)→ json.loads。失败:truncated → `"JSON 文件超过预览设置上限 {mib} MiB，请在预览设置中提高上限"`;否则 `"JSON 解析失败: JSONDecodeError"`。
- 成功:mode=json_tree;warning=`"JSON 文件超过预览设置上限 {mib} MiB，仅解析前 {mib} MiB"`。
- C++:JSON **有效性判定**(Python json 兼容:接受 NaN/Infinity/-Infinity 字面量、\u 转义、重复键后者胜),不需要构建树(decisions D7)。

### `audio_preview` / `video_preview` / `doc_preview`
- media/message 常量构造;doc 文案 `"旧版二进制 .doc 不受支持，请另存为 .docx 后再预览"`。

### `docx_preview` 【只读(python-docx)】
- ImportError → `"docx 预览依赖缺失，请安装 python-docx"`;解析失败 → `"docx 解析失败"`;截断按字节切+replace 回解(warning 仅显示前 N KiB)。C++ 常态=依赖缺失回退(oracle 冻)。

## 9. paleo_workbench/resources/preview_parsers/office_parsers.py 【移植 → libs/ingest preview office】

常量:`MAX_ARCHIVE_NAMES=500; MAX_EMBEDDED_IMAGE_BYTES=16MiB; MAX_CENTRAL_DIRECTORY_BYTES=4MiB; MAX_CENTRAL_ENTRIES=10_000; MAX_CENTRAL_NAME_BYTES=1MiB; _SPREADSHEETML_NAMESPACE="urn:schemas-microsoft-com:office:spreadsheet"`。

### `BoundedReader`
- limit 字节后人工 EOF;`artificial_eof_received` 标记(判 boundary 截断)。

### `spreadsheetml_preview(resource, max_text_bytes, max_rows, max_columns) -> PreviewResult|None`
- **iterparse 流式**语义(start/end 事件 + element.clear()):
  - 首个 start:根元素 namespace/local ≠ Workbook → **return None**(不认领)。
  - 第一个 Worksheet start 记 sheet_name(`ss:Name` 或 `Name` 属性,`_attribute` 先 `{ns}Name` 后裸 Name);**第二个 Worksheet start 或第一个 Worksheet end → 停止**(_FirstWorksheetComplete)。
  - Table start/end 切换;仅第一 worksheet+第一 table 内消费 Row/Cell。
  - Row start:行数 ≥ max_rows+1 → truncated+停;`ss:Index`(正整数;负/0/非数 → malformed)否则 `next_row_position`;若 < 推进位 → malformed+钳制。
  - Cell end:`ss:Index` 决定 desired_position;`< current_cell_position` → malformed+钳制;`≤ max_columns` 补空串到位置后 append `_cell_text`(首个 `{ns}Data` 后代的 itertext 拼接);> max_columns → truncated。`current_cell_position=desired+1`。
  - Row end:稀疏行号间隙补 `()` 空行(≤max_rows+1 否则 truncated+停);append `current_row[:max_columns]`。
  - ParseError 分支:artificial EOF 且 source 更大且已见 worksheet → truncated=True(保留已收行!bounded.xml 案:4 数据行+truncated);`not root_checked ∧ size==0` → `"SpreadsheetML XML 为空"`;否则 `"SpreadsheetML XML 格式错误"`。
  - 收尾:未 root_checked → 空;malformed → `"SpreadsheetML XML 索引格式错误"`;未见 worksheet → `"SpreadsheetML XML 没有可预览的工作表"`。
  - 输出:headers=rows[0];body=rows[1:max_rows+1];sheets=(sheet_name,);warning=`"SpreadsheetML 表格预览已按读取或行列上限截断"`。
- C++:自研流式 XML(expat 式事件)忠实复刻;**这是 XML 基建的流式需求来源**(纯 DOM 会丢 boundary 部分行)。

### `_qualified_name` / `_is_spreadsheet_element` / `_attribute` / `_positive_index` / `_cell_text`
- 语义如上;`_positive_index`:int() 失败或 ≤0 → None(int("40") ok;int("4.0") ValueError → malformed)。

### `pptx_preview(resource)`
- `_validate_zip_central_directory` → ZipFile 读 infolist;slides = 匹配 `ppt/slides/slide[1-9][0-9]*\.xml`(fullmatch,非目录)集合大小 → `("幻灯片数", N)`。
- 缩略图:文件名恰为 `docProps/thumbnail.jpeg|png`;重复名(同名多条目)→ `"PPTX 包含重复缩略图条目，已拒绝读取"`;无 → `"PPTX 未发现可用缩略图"`;`file_size>16MiB` → 过大拒读;实际读 16MiB+1 再查 → 实际内容过大拒读。
- `_ArchiveSafetyError` → `"PPTX ZIP 目录不安全: {msg}"`;坏 zip → `"PPTX 包格式错误，无法读取元数据"`。成功 mode=image。
- **ZIP 读取本身依赖 zipfile(C++ 移植 = 自解析 central directory 条目数据;stored 条目直接读,deflate 条目需 inflate——thumbnail 一般 stored/deflate,C++ 需要一个最小 inflate。决策 D9:实现独立的 mini-inflate(fixed+dynamic Huffman,~200 行)或仅支持 stored?真实 pptx thumbnail 由 PowerPoint 写出通常 deflate。oracle 生成器用 Python zipfile 造ZIP_STORED 与 ZIP_DEFLATED 两案;C++ 实现完整 inflate 以对账)**。

### `dfb_preview(resource)`
- `_dfb_sibling`:同目录同 stem 的 .png/.jpg/.jpeg(rank 0/1/2;大小写不敏感后缀;key=(rank, name.casefold(), name) 最小者)。
- sibling:stat>16MiB → `"DFB 同名预览图超过 16 MiB，已拒绝读取"`;读 16MiB+1 同理;OSError → `"DFB 同名预览图不可读"`;成功 mode=image,path=sibling,summary `("预览来源", name)`。
- 无 sibling:自身 mmap 找内嵌图(空文件 → metadata);`_find_embedded_image`:PNG 签名优先全扫描,失败再 JPEG;`_validated_png_range`(逐 chunk:长度、类型字母、CRC32 校验、IHDR 首且 len13、唯一、IEND len0 需已见 IDAT);`_validated_jpeg_range`(完整 marker 状态机:SOI/SOF 组件表校验/SOS 扫描头/熵编码字节扫描/EOI;见源码 636-788 行,逐分支移植)。失败 → `_dfb_metadata(("文件大小", format_size(size)), ("预览状态","仅元数据"))`。
- CRC32(C影响 PNG 校验)需 C++ 自实现(表驱动,~20 行)。

### `zip_preview(resource, max_rows=500)`
- 校验 central directory 后 `heapq.nsmallest(visible_limit+1, names)`(= 排序取前 N+1);truncated=len>limit;rows 单列 `("ZIP 条目",)`;warning=`"ZIP 目录仅显示排序后的前 {N} 个条目，已截断"`。

### `wlp_preview`
- 恒 `"暂不支持 WLP 内置预览"`。

### `_validate_zip_central_directory(path)`(移植核心,483-575 行)
- tail=min(size, 22+65535) 找 EOCD(`_find_eocd`:rfind PK\x05\x06,校验 22+comment_len 恰到 tail 尾);错误文案:`"无法读取 EOCD"/"EOCD 缺失或损坏"`。
- `<4s4H2LH` 解析;multi-disk(`disk≠0∨central_disk≠0∨entries 不一致`)→ `"不支持 multi-disk ZIP"`;0xFFFF/0xFFFFFFFF → `"不支持 ZIP64"`;>10000 条 → `"central entries 超过 10000"`;central_size>4MiB → `"central directory 超过 4 MiB"`;offset 越界/`central_end != absolute_eocd` → `"central directory offset/size 越界"`。
- 逐条目(46B 固定头 `<4s6H3L5H2L`):`PK\x01\x02` 签名、entry_end 越界、ZIP64 entry 标记、`start_disk≠0 ∨ local_offset≥central_offset` → `"entry offset/disk 无效"`;名称解码(flags&0x800 → utf-8 否则 cp437;解码失败 → `"entry 名称编码无效"`,**C++ 需 cp437 解码表**);utf-8 名称总量 >1MiB → `"central 名称总量超过 1 MiB"`;条目数与 EOCD 不一致 → `"EOCD entry count 不一致"`。
- C++:直接 std::ifstream 实现;oracle 用 Python zipfile+struct 补丁造各错误变体(test_fallback_preview 的 `_patch_eocd` 手法)。

## 10. paleo_workbench/resources/preview_parsers/seismic_parsers.py 【只读(segyio)】

- `segyio` 缺失 → `"SEG-Y 预览依赖不可用"`;`field_value` duck-typing 容错取值;体积加载失败 → `"三维体加载失败: {cls}"` 并入 warning(`"; "` 连接)。
- C++ 已有 libs/seismic_io 真读 M3;preview 接线是后续切片。本切片 oracle 只冻依赖缺失分支?否——那是环境产物(decisions D8),不冻;本模块整体不移植。

## 11. paleo_workbench/resources/preview_parsers/well_log_parsers.py 【移植(仅 xml_well_log_preview)→ libs/ingest preview well_log_xml】

### `_UseLasio` / `_lasio_data_table` / `las_preview` 【只读(geoviz/lasio)】
- geoviz 阻塞 import(见 ledger 轮3);不移植不冻 env 产物。

### `xml_well_log_preview(resource, settings) -> PreviewResult|None`
- lxml 优先、stdlib ET 回退(两者对本解析语义一致);解析失败 → **None**(registry 落到 las/spreadsheetml/text)。
- `local_tag`:仅剥 `}` 命名空间(保留大小写!后续比较 `.lower()`)。
- 第一优先:根直属 Worksheet(SpreadsheetML):`ss:Name` 属性(`{urn:...spreadsheet}Name` 或 `ss:Name` 键,缺省 `"工作表"`);Table/Row/Cell/Data 直系遍历取文本(Cell 直下 Data 优先,回退 cell.text);行数达 `max_rows+1` break;`sheet_rows>1` 才成表;s_headers=非空首行 strip;s_data_rows=`rows[1:max_rows+1]` 截到 len(headers)(#897 off-by-one 修复钉);`parsed_sheets` 记录;**首个含 "测井曲线" 子串的 sheet 名** → all_rows 优先。
- all_rows 空则用 parsed_sheets[0]。all_rows 路径:headers 首列 ∈ {井号,Well,WELL_NAME,WELL} → 第一个非空首列作 well_name。
- 仍无 data:WITSML 路径一——`logcurveinfo/curveinfo/curve` 元素的 mnemonic/mnem/name + unit/unitstring + curvedescription/description/desc → curve_infos;`data_headers=mnemonics`;`logdata` 元素:自身 text + `data/row/line` 子文本按行,`re.split(r"[\s,;]+")` 分词,`#`/空行跳,行数 ≤max_rows break(只取第一个有数据的 logdata)。
- 仍无:record 路径——`record/datapoint/logdatapoint/point` 元素的非空子文本 dict(≤max_rows);headers=首行键序。
- `not data_headers and not data_rows → None`。
- curve_infos 兜底:headers 推断单位(DEPTH/深度/TVD/TVDSS→m;含 GR→gAPI;含 DT→us/m;含 孔隙度/POR/PORO→%;含 渗透率/PERM→mD),(name,unit,name)。
- well_name 兜底:stem;`namewell/wellname/well/name` 元素文本 <50 字符取首个。
- summary:`("井名",well_name),("曲线数",len(headers)),("采样点",len(rows))`;table=("曲线","单位","描述") × curve_infos;type_label=`测井数据`;visualization_available=True;sheets 仅 >1 表时。
- C++:完整移植;oracle 用 stub 父包加载真实源码冻结(decisions D2)。

## 12. paleo_workbench/resources/preview_parsers/registry.py 【移植 → libs/ingest preview registry】

### `PreviewRegistry.register_format(fmt, parser)`
- `fmt.lower()` 覆盖注册。C++:函数指针表(本切片无运行时注册需求则表内建;保留 API 形状)。

### `_resolve_project_path(path, project_root)`(**路径穿越拒绝**)
- expanduser;已是文件 → resolve 绝对路径直通;绝对路径直通;相对:root 非空且 ∉ {".",".."} → `(root.resolve()/cand).resolve()`,**不在 root 内 → 放弃解析返回原 candidate**(escape 拒绝);在 → joined。
- C++:std::filesystem weakly_canonical + 前缀判断;oracle 冻结合成路径表(含 ../ 逃逸案)。

### `build_preview(asset, settings, safe_stat_fn, project_root)`(dispatch 全序)
1. ExportArtifact → artifact_preview。
2. project_root 给定且 path 相对 → resolve(可能改写 asset.path)。
3. 文件不存在 → message/`status="missing"`/`"文件不存在"`。
4. 注册表命中 → 注册 parser。
5. 硬编码序:pdf → mode=pdf;**pptx → pptx_preview**;dfb;zip(`max_rows=MAX_ARCHIVE_NAMES`,#896);wlp;**geotiff 先于 image**;IMAGE ∨ type∈{image_reference,reference_map} → image;TABLE → delimiter(tsv=`\t`);EXCEL;LAS;`type=="well_log"`:xml→xml_well_log_preview(非 None)否则 las;SEGY ∨ type=="seismic";HTML → chunk 直读 rich_text(warning 仅显示前 N KiB);MARKDOWN → markdown_rich;JSON;AUDIO;VIDEO;docx;doc;xml → xml_well_log_preview(非 None)→ spreadsheetml_preview(text_limit_kib*1024, rows, cols);dat → dat_preview;TEXT → text_preview;**兜底** `"此格式暂不支持内置阅读，可使用打开目录定位文件"`。
- 注册表互斥:`default_registry()` 单例无注册项时行为=纯硬编码链(生产现状)。C++:实现硬编码链 + 空注册表。
- geotiff/excel/las/docx/segy 依赖缺失回退案全冻结(decisions D8)。

## 13. paleo_workbench/resources/classifier.py 【移植 → libs/ingest classifier】

### `classify_path(path) -> (type, format, status)`
- 后缀小写去点;name=文件名小写;path_parts 各段小写。
- 决策序:las→well_log/indexed;sgy/segy→seismic;geojson→geojson;**json 关键词启发**(name 含 facies/paleo/map/geo → geojson,否则 tabular);shp/gpkg→vector;**dat 分流**:路径段含 td/时深→time_depth;层位→horizon;井分层→well_stratification;井位段或 name 含 wellhead/well_head→well_head;否则 tabular;xlsx/xls→spreadsheet;**xml 分流**:name 含 well/log/测井/曲线/witsml/las 或路径段含 well/log/测井/曲线/井曲线 → well_log;否则 spreadsheet;csv→tabular;pdf/ppt/pptx/docx/doc→document/indexed_reference;图片集→image_reference;dfb 或 name 含 相图→reference_map(ext 空则 "unknown");wlp→well_reference;zip→archive;md/markdown/htm/html→document;音频→unknown;视频→**video**/indexed_reference(注意 video 不在 TYPE_LABELS);兜底 unknown/(ext or "none")/indexed_reference。
- C++:同序 if 链 + UTF-8 子串(中文关键词字节级 strstr 安全,UTF-8 无部分前缀混淆——子串匹配仍按字节,需防跨码点假命中:UTF-8 自同步性保证中文多字节序列不会 match 进 ASCII 边界,oracle 用真实函数冻结)。

### `classify_import_path(path)`
- 后缀 xml:先 `is_well_location_xml` → (well_head,xml,indexed);再 `is_well_log_xml` → (well_log,xml,indexed);**任何异常 → 落回 classify_path**(不可读 vendor XML 仍作通用资源索引)。
- 其余 → classify_path。

## 14. paleo_workbench/resources/io_registry.py 【移植 → libs/ingest classifier(数据表)】

- `TYPE_LABELS`(16 对中英标签;含 "video" 缺失——UI 查 video 会回退原文,保持原样);
- `PREFERRED_IMPORT_EXTENSIONS`(26 个扩展 frozenset);`ROLE_BY_TYPE`(16 对 type→input/reference);
- `CONVERT_LABEL_EXT`(8 对导出标签→后缀);`VIEW_EXPORT_FORMATS`(PNG/SVG/PDF engine 规格,export 用,只读);
- `ExportFormatSpec` dataclass(只读);C++:constexpr 表 + 查询。

## 15. paleo_workbench/resources/scanner.py 【宿主(并发壳)/核移植 classify+sha256】

- `_checksum`=catalog.checksum.sha256_file(Pwb::Domain Sha256 已有等价实现);`default_workers`(governor IO 槽 +2,[2,32],回退 cpu+4);`_process_file`:classify→stat→relativize→summary{size_bytes, checksum_skipped/checksum_error}→ResourceItem(source="scan");`scan_resources`:`rglob` 排序、滤 `._` 前缀、ThreadPool 保序 map、消失文件滤除。
- C++ 本切片:不做并发 walker(宿主层);但 sha256/relativize/classify 的组合语义由 classifier+project_path 移植覆盖。relativize_path 语义(project_dir resolve,内部→posix 相对,外部→绝对+external=True)移植(project_path 模块)。

## 16. paleo_workbench/resources/import_service.py 【只读(catalog 编排)】

- ImportReport 计数/summary_text(`" · "` 连接,Top4 类型标签);`_path_key`(expanduser+resolve posix;相对基于 project.parent);`_filter_new`(路径键去重);`_probe_summary`(size/mtime/extension/type_label;<2MB 文本探针 line_count;json→json_type/feature_count;geojson→geojson_document_summary;错误→geojson_valid=False+geojson_error=类名);`_collect_resource`(geojson_valid 提升 type);`_collect_entry`(显式 vs 目录:非文件/`._`/空文件三种分叉);`_map_collect`(线程池保序);import_files/import_folder=collect→filter→annotate_facies→warnings。
- §7.4 明示不移植入库编目;本模块为 catalog 接线层。findings 供后续切片。

## 17. paleo_workbench/resources/data_asset_registry.py 【只读(外观深模块)】

- FormatSpec(format_id/extensions/resource_type/status/preview_parser/exporter);classify_path=注册表优先否则静态 classify;scan_directory 走静态扫描;parse_preview=注册 parser 优先否则 default_registry().build_preview;export=FormatSpec exporter 否则 converters 表(无 → ExportError `"没有可用于 {label} 的导出器: {format}"`)。单例 `data_asset_registry`。纯编排,无解析语义,C++ 接线层责任。

## 18. paleo_workbench/resources/exporters.py 【只读(导出转换)】

- atomic_output(mkstemp 同目录同后缀+replace);9 个转换器全部依赖 lasio/pandas/PIL/segyio/geoviz;`get_available_formats`(保序去重 label);`extension_for_label`(缺省 ".out")。C++ 转换核不在本切片。

## 19. paleo_workbench/resources/export_service.py 【只读(UI 导出编排)】

- list_asset_export_labels;view_export_capabilities(host 声明优先,duck-type 画布族判定:well_log/cross_well/paleo_map/native_factor_map/unified_map/generic);export_asset_to_path(源文件解析→converter→record_export lineage);export_project_inventory;export_widget_snapshot(PNG/SVG/PDF 分支,SVG 空导出防呆 `"导出的 SVG 不包含任何曲线元素，已中止"`)。Qt 编排层,不移植。

## 20. paleo_workbench/resources/geojson_layers.py 【只读(facies 分组)】

- FACIES_LAYER_SPECS(facies 相 1/subfacies 亚相 2/microfacies 微相 3);role 归一(别名组);文件名推断(别名子串);geojson_document_summary(FeatureCollection 校验、geometry_types 排序去重、显式 role 键 4 个、product id 键 3 个);_group_stem(别名剥离+尾词正则+非 `[0-9a-z\u4e00-\u9fff]`→`-`);_stable_group_id(sha256 前 16 hex);annotate_facies_product_groups(完整组=output+tags 重组;不完整组 warning `"GeoJSON 相图成果组不完整（…）"`)。属 import 编目分组,本切片不移植(依赖 import_service 编排)。

## 21. paleo_workbench/resources/ingest_plan.py 【只读(两阶段计划/执行)】

- Phase1 build_ingest_plan(纯):候选(`._`/空文件滤)、shapefile 家族捆绑(.shp+.shx+.dbf 必需,成员整体收录)、preferred 过滤、classify_import_path、PLAN_HASH_LIMIT=256MiB 上限 sha256、身份提案(WELL_BOUND 类型:XML→geoviz load_xml_preview 井名/LAS→inspect_las_file 井名/目录 LOW 提示→resolve_well 链;SURVEY 按 stem 注册表;horizon/fault→geological file_stem LOW)、重复判定(**同源同 content**(source_uri,sha) 才 skip;内容同源不同≠重复;外部链接同路径只 note)、primary 提案(实体+role 无既有资产的首件)。
- Phase2 execute_ingest_plan(副作用):幂等(已注册 (path,sha)→skip+引用)、as_new_version 绕过幂等、chunk batch_save、绑定(well 直接 id 链接/未解析 bind_well_extracts/survey/geological ensure)、primary upsert。catalog 深层编排骨架,不在本切片。

## 22. paleo_workbench/resources/preview_settings.py 【移植 → libs/ingest preview settings】

### `PreviewSettings`(frozen dataclass,23 字段)
- 全默认值(font_size=12…geoviz_surface_grid_size=256);`_INTEGER_RANGES` 15 组上下界;`_BOOLEAN_FIELDS` 6 个。
- `__post_init__`:density/theme_mode 枚举;bool 严格型;int 严格型(含 bool 排除);范围;pdf_fit_mode ∈ {page,width,custom}。
- `from_mapping`(仅已知键)/`to_mapping`(asdict)/`fingerprint()`(sort_keys+separators=(",",":")+ensure_ascii 的 json → sha256 → 前 16 hex)/`to_geoviz_options`(geoviz 依赖,宿主)。
- C++:结构体+validate+fingerprint(Pwb::Domain Sha256;JSON 规范化需与 Python json.dumps sort_keys 逐字节一致——ensure_ascii=True 时非 ASCII 转 \uXXXX!)。

## 23. paleo_workbench/viz/joint_well_parsers.py 【只读(geoviz 阻塞,不移植)】

- 模块级 `ensure_geoviz_on_path()` + `from geoviz import JointWellId, TimeDepthTable, WellHead` → 本机任何 oracle 环境均不可 import(PySide6 缺,决策 D3)。
- 语义记录(供后续切片):
  - `parse_well_heads(path, identity_registry)`:文本行 ≥7 词,name/x/y/kb/td/bx/by 全 float 否则跳行;SourceWellRecord→registry.reconcile→WellHead 列表;zip(strict)。
  - `parse_td_table(path, well_name=None)`:time=col0,md=col3(≥4 词);井名来自 `# Well :` 注释(left 以 Well 结尾 ∧ right 非空取 right 首词;`# Well :` 无名/`# Well label: check` 不劫持,#430);<2 点 → None。
  - `load_td_tables(dir)`:sorted *.dat;键=(well_name, stem) 双注册;键冲突 warning `"TD 时深表键 '{key}' 冲突：…保留先加载的…"` 且**保留先载**(sorted 序,#430)。
- 依赖 geoviz 数据类构造结果,无法以"真实实现"冻结 → 不移植;其纯文本行解析规则与 well_tops 同族,已在 well_tops 移植中对齐(CRLF/注释/短行/坏 float)。

## 24. 依赖文件(非 §5 但移植直接需要)

- `paleo_workbench/project/paths.py`:`safe_file_stat`(OSError→None)、`is_within_directory`(resolve+relative_to)、`relativize_path`(内部→posix 相对+False;外部→绝对 posix+True)、`resolve_project_path`(相对越界 raise ProjectPathError `f"Relative path escapes project directory: {raw!r} (project_dir=…)"`;空串 raise;绝对直通)→ 移植为 libs/ingest project_path(路径穿越拒绝,§7.3)。
- `paleo_workbench/tokens.py::format_size`:None→"—";≥1MiB→`{v:.1f} M`(非整)或 `{int} M`;≥1KiB→K 同理;否则 `{n} B` → 移植(dfb/zip summary 用)。
- `paleo_workbench/ui/pages/preview_provider.py`:PreviewProvider.preview == default_registry().build_preview(asset, settings);默认 settings=PreviewSettings.defaults() → oracle 以 registry 层为准。

## 25. 测试缺口汇总(oracle 生成器补)

1. well_tops:NaN/inf md、\r 老 Mac 行尾、tokens[6] 非 float(有 tvd 列但坏值)。
2. well_location_xml:坏 XML warning 文案、attrib 覆盖子文本、同 (name,x,y) 去重、100k 上限(跳过——太大;冻 3 条小流即可)、根 attrib CRS 继承、井名 plain-name 仅 Well/井元素、z/uwi 键族、lon/lat 键名不产生 CRS。
3. well_log_xml:worksheet 属性名变体(测井曲线/well log)、"witsml" 子串 vs 集合成员两语义、200k 上限(不冻大流)。
4. preview registry:missing 文件、兜底未知格式文案、zip/pptx/dfb/wlp 回退族、geotiff/excel/las/docx/segy 依赖缺失回退、dat→text 回退、xml→(well_log xml)→(spreadsheetml)→text 三级。
5. spreadsheetml:边界截断保留部分行、malformed 三文案、稀疏 Index、第二 Worksheet 停止、外来命名空间元素忽略。
6. markdown:代码块未闭合、列表类型切换、html 转义五符。
7. json:NaN/Infinity 合法、截断前缀可解析/不可解析两分支。
8. classifier:每条扩展名分支 + dat/xml 内容分流族。
