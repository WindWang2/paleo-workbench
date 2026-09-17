# 13 — decisions：prediction/tiled_onnx → C++ 的非显然选择

每条：决策 + 理由 + 被放弃的备选。按出现顺序编号。

## D1 goal-loop / 路径映射
- prompt 给出的 `/home/kevin/.grok/skills/goal-loop/SKILL.md` 与
  `/home/kevin/projects/paleo_project/main/...` 在本机不存在。实际仓库根 =
  `/home/kevin/project/paleo-workbench`（worktree 放
  `/home/kevin/project/worktrees/cpp-conv-13-prediction-onnx`，与既有
  conv-11/conv-15 worktree 同级）。karpathy 指南实际位于
  `agent/skills/karpathy-guidelines/SKILL.md`（已读）。goal-loop SKILL 缺失 →
  以 prompt §0/§8 为流程规范执行（账本、轮次、禁止提问照办）。
- `docs/development/cpp-conversion-swarm-20/ledgers/` 在 BASE 不存在（conv-15
  worktree 建了空目录未提交）→ 本分支随本切片创建并提交。

## D2 oracle 用临时 venv
- 本机系统 python3（3.14）无 numpy（此前 M6 fixtures 出自别的机器/会话状态）。
  为跑真实 Python 而创建 `/tmp/pwb-oracle-venv`（`python3 -m venv` + pip 装
  numpy 2.5.3 + pydantic）。不重编 QGIS vendor、不改系统包。生成器是唯一
  消费者，README 注明用法。备选：pip --user（污染系统）、pur 环境重建（超
  本切片范围）。

## D3 oracle 的 stub 接缝：monkeypatch `_make_session` + 假 zarr，其余全真
- `run_tiled_inference` 是被测对象本体；仅两处环境不可复现：
  (a) `onnxruntime` 会话 → StubSession 从 `_make_session` 接缝注入；
  (b) zarr 存储 → `sys.modules['zarr']`/`['zarr.codecs']` 换成内存替身
  （slice 赋值 + 按 path 复用，镜像 zarr 追加打开语义）。
  tile 循环、resume marker、fsync、cancel 协议、零填充、center-crop 裁剪、
  softmax/sigmoid、fp16 量化、stats dict 全部是真实产品代码跑出来的。
  备选（放弃）：在生成器里重写 tile 循环 —— 那是"测试自己实现自己"，不是
  对账。
- 假 zarr 的 `create_array` 需要 `mkdir(parents=True)`（真 zarr 会建父目录，
  首跑踩过 FileNotFoundError）。

## D4 stub 算子：可分离二项式平滑（而非 pytest 的 1/27 卷积）
- pytest 用 3×3×3 全 1/27 核（真 ORT 执行）。1/27 非二进制分数，求和顺序与
  FMA 收缩都会引入顺序相关舍入，C++ 无 ORT 无法逐位对账 → 改用逐轴
  `0.25*L + 0.5*C + 0.25*R` 可分离核（等效 (1,2,1)⊗³/64，感受野同为 3）：
  每个乘积是精确的指数移位，两次加法按固定左结合顺序 → C++ 用同表达式同
  顺序可**逐位一致**。生成器内建 selfcheck 断言标量循环与 numpy 向量化
  （含 NaN，`equal_nan=True`）位级相等。
- 教训（记录供后来者）：`np.array_equal` 默认 `equal_nan=False` —— 首轮
  "不一致"全是 NaN 用例假阳性。
- C++ 侧该 TU 以 `-ffp-contract=off` 编译（禁 FMA 收缩），否则逐位一致性
  不成立。
- 每类 stub 对应 pytest 的真实模型：sign ↔ `_sign_model`（感受野 1）；
  conv2 ↔ `_conv_model`（感受野 3、重叠敏感）；conv3/sigmoid1 覆盖
  多类 softmax 与 C=1 sigmoid 展开路径（pytest 未覆盖 C≠2，oracle 补上）。

