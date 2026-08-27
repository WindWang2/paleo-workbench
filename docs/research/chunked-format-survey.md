# 百 GB 地震体内部署分块存储格式选型调研（Zarr v3 / HDF5 / 自研 bricklet）

**工单：** WindWang2/paleo-workbench#1068（Wayfinder 地图 #1067 的 research 子工单）
**日期：** 2026-08-27
**状态：** 调研完成（Research Complete）
**边界：** 本报告给出**能力矩阵 + 理论分析 + 推荐排序**；不定案基准数字——量化基准（三向读延迟、压缩系数实测、导入吞吐）是后续「候选格式基准测试」工单的事。本报告末尾列出该基准工单应当验证的具体问题清单。

---

## 1. 问题定义

100 GB float32 地震体（约 250 亿采样点，百万级道数）需要在导入时转换为内部分块格式（ADR 0059 RAW 的派生 DataVersion）。桌面单机（32 GB RAM + NVMe + 消费级 GPU）、无服务端。候选：

1. **Zarr v3**（+ Blosc/LZ4/ZSTD 编解码，含 sharding 扩展）
2. **HDF5**（h5py chunked dataset + filter pipeline）
3. **自研 bricklet 文件**（OpenVDS/VDS 式 brick 存储）

需要覆盖：成熟度与 Python 生态、PySide6 应用内嵌成本、chunk 形状策略、LOD 表达、随机读/顺序扫描、并发读安全、Windows/Linux 一致性、float32 地震数据压缩系数参考。

---

## 2. 仓库现状锚点（访问模式证据）

结论必须服从现有访问模式，先摆事实：

**`geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/loader.py`（现役 SEG-Y 直读器）**
- `read_inline()` 走 segyio `f.iline` 快路径——inline 是第一公民（SEG-Y inline-sorting 的存储顺序红利）；
- `read_crossline()` 结构模式下走 `f.xline`，非结构退化到逐道循环（O(n_il) 次随机寻道）；
- `read_timeslice()` 优先 `f.depth_slice`，不可用时退化为 **O(体积) 的逐 inline 全量扫描**（代码里原话："O(volume) I/O"），且必须挂 cancellation_token 供取消——timeslice 是三向中最痛的方向；
- `read_trace()` 已优化为 stride 直取单道（well-tie / fence 场景，Issue #64）；
- `get_volume_downsampled()` 按步长因子降采样整内存数组，且**只缓存单一 factor**——LOD 需求已显式存在，但没有多分辨率落盘表达。

**`docs/research/segy-async-cache.md`（已实现的双级缓存设计）**
- L1 RAM Slice Cache（512 MB byte budget）+ L2 VRAM Texture Cache（256 MB）；
- `SliceCacheKey` 中含 `downsample_factor` 字段——缓存键层面已经为 LOD 预留了维度；
- **后台预读线程池（P0/P1/P2 优先级）+ 主线程渲染读并发**是设计前提：`threading.RLock` 保护、Generation Token 取消、内存背压。

→ 对存储格式的硬性推论：
1. **多线程并发读是刚需**（预读线程 + UI 线程 + 多视图），且预读的价值依赖于读操作能真正并行；
2. inline 滑动是热路径、timeslice 是最坏方向，chunk 形状必须三向折中；
3. LOD 级别应下沉到存储层（缓存键已有对应槽位）；
4. 单道随机读（well-tie/horizon）必须有可接受的延迟上界。

**Python 版本约束：** 仓库各包 `requires-python = ">=3.12,<3.13"`。zarr 3.3.0 要求 Python ≥3.12（PyPI，2026-07-30 发布）——**版本正好咬合，无冲突**；h5py 3.16.0 要求 ≥3.10，亦兼容。third_party 中的 GDAL/QGIS 已有 HDF5/Zarr 的 C++ 侧驱动链接先例，但与本决策（Python 侧数据通道）无耦合。

