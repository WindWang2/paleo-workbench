# pwb::science 接口契约 v1（接口握手冻结项的 C 线实现）

> 对应 01-parallel-development.md「接口握手 v1」中 C 行的三项：
> `AlgorithmRequestV1 / ResultV1`、`IResultPublisherV1`、`SelectionEventV1`。
> 命名空间 `pwb::science`，CMake 目标 `Pwb::Science`（libs/algorithms）。
> 头文件是权威：`libs/algorithms/include/pwb/science/*.hpp`。本文是语义说明书。

## 1. 算法描述与参数

~~~cpp
namespace pwb::science {

enum class PortKind : std::uint8_t { volume_f32, grid_f32, well_log, table, path, artifact };

struct PortSpec {              // typed port：输入或输出端口的显式类型
    std::string name;          // "volume"
    PortKind   kind;
    std::string unit;          // SI 或 ""；体积无单位、深度 "m"、时间 "ms"
    bool       required = true;
};

struct ParamSpec {             // 参数：可校验、带单位
    std::string name;          // "win_il"
    enum class Type : std::uint8_t { integer, number, boolean, string } type;
    std::string unit;
    double      minimum = 0;   // 数值域（integer/number 生效）
    double      maximum = 0;
    std::string default_json;  // JSON 字面量；"" = 无缺省
};

struct AlgorithmDescriptor {
    std::string algorithm_id;      // "seismic.coherence_c3"
    std::string version;           // 语义版本（数值结果变更必须升版）
    std::string display_name;
    std::string family;            // "seismic_attribute"（对齐 Python ProviderFamily）
    std::vector<PortSpec>  inputs;
    std::vector<PortSpec>  outputs;
    std::vector<ParamSpec> parameters;
    bool supports_cancel  = false;
    bool deterministic    = true;
    bool approximate      = false; // 幂迭代等近似算法必须标记
    std::string build_identity;    // git sha / 构建标签，入 provenance
};
}
~~~

规则：descriptor 不可变（算法对象每次返回同一份）；`algorithm_id` 命名
`<domain>.<name>`；数值结果语义任何变化必须升 `version`。

## 2. 请求与结果

~~~cpp
struct VersionRef {                // immutable 输入版本引用（对齐 B 线 DataVersionRef 语义）
    std::string asset_id;          // 领域 ID，非文件路径必选
    std::string version_id;
    std::string path;              // 数据落点（可选；由宿主解析）
};

// 数据负载：非拥有视图 + 生命周期句柄。异步执行期间必须存活；
// task runtime 持有 shared guard，算法内禁止跨线程悬挂访问。
struct VolumeView {
    const float* data = nullptr;   // C-order (il, xl, t) 除非 desc 另行声明
    std::array<std::int64_t, 3> shape{0, 0, 0};
    std::array<std::int64_t, 3> strides{0, 0, 0};   // 元素步长
    std::shared_ptr<const void> lifetime;           // 保活句柄（mmap/缓冲所有权）
};

struct AlgorithmRequestV1 {
    std::string request_id;         // 幂等键（空则 runtime 生成 UUID）
    std::string algorithm_id;
    std::string algorithm_version;  // 必须与 descriptor 匹配
    std::map<std::string, std::string> params_json; // 参数（JSON 值）
    std::vector<VersionRef> input_refs;
    std::vector<VolumeView>  input_volumes;         // 按 descriptor 输入端口顺序
};

struct Diagnostic { std::string code; std::string message; std::string severity; };
struct ProducedVolume {             // 结果端口负载（内存形态；落盘由 publisher 决定）
    std::string name; VolumeView volume; std::string unit;
};

struct ProvenanceRecord {
    std::string algorithm_id, algorithm_version, build_identity;
    std::map<std::string, std::string> params_json;
    std::vector<VersionRef> input_refs;
    std::string started_utc, finished_utc;          // ISO-8601
    bool approximate = false;
    std::uint64_t wall_time_ms = 0;
};

struct AlgorithmResultV1 {
    std::string request_id;
    std::vector<ProducedVolume> outputs;
    ProvenanceRecord provenance;
    std::vector<Diagnostic> diagnostics;  // 含 warning（近似/降采样说明）
};
}
~~~

不变量：结果一旦从 `IAlgorithm::run` 返回即不可变；取消/异常路径**从不**构造成功
`AlgorithmResultV1`。

## 3. 执行接口与取消/进度

~~~cpp
struct ProgressReport { double fraction; std::string stage; };
using ProgressSink = std::function<void(const ProgressReport&)>;

class IAlgorithm {
public:
    virtual ~IAlgorithm() = default;
    [[nodiscard]] virtual const AlgorithmDescriptor& descriptor() const = 0;
    // 三种终态：值=成功；AlgorithmError=失败（含校验诊断）；TaskCancelled=取消。
    virtual tl::expected<AlgorithmResultV1, ExecutionOutcome>
    run(const AlgorithmRequestV1&, ProgressSink, std::stop_token) = 0;
};
}
~~~

（`tl::expected` 以仓内最小实现 `pwb::science::expected` 代替，避免外部依赖；
`ExecutionOutcome` = `AlgorithmError{diagnostics}` | `Cancelled{}`。）