## D5 argmax/NaN/平局语义
- numpy argmax：首最大；通道含 NaN 时 NaN 视为最大、落在首个 NaN 通道
  （探针验证 2.5.3）。C++ argmax 逐通道扫描，遇 NaN 立即胜出，否则严格
  大于才替换（平局保前）。`conv3_ties` 冻结了 c=1/2/2.5 三个精确平局
  （二进制分数构造），`sigmoid1_half` 冻结 0.5 平局 → 类 0。
- `seg.max` 传播 NaN → fp16 NaN。JSON 里非有限值以 "NaN"/"Inf"/"-Inf"
  字符串表示（pwb Json 解析器不必支持裸 NaN 字面量）。

## D6 fp16 对账容差
- 冻结的是 Python 侧量化后的 fp16 值。C++ 的 fp32 概率若与 Python 差
  ~1 ulp（exp 实现差异），fp16 舍入可能跨舍入边界差 1 fp16 ulp。
  容差 = `4e-4 + 2^-9 * |want|`（≈1 fp16 ulp）+ 两侧 NaN 互相承认。
  classmap uint8 **必须逐体素相等**（stub 的 logit 间隔远大于 exp 噪声，
  见 D4/D5；平局只发生在精确相等的 bit 上，两侧一致）。
- 备选（放弃）：冻结 fp32 概率再比较 —— Python `_softmax` 之后立刻
  astype(float16)，中间 fp32 无从落盘。

## D7 不移植资源预算钳制（run 内 `_max_batch` 批量收缩）
- `active_budget().streaming_buffer_bytes` 依赖机器 RAM 探测/env（#1081
  运行时守卫），不是切块/重叠/拼回几何契约的一部分；本机 62 GiB → 5 GiB
  预算下所有 oracle 用例都不触发。C++ 数值核不含此守卫；接入运行时预算
  属 platform/runtime 后续切片（软警告 + 收缩，无正确性影响）。
- 对比：`_validate_softmax_budget`（#1187）是纯 (batch, classes, tile)
  函数且报错文案用户可见 → **移植**（6 个冻结用例，含 ==预算边界两侧）。

## D8 Session/Reader 接缝形态（C++）
- C++ 无 monkeypatch → 把 Python 代码里 duck-typed 的 session/reader 提为
  两个最小抽象：`ISession::run(Tensor5)->SessionOutput`（可返回错误秩以
  复刻 ndim 诚实错误）与 `IReader::shape()/read_voxel_window(...)`。
  `input_name/output_name/get_providers` 是 ORT dict 协议细节，对几何契约
  无意义，不进接缝。
- ONNX Runtime 接线：CMake 里 `find_package(onnxruntime CONFIG QUIET)` +
  `PWB_PREDICTION_WITH_ORT` 缓存变量，**本切片不写 ORT 适配 TU**（本机无
  ORT，写了即无编译/测试覆盖的 bitrot）。真实模型路径留给接线切片；
  ISession 即为其契约。此决定如实记录，不假装"已支持 ORT"。

## D9 恢复语义的存储形态（C++）
- Python 把 classmap/probmap 写 zarr、跨进程持久。C++ 核改为调用方传入
  全尺寸 `span<uint8_t>` / `span<uint16_t>`（fp16 位型）缓冲 + `work_root`
  目录（tiles.done marker 仍落真实文件系统 + fsync）。恢复 = 调用方保留
  缓冲再次调用，与 oracle 的 resume 用例同构。zarr 分片/压缩是存储层细节，
  不属数值契约。
- 取消返回值：Python cancelled dict 无 `model_binding` 键 → C++
  `TiledRunResult::binding_present=false` 且冻结该差异（取消 ≠ 完成的
  协议可辨性，#1167）。

## D10 错误文案中的路径归一化
- 冻结的报错文案含临时目录绝对路径 → 生成器把 temp 根替换为 `<WORK>`，
  C++ 测试把自己的临时根代入后再逐字节比较。文案其余部分（含
  `(N,C,64,128,128)`、`refusing to silently clamp` 等）逐字冻结。