---

## 3. 候选能力矩阵

| 维度 | Zarr v3 (+sharding) | HDF5 (chunked) | 自研 bricklet |
| :--- | :--- | :--- | :--- |
| 成熟度（2026-08） | 规范稳定；zarr-python 3.3.0（2025 年大版本重构后持续迭代） | 极高（30+ 年格式历史；h5py 3.16.0） | 无现成件；OpenVDS 规范可参照但非 Python 件 |
| Python 生态 | 一等公民：zarr-python、xarray、TensorStore、zarrs(Rust)、GDAL 驱动 | 一等公民：h5py 官方 wheel（Win/mac/Linux，CPython 3.10–3.14） | 全部自研 |
| 地震行业先例 | **MDIO（TGS）：基于 Zarr 的开源地震格式**，默认 lossless Blosc-zstd | 常用于属性/井数据中间产物；非主流地震体格式 | **OpenVDS/VDS（OSDU 开放规范）**：brick 存储 + LOD 的行业标准 |
| 单文件分发 | 否（目录 store）；shard 可聚成大文件；另有 zip store | **是**（单文件，带外部索引文件的情形少） | 可设计为单文件 |
| 多线程并发读 | **官方设计目标：同进程多线程并发读写线程安全；读无需锁** | 安全但**不并行**：h5py 用解释器级全局锁 `phil` 串行化全部 HDF5 C API 调用 | 自担（mmap 只读天然安全） |
| 多进程只读并发 | 天然安全（无文件锁） | 安全（HDF5 ≥1.10 文件锁，只读共享） | 自担 |
| 压缩编解码 | 内建 Blosc(lz4/zstd/zlib+shuffle)、zstd、gzip、CRC32C 等 codec 管道 | 内建 gzip/shuffle/szip；**zstd/Blosc 需第三方 filter 插件（hdf5plugin wheel）** | 自由（直接链 zstd/blosc C 库） |
| LOD/金字塔 | 无内建，但 group 天然挂多分辨率数组（OME-NGFF multiscales 即该惯例的成熟范式） | 无内建，group 挂多 dataset 自建约定 | OpenVDS 式**原生 LOD 层**（channel+LOD+partitioning 三元组） |
| chunk 形状自由度 | 任意 N-d；shard 内 inner chunk 任意；支持 rectilinear（ZEP 3，MDIO 已用） | 任意 N-d（chunk 为原子 I/O 单元） | 任意（自由设计） |
| 元数据可扩展性 | zarr.json 为 JSON，attributes 自由（dimension_names/units 已入 v3 规范） | attributes/自由，但格式黑盒程度高 | 完全自由 |
| Windows/Linux 一致性 | 纯文件系统语义；**小文件问题用 sharding 收敛** | 官方 wheel 一致；文件锁语义 1.10+ 在 NFS/网盘有已知坑 | 完全自担（大文件 mmap/锁细节） |
| PySide6 嵌入成本 | pip wheel，无原生插件依赖，无服务/守护进程 | pip wheel；如用 zstd/blosc 需加 hdf5plugin 依赖 | 数月级开发 + 永久维护 |
| 主要风险 | zarr-python 高层 API 仍在快速迭代（spec 层稳定） | 全局锁杀死预读并行度；非内建 codec 的插件分发 | 工程量、bug 面、跨平台文件 I/O 细节 |

---

## 4. 逐专题分析

### 4.1 成熟度、Python 生态与嵌入成本