语义：
- `std::stop_token` 由 task runtime 注入；算法在可安全暂停的边界轮询
  `stop_token.stop_requested()`（c3：每 inline 一查），收到即返回 `Cancelled`。
- progress 为[0,1]单调不减（弱单调；允许合并）；只在 run 内调用。
- 参数校验失败返回 `AlgorithmError`，diagnostics 携带 code（如
  `param.win_il.not_positive`），不抛 C++ 异常穿边界。

## 4. 结果发布（C 不写数据库）

~~~cpp
class IResultPublisherV1 {
public:
    struct Failure { std::string request_id; std::string code; std::string message; bool cancelled; };
    virtual void publish_success(const AlgorithmResultV1&) = 0;   // → A 的 B-adapter
    virtual void publish_failure(const Failure&) = 0;             // 取消/失败也必须可见
protected:
    ~IResultPublisherV1() = default;
};
}
~~~

规则：一次请求至多一次 `publish_success` 或一次 `publish_failure`；取消 → 只允许
`publish_failure(cancelled=true)`。C 线不 import SQLite/B 线头文件。

## 5. 最小任务状态机（libs/workflow，`pwb::workflow`）

~~~cpp
enum class TaskStatus : std::uint8_t { queued, running, succeeded, failed, cancelled };

struct TaskSnapshot {
    std::string task_id, request_id, algorithm_id;
    TaskStatus  status;
    std::string error_code;        // failed 时
    std::optional<ProgressReport> progress;
    std::vector<Diagnostic> diagnostics;
};
~~~

`TaskRuntime::submit(descriptor-backed algorithm, request, publisher) -> TaskHandle`：
- 单 worker 线程执行（本轮上限 1 并发，符合 2-job 资源门禁）；句柄可 `cancel()`、
  `snapshot()`、`wait()`；
- 状态迁移只允许 queued→running→{succeeded|failed|cancelled}（含 queued→cancelled）；
- 线程安全；进程退出前必须 join（测试覆盖 shutdown 不悬挂）。

## 6. SelectionEventV1（libs/visualization，Qt-free 契约头）

~~~cpp
namespace pwb::viz {
struct DepthRange { double top, bottom; std::string unit; };
enum class DepthDomainKind : std::uint8_t { measured_depth, time };

struct SelectionEventV1 {
    std::string document_id;        // 稳定 domain ID（井/文档），非 widget 地址
    std::string origin;             // 发源视图标识（防反馈环：广播时跳过同 origin）
    std::uint64_t revision = 0;     // 来源文档修订号
    DepthDomainKind domain{};
    DepthRange range;               // 单位必填（"m"/"ms"）
    std::string crs;                // 水平坐标时必填；纯深度选择为空
};
}
~~~

禁止携带：QWidget*/QObject 指针、整数 widget 地址、Python 对象、QGIS 类型。

## 7. 地震数据源接口（libs/visualization）

~~~cpp
namespace pwb::viz {
enum class VolumeAxis : std::uint8_t { inline_, crossline, sample };  // 显式轴序
enum class VolumeOwnership : std::uint8_t { none, owning, mmap };

struct VolumeGeometryV1 {
    std::array<std::int64_t, 3> shape{0,0,0};        // (n_il, n_xl, n_t) 索引空间
    std::array<std::int64_t, 3> strides{0,0,0};      // 元素步长（允许非对称/置换）
    std::array<double,3> origin{0,0,0};              // il0, xl0, t0（物理值）
    std::array<double,3> step{1,1,1};                // 步长（含符号）
    std::string unit;                                // "ms"（sample 轴）等
    float missing_value = std::numeric_limits<float>::quiet_NaN();
    std::endian byte_order = std::endian::native;
    VolumeOwnership ownership = VolumeOwnership::none;
};

class ISeismicVolume {                                // 数据源抽象（#148 兼容位）
public:
    virtual ~ISeismicVolume() = default;
    virtual const VolumeGeometryV1& geometry() const = 0;
    // 三轴切片：输出 span 由调用方提供；禁止内部全卷复制。
    virtual std::size_t read_slice(VolumeAxis axis, std::int64_t index,
                                   std::span<float> out) = 0;  // 越界 → 抛/返回 0 由实现契约定
    // chunk 元数据（secondary layout 扩展位）：本轮 in-memory 返回空。
    virtual std::vector<ChunkInfo> chunk_plan() const { return {}; }
};
}
~~~

契约细节（实现必须遵守，测试逐项覆盖）：
- 索引空间 → 物理值：`origin[axis] + index * step[axis]`；step 可为负。
- `read_slice` 越界索引返回 0 并置错误码（不抛异常穿 C 边界）；out 大小必须等于
  其余两轴乘积。
- 生命周期：`VolumeView.lifetime` shared guard 保活；backend 不得缓存裸指针到请求之外。
- 颜色/范围处理（切片后处理 `map_slice_to_indexed8`）：非有限样本不参与 min/max
  拉伸、渲染为 0；退化范围（常数/全无效）输出全 0 并报告 (0,0)——语义对齐
  native_backend.py `_py_fast_slice_to_indexed8`（oracle 对照对象）。