## D11 providers.py 既有死代码不修
- BASE `providers.py` 529–558 行：第一个 `unregister_provider` 体内 return
  后跟着不可达的旧 register 体，555 行第二个模块级同名 def 覆盖前者（语法
  合法、行为相同）。超本切片写入范围（§6 只允许 libs/prediction + CMake
  CONV-13 + oracle + ledgers），只记录不修。

## D12 移植范围切割
- **进 C++（libs/prediction）**：tile_starts、authoritative_range、
  validate_softmax_budget、模型文件门（suffix/size/env cap，sha256 由调用
  方冻结注入）、looks_like_oom（含 Python `or/and` 优先级）、批量半退避、
  tiles.done 恢复协议、零填充 + center-crop 拼回、softmax/sigmoid 转换、
  fp16 量化、stats/cancel 协议、进度回调接缝。
- **不进（胶水，后续切片）**：TiledOnnxProvider 参数装配/catalog 持久化、
  `_verify_model_identity` 模型身份绑定（catalog ModelVersion 依赖）、
  zarr 落盘、inference_service 生命周期、input_contract、在线客户端、
  viz/UI。
- 理由：§4 的用户流程验收 = "一张小 2D 网格按同一 tile/halo 策略切块拼
  回，C++ 与 Python 逐格一致" —— 几何 + stub 对账即可闭环；胶水层需要
  catalog（M4 线）与平台接线，混入会破坏 Qt-free 核边界。

## D13 OOM 退避的 sleep 契约
- Python `time.sleep(0.5/current_batch)`（半退避后 0.25s+0.5s，oom_halving
  用例实耗 ~0.75s）。C++ 同样 `std::this_thread::sleep_for`。保持一致性
  优先于测试提速；如未来成瓶颈，先改 Python 再同步两侧。

## D14 测试目标名与布局
- `libs/prediction/`（`pwb_prediction` 静态库，Qt-free、numpy-free；唯一库
  依赖是 `Pwb::Domain`，复用其与 hashlib 字节一致的 Sha256，见 findings
  §17；fp16 为自带 RNE 位运算）+ `libs/prediction/prediction_tests/`
  （可执行 `prediction.tiled_stub`，fixture 经编译宏注入）—— 完全镜像
  mapping_kernel 的既有约定。根 CMakeLists 仅追加 `# BEGIN CONV-13` 块
  （option `PWB_BUILD_CONV_13`），不动其他块。

## D15（审核轮 1 产物）会话输出空间维度守卫 —— 有意的忠实性偏差
- Python `_run_tile_group` 对会话返回的错误空间维度（D'H'W' ≠ tile）会
  静默继续：numpy 切片越界**钳制**而非报错，产出错误但不崩溃的拼图。
  C++ 同样情形是越界读（UB）。移植在裁剪前加一行诚实检查
  （"model output tile shape (...) does not match the input tile (...)"）
  —— Python 行为是缺陷不是契约（从未被任何测试/文档声明），不复制。
  冻结 oracle 无此用例（stub 会话恒返回匹配维度），偏差已在此记录。

## D16（审核轮 3 产物）`looks_like_oom` 不导出
- Python 里 `_looks_like_oom` 是模块私有函数；C++ 同样收进实现文件的
  匿名命名空间，头文件只暴露切块/拼回契约真正需要的符号
  （tile_starts / authoritative_range / validate_softmax_budget /
  check_onnx_model_file / run_tiled_inference / 会话与读取器接缝 /
  TiledInferenceError）。

## D17 nlohmann/JSON 的 NaN 与占位符
- Python json.dump 默认写出裸 `NaN` 字面量，nlohmann 拒绝解析 → fixture
  中一切非有限 float32/fp16 值统一编码为 "NaN"/"Inf"/"-Inf" 字符串
  （体积数据与 probmap 同法）。`<WORK>` 占位符（D10）同理保证 C++ 端
  nlohmann 解析 + 逐字对账可行。