**Zarr v3**
- 规范层（zarr.json + chunk 编码）已稳定，sharding 为已接受的 ZEP 0002；zarr-python 3.x 完整实现 v3 + sharding，并内置 async I/O（zarr.dev 官方发布博客）。
- 生态互操作：xarray 直接读写、Google TensorStore 有 zarr3 driver、Rust 实现 zarrs、GDAL 有 Zarr 驱动（仓库 third_party 里即可见）。这意味着未来 C++ 渲染引擎（geo-viz-engine native 侧）可以脱离 Python 读同一份数据（zarrs / tensorstore 均为候选绑定）。
- **最有力的一手先例：MDIO**——TGS 的开源云原生地震格式，直接构建在 Zarr 之上，默认无损压缩即 Blosc-zstd，并提供针对不同地震数据类型的模板化分块逻辑（MDIO 官方文档/TGS 技术库/《The Leading Edge》2023 论文，Sansal 等）。行业已经替我们趟过「地震体上 Zarr」这条路的格式设计。

**HDF5**
- 成熟度和工具链无可挑剔（HDFView/h5dump/GDAL/QGIS mdal），官方 wheel 覆盖全平台。
- 两个嵌入成本点：① **zstd/Blosc 不是 HDF5 内建 filter**，需要额外依赖 `hdf5plugin` wheel 注册动态 filter——多一个打包/版本协调项；② 大 chunk 随机读必须按数据集调 chunk cache（默认 rdcc 仅 8 MiB@HDF5 2.0+ / 1 MiB@旧版，rdcc_w0=0.75，rdcc_nslots=8191@2.0+），否则 chunk 反复逐出造成数量级的性能塌方（h5py 官方 issue #2568 与 HDF Group 缓存博客的核心结论）。

**自研 bricklet**
- 工业先例 OpenVDS/VDS 证明该设计（brick + LOD + 多 partitioning + chunk 级元数据页）是渲染侧最优解，且已是 OSDU 开放规范（含开源参考实现、PyPI `openvds` 包）。
- 但「自研」意味着：容器文件格式、分块索引、并发控制、编解码接入、损坏恢复、跨平台大文件 I/O、双语言读取端，全部自担。对单机桌面项目这是数月级投入加上无限期维护承诺；而它相对「Zarr v3 sharding + 自建 LOD 约定」的**边际收益很小**（见 4.3/4.5 的映射论证）。
- 若未来确实需要 brick 级能力，**采用 OpenVDS 参考实现/绑定**远优于从零自研——这是本报告对「自研」选项的基本立场。

### 4.2 chunk 形状策略：立方块 vs 沿 inline 板状（理论影响）

**读放大模型（理论推导，非基准）。** 压缩分块存储中，读一张切片必须解压所触碰的全部 chunk。定义读放大系数 A = 实际解压字节数 / 切片有效字节数。对尺寸为 `(ci, cx, ct)`（采样点数）的 float32 chunk，读「垂直于轴 d 的整张切片」时：

```
A_d ≈ (ci × cx × ct) / (该切片在 chunk 内截出的面 × 1) = chunk 沿 d 轴的边长
```

即：**立方块三向放大系数对称（≈边长）；板状块只在法向轴上便宜，其余两向贵一个数量级**。以参考体 4000×4000×1500（≈96 GB float32）算例：

| 候选形状 | 原始 chunk 大小 | inline 切片 A | crossline 切片 A | timeslice 切片 A | 单道读取触碰量 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 立方 128³ | 8 MiB | ~128 | ~128 | ~128 | ~96 MiB（12 个 t 向 chunk） |
| 立方 64³ | 1 MiB | ~64 | ~64 | ~64 | ~24 MiB |
| 板状 (4, 256, 256) | 1 MiB | **~4** | ~256 | ~256 | ~6 MiB |
| 折中 (16, 256, 256) | 4 MiB | **~16** | ~256 | ~256 | ~6 MiB |
| 折中 (64, 128, 128) | 4 MiB | ~64 | ~128 | ~128 | ~24 MiB |

解读：
- **纯板状（1, n_xl, n_t）是 SEG-Y 直读的现状心智，在分块世界里是最差选择之一**：crossline 与 timeslice 的放大系数恶化到 256+，而现状 loader 的痛点恰恰是后两者。
- 立方块把三向延迟拉平——对「inline 热路径 + timeslice 最坏路径」的对称化最优；单道读取（well-tie）是立方块的弱项，但 well-tie 是批量操作且有 LRU 缓存兜底。
- 折中形状（法向 il 略薄，如 `(16~64, 128~256, 128~256)`）可在保住 inline 热路径的同时控制其余两向的绝对字节数。
- **chunk 原始体积建议 ≥1 MiB**（zarr 官方性能指南：使用 Blosc 时未压缩 ≥1 MiB 的 chunk 有更好表现；HDF5 社区同样给出 10 KiB–1 MiB 区间、过大过小皆伤的经验值）。
- **压缩率影响**：chunk 内三维覆盖越完整，shuffle/decorrelation 看到的相关结构越多，压缩率越高——立方块略优于薄板；更关键的变量是 shuffle（按 float32 item 位重排，Blosc 的 shuffle/bitshuffle、Zarr v3 transpose codec 同理）是否开启，其差异大于形状差异。zarr 性能指南明确指出序列化布局由 codec 决定，transpose/shuffle「how well the data compresses depending on the correlation structure within the data」。
- **shard 打包（仅 Zarr v3）**：shard 是 chunk 的容器文件。推荐 shard 取 chunk 的整数倍、目标单文件 ~32–256 MiB（如 64³ chunk × 8³ = 256³ shard = 64 MiB），把 4000×4000×1500 体收敛到 ~1,500 个文件，兼顾 Windows NTFS 小文件开销与 shard 内 range-read 的随机访问能力（ZEP 0002：索引在 shard 尾部，可只取索引再按字节区间读单个 inner chunk）。`subchunk_write_order` 选 morton 增强空间局部性（顺序扫描用 lexicographic 更优）。

**给基准工单的候选集：立方 128³、立方 64³、(16, 256, 256)、(64, 128, 128)，加对照组板状 (4, 512, 512)。**

### 4.3 多分辨率（LOD/金字塔）表达

- **Zarr：** group 下按 2³ 降采样逐级挂数组（`/l0, /l1, /l2, ...`）是零成本自建约定；OME-NGFF 的 multiscales 惯例证明该表达在大规模科学影像生态中成熟可用（ome-zarr/NGFF 文档；image.sc 社区实践）。v3 的 zarr.json 支持 `dimension_names`，坐标语义（inline/xline/t）可直接入元数据。金字塔总体积开销 ~33%（几何级数和）。
- **HDF5：** group 挂多 dataset 完全等价可行；无标准地震金字塔约定，需要自写降采样与命名规范。差异不在能力，在约定的标准化程度。
- **自研：** OpenVDS 式原生 LOD 是三者中表达最完整的（每个 channel+LOD+partitioning 一个 layer，还可以同时存 3D brick 与 2D tile 两套 partitioning 换取切片读加速——官方 Storage Format 文档）。
- **结论：** LOD 三者皆可表达；Zarr 的层级 group + JSON 元数据以最低成本覆盖需求，与 `SliceCacheKey.downsample_factor` 一一对应。OpenVDS 的「多 partitioning 共存」（同一数据既切 brick 又切 tile）是唯一真正超出 Zarr 常规用法的特性——但它同样可以用「同一 group 下挂不同 chunk 形状的两份数组」模拟，代价是双份存储（或只对 LOD≥1 的小体做第二 partitioning）。

### 4.4 随机单道/单体素读 vs 顺序扫描（horizon 追踪、well-tie）

- **随机单道：** Zarr v3 shard 内单 chunk 为一次字节区间读 + 一次解压；一道 1500 样本在 64³ chunk 下触碰 ~24 个 chunk（存在 shard 内则集中在 1–2 个 shard 文件内，page cache 友好）。HDF5 依赖 chunk cache 命中（再次强调 rdcc 调优）。自研 brick 单体素 O(1) 最优。**单道延迟上界由 chunk 体积决定**——这是 4.2 中不选大立方块的第二个理由。
- **顺序扫描（导入转换、全量属性、AI 推理分块遍历）：** 三者都接近 NVMe 顺序盘速。压缩流方面 zstd 解压速度 >10 GB/s（Blosc 官方），远超消费级 NVMe 顺序读——**解压不是顺序扫描瓶颈**。Zarr 的 `subchunk_write_order=lexicographic` 可为顺序批读优化；HDF5 chunk B-tree 顺序遍历成熟。
- **horizon 追踪（沿 inline 面引导的局部随机读）：** 空间局部性要求高——morton 序 shard + 立方/近立方 chunk 提供的局部性最接近 brick 方案。

### 4.5 并发读安全（多视图 + 后台预读线程）——本决策的胜负手

- **Zarr（官方文档原文）**："Zarr arrays are designed to be thread-safe for concurrent reads and writes from multiple threads within the same process"，且并发读无需任何锁（zarr-python 用户指南 Performance 章 / Tutorial）。chunk-per-key 模型使**每个预读线程的 I/O 与解压真正并行**——这正是 `segy-async-cache.md` 的 P0/P1/P2 预读管线想要的效果。
- **HDF5（官方文档原文）**：libhdf5 默认编译 "is not thread-safe"；h5py 通过"interpreter-wide reentrant lock"（`phil`）包住全部 C API 调用来保证安全，代价是官方明言 "multiple calls to the h5py API will not run in parallel"——即使开在两个不同的 dataset/文件上。h5py 3.15+ 对自由线程 Python（3.14t）的支持也**不会禁用 phil**（"protects against race conditions in libhdf5"）。**后果：预读线程与 UI 线程的读在 HDF5 C API 层完全串行化**。I/O 等待期间锁是释放的（可与其他 Python 工作流水线化），所以不是灾难，但解压/C-API 段的并行度归零；h5py 官方对真并行 I/O 的建议是多进程绕行——对单机桌面应用（进程数、内存 32 GB）是笨重的替代。
- **自研：** 自担。mmap 只读 + 原子索引更新是标准做法，但要自己写对。
- **多进程并发（如未来加命令行导入工具与 GUI 同时打开）：** Zarr 只读天然安全；HDF5 ≥1.10 有文件锁、只读共享可行；Windows 本地 NTFS 语义正常，但 NFS/网盘上文件锁有著名的失败模式（h5py #1101 errno 37；缓解：`HDF5_USE_FILE_LOCKING=FALSE` / 1.14 best-effort 锁）。

### 4.6 Windows/Linux 一致性

- **Zarr：** 纯文件系统语义，两端一致。唯一历史性弱点——目录 store 产生海量小文件，在 NTFS（簇开销 + Defender 实时扫描）上性能劣化明显——**被 sharding 直接解决**（ZEP 0002 立项动机即"filesystems hit inode and block-size limits"；示例：2.4 TB / 64³ chunk ≈ 1030 万文件 → 加 shard 后 ~300 文件）。无锁文件、无隐藏状态。
- **HDF5：** 官方 wheel 单文件、跨平台行为一致性好。文件锁自 1.10.0 引入，本地盘两端正常；网盘/NFS 场景需 `HDF5_USE_FILE_LOCKING` / `locking="best-effort"`（仅 HDF5 ≥1.12.1 或 1.10.7+ 可用，h5py File 文档）。桌面本地盘场景风险低。
- **自研：** 大文件 mmap、64 位偏移、写入原子性（先写数据后翻索引）、崩溃一致性等全部细节两端各验一遍——是自研选项最容易被低估的成本。

### 4.7 落盘体积：float32 地震数据压缩系数参考

文献与工程数据交叉核对（均为二手可溯系数，实测留给基准工单）：

| 数据类型 | 无损压缩系数（预期） | 证据 |
| :--- | :--- | :--- |
| 地震振幅道数据（float32，shuffle+zstd） | **~1.5:1 – 2:1** | 地震无损压缩文献共识：Geophysical Prospecting（Røsten 等）"难以显著超过 2:1"；AAPG Explorer：GeoEnergy「essentially lossless」1.5:1–3:1 |
| 通用 float32 数组（zstd + byte-shuffle） | ~3.5x 上限 | Aras Pranckevičius《Float Compression》系列实测；arXiv 2312.10301（bitshuffle+zstd 跨域基准） |
| SEG-Y 道头（int 高冗余） | 30:1 – 1000:1 | SEG-Y 头压缩研究（ResearchGate）——**头段应单独存结构化表，不与振幅同 codec** |
| 业界「4:1 vs SEG-Y」宣传 | 混合格式/位深手段 | SLB 博客 4:1 指替代存储方案总体；MDIO 无损默认 = Blosc-zstd，有损另用 ZFP |
| 有损（ZFP/wavelet，如启用） | 4:1 – 10:1+ | equinor/seismic-zfp、AAPG（有损 5:1–10:1+）；OpenVDS wavelet 分级质量层 |

**落盘体积预算（100 GB 原始 float32）：** 无损基线 **50–65 GB**（1.5–2x）；+ LOD 金字塔 ~33% 开销 → **67–87 GB**。Blosc-zstd（clevel 3–5 + bitshuffle）是 Zarr 侧默认推荐；LZ4 仅在导入吞吐成为瓶颈时作为写速换压缩率的备选（blosc 官方：zstd 比 zlib 压缩率高 ~25%、解压 >10 GB/s；LZ4 解压更快压缩率更低）。baselevel shuffle 对道内相关性敏感——bitshuffle/transpose 按道轴分块的效果应由基准工单实测标定。

---

## 5. 推荐排序与理由

### 🥇 首选：Zarr v3 + sharding + Blosc(zstd/bitshuffle)

1. **并发读是真正的并行**（官方设计的线程安全读、无全局锁）——直接兑现双级缓存 + 后台预读架构的性能模型；这是相对 HDF5 的**结构性优势**，HDF5 的 phil 全局锁无法绕过。
2. **地震行业先例背书**：MDIO（TGS）证明「地震体 + Zarr + Blosc-zstd 无损 + 模板化分块」是可量产的格式设计，其 chunk grid（Regular/Rectilinear，ZEP 3）与元数据模型可直接借鉴。
3. **sharding 一招解决 Zarr 在本地盘的传统短板**（海量小文件），shard 文件 ≈ brick 页、inner chunk ≈ bricklet——以零自研成本获得 brick 方案的主要收益（含 morton 空间局部性、shard 内 range read）。
4. **LOD 零成本表达**（group 挂多分辨率数组，OME-NGFF multiscales 惯例），与 `SliceCacheKey.downsample_factor` 对位。
5. **生态与演进面最好**：xarray/TensorStore/zarrs(Rust)/GDAL 多语言互读（C++ 渲染端未来可绕开 Python 读同一份数据）；zarr-python 3.3.0 要求 Python ≥3.12 与仓库 pin 完全咬合。
6. **嵌入最轻**：纯 pip wheel、无原生 filter 插件、无服务进程。

**风险与缓解：** zarr-python 高层 API 仍在快速迭代 → 访问层封装一个薄协议接口（见 §6），数据层锁定的是稳定的 v3 规范（zarr.json + chunk 编码），必要时可换 zarrs/tensorstore 后端。

### 🥈 备选：HDF5 chunked dataset

单文件分发与工具链是独有优势；本地裸 I/O 基准历史上最快（arXiv 2207.09503：HDF5 最快、Zarr 紧随）。**落选主因**：① h5py 全局锁使预读与 UI 读串行化，掐住本架构最在乎的并发读并行度；② zstd/Blosc 需第三方 hdf5plugin 插件依赖；③ LOD/地震语义元数据全部自建且无生态先例对齐。若最终选它，必须：按数据集调 rdcc（8 MiB 默认远不够切片级随机读）、rdcc_nslots 按 chunk 数 ×10–100 配、只读模式打开以规避文件锁问题。

### 🥉 现阶段不做：自研 bricklet

OpenVDS/VDS 已把 brick+LOD 设计做成 OSDU 开放规范，证明的是「该设计可行且优秀」，而非「值得我们从零重写」。Zarr v3 sharding 已覆盖其 ~80% 的结构性收益；剩余部分（原生多 partitioning、渐进式有损波化解码）在基线需求之外。**重新评估触发条件**：基准工单显示 Zarr/HDF5 三向读均不达标（如 timeslice 首读延迟超预算 2 倍），或产品明确需要 OpenVDS 生态互通——届时优先采用 OpenVDS 参考实现/绑定，而非自研格式。

---

## 6. 对实施的建议（访问层抽象，不改本工单代码）

- 在 `geoviz_seismic` 中定义后端无关的 `BrickStore` 协议（`read_inline/crossline/timeslice/trace/region(level=…)`），`SeismicLoader` 增加导入后体（派生 DataVersion）与 SEG-Y 直读（小体基线，ADR 0059 既有裁决）的双后端分发；缓存层原样复用双级 LRU 与 `SliceCacheKey`。
- 起步参数建议（交基准工单验证后定案）：chunk 三候选 `64³ / 128³ / (16,256,256)`；shard 目标 32–128 MiB；codec `Blosc(cname="zstd", clevel=3~5, shuffle="bitshuffle")`；LOD ≥3 级（2³ 降采样）。
- trace 头与导航元数据（inline/xline 号、坐标、采样率）存 Zarr attributes/独立小数组，不要混入振幅 codec。

---

## 7. 移交「候选格式基准测试」工单的问题清单

1. 三向切片首读/热读延迟 × chunk 形状（§4.2 候选集）× codec（zstd 各 level / lz4）；
2. 单道随机读批量（well-tie 场景，10³–10⁴ 道）吞吐；
3. 顺序扫描（全量遍历 + 导入转换）吞吐与导入耗时；
4. 实际压缩系数（真实工区数据，bitshuffle 开/关、按轴 transpose 效果）与落盘体积（含 LOD）；
5. shard 尺寸扫描（32/64/128/256 MiB）对 NTFS 与 ext4 的影响；
6. 8 线程并发读的加速比（Zarr 预期接近线性；HDF5 预期被 phil 锁钳制——验证 §4.5 的结构性判断）。

---

## 8. 证据来源

**官方文档/规范（一手）**
- ZEP 2 — Sharding codec（已接受）：https://zarr.dev/zeps/accepted/ZEP0002.html —— 小文件动机（2.4 TB→1030 万文件→shard 后 ~300）、shard 内索引与字节区间随机读
- zarr-python 用户指南·Optimizing performance：https://zarr.readthedocs.io/en/latest/user-guide/performance/ —— 线程安全原文、≥1 MiB chunk 建议、shard 权衡、`subchunk_write_order`、transpose/codec 对压缩率的影响
- zarr-python Tutorial（并发读无需锁）：https://zarr.readthedocs.io/en/v1.1.0/tutorial.html
- zarr-python 3 发布博客（sharding 支持、async I/O）：https://zarr.dev/blog/zarr-python-3-release/
- Zarr v3 Blosc codec 规范：https://zarr-specs.readthedocs.io/en/latest/v3/codecs/blosc/
- PyPI zarr 3.3.0（2026-07-30，Python ≥3.12）；PyPI h5py 3.16.0（2026-03-06，Python ≥3.10）
- h5py Multi-threading：https://docs.h5py.org/en/stable/threads.html —— libhdf5 默认非线程安全、`phil` 全局锁、"multiple calls … will not run in parallel"、自由线程不禁用 phil
- h5py File 对象（rdcc_nbytes/rdcc_w0/rdcc_nslots 默认值、locking 参数、HDF5_USE_FILE_LOCKING）：https://docs.h5py.org/en/stable/high/file.html
- HDF Group·Chunking in HDF5（chunk 为原子 I/O 单元）：https://support.hdfgroup.org/documentation/hdf5-docs/advanced_topics/chunking_in_hdf5.html
- HDF Group·HDF5 File Locking（1.10+ 锁语义）：https://support.hdfgroup.org/documentation/hdf5/latest/_file_lock.html ；h5py #1101（NFS errno 37）、h5py #1722（HDF5_USE_FILE_LOCKING）
- h5py #2568（chunk cache 调优对读性能的影响）：https://github.com/h5py/h5py/issues/2568
- OpenVDS Storage Format（brick 2 的幂尺寸 64/128/256、LOD layer、多 partitioning、chunk 元数据页、wavelet 分级质量）：https://osdu.pages.opengroup.org/platform/domain-data-mgmt-services/seismic/open-vds/vds/specification/Format.html
- OME-NGFF multiscales 惯例（Zarr group 多分辨率金字塔范式）：https://ome-zarr.readthedocs.io/en/stable/formats.html

**地震行业先例与压缩系数**
- MDIO（TGS，基于 Zarr 的地震格式，默认 lossless Blosc-zstd）：https://mdio.dev/ 、https://www.tgs.com/technical-library/integrating-energy-datasets-the-mdio-format 、MDIO Python 文档 https://mdio-python.readthedocs.io/en/stable/data_models/chunk_grids.html 、Sansal 等《The Leading Edge》2023：https://pubs.geoscienceworld.org/seg/tle/article/42/7/465/624391
- equinor/seismic-zfp（ZFP 有损地震压缩）：https://github.com/equinor/seismic-zfp
- 地震无损压缩系数共识：Geophysical Prospecting（Røsten/Ramstad/Amundsen，无损难超 2:1）https://onlinelibrary.wiley.com/doi/10.1111/j.1365-2478.2004.00422.x ；AAPG Explorer（essentially lossless 1.5:1–3:1）https://www.aapg.org/news-and-media/details/explorer/articleid/46915/shrinking-seismic-not-an-easy-task ；SEG-Y 头压缩 30–1000:1（ResearchGate）
- 通用 float32 shuffle+zstd 系数：Aras-P《Float Compression》系列 https://aras-p.info/blog/2023/01/29/Float-Compression-1-Generic/ ；arXiv 2312.10301 https://arxiv.org/pdf/2312.10301 ；arXiv 2506.18062 https://arxiv.org/html/2506.18062v1
- Blosc+zstd（解压 >10 GB/s、比 zlib 高 ~25% 压缩率）：https://blosc.org/posts/zstd-has-just-landed-in-blosc/
- SLB 4:1 实践参考：https://www.slb.com/resource-library/blogs/di/solving-the-challenge-of-seismic-data-management

**本地性能对比**
- arXiv 2207.09503《A Comparison of HDF5, Zarr, and netCDF4 in Performing Common I/O》（本地 HDF5 最快、Zarr 紧随）：https://arxiv.org/pdf/2207.09503
- zarr-developers 讨论 #1954（Zarr vs HDF5 本地读写差异个案）：https://github.com/zarr-developers/zarr-python/discussions/1954

**仓库现状（一手）**
- `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/loader.py`（三向读路径现状、O(volume) timeslice 退化、单道 stride 直取、降采样缓存）
- `docs/research/segy-async-cache.md`（双级 LRU、预读管线、SliceCacheKey.downsample_factor、RLock 并发前提）
- 各 `pyproject.toml`（`requires-python = ">=3.12,<3.13"`）
