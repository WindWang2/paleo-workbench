# CPP-A 平台/QGIS 线 — 冻结契约 v1（A0）

> 状态：Frozen（第一轮；跨线握手按协议 §接口握手 v1）
> Owner：A（`feat/cpp-platform-qgis`）。B/C 实现各自头文件时以此语义为准。

## 1. CMake targets（A 拥有并发布）

| Target | 类型 | 职责 | 依赖 |
|---|---|---|---|
| `Pwb::Qgis` | STATIC lib `pwb_qgis` | QGIS runtime（唯一 init/exit）、MapSession（session-owned QgsProject + canvas + layer tree + bridge）、LayerAdapter（domain ID ↔ `pwb/layer_id` custom property）、EditController（start/commit/rollback/undo/redo/snapping/topology）、LayoutService（PNG/PDF/SVG）、StyleService（renderer/labeling XML 读写） | Qt6 Core/Gui/Widgets/Xml/Svg + QGIS imported `qgis_{core,gui,analysis}` |
| `Pwb::ToolPolicy` | INTERFACE-ish STATIC lib `pwb_tool_policy`（Qt-free） | `ToolContextSnapshot`（不可变）+ `evaluate_tool/evaluate_all` 纯函数 + ToolGroups 词表 | 无 Qt、无 QGIS（纯 C++20，可独立单测） |
| `Pwb::Application` | STATIC lib `pwb_application` | ProjectSession 组合根：MapSession + ToolStateReducer + B/C 适配器装配点（`libs/application/adapters/`） | Pwb::Qgis、Pwb::ToolPolicy |
| `pwb-platform` | EXECUTABLE `apps/paleo_workbench_platform` | MainWindow：直接 `QgsMapCanvas` + `QgsLayerTreeView`，无地址桥 | Pwb::* 全部 |

根 CMake 开关：`PWB_BUILD_DATA` / `PWB_BUILD_SCIENCE`（默认 OFF）。ON 而 target 缺失 → configure FATAL_ERROR（禁止 silent skip）。

## 2. MapSession / CanvasHost 生命周期

~~~cpp
namespace pwb::qgis {
class QgisRuntime {            // 进程级，恰好一次
  static void acquire();       // setPrefixPath+init+initQgis；重复调用 abort
  static void release();       // exitQgis；主程序退出前调一次
};
class MapSession {             // session-owned QgsProject
  explicit MapSession(QObject* uiParent);
  ~MapSession();               // §5 关闭顺序；不可复制
  CanvasHost* createCanvas(QObject* parent);   // QgsMapCanvas 白底+AA
  LayerTreeHost* createLayerTree(QObject* parent); // QgsLayerTreeView+model+bridge
  QgsProject* project() const; // 唯一 QGIS 权威工程
};
}
~~~

- 所有权：Qt 对象走 Qt parent；MapSession 持 `std::unique_ptr<QgsProject>`；工具先于画布析构、画布先于工程。
- 无全局单例依赖（`QgsProject::instance()` 不出现在生产代码）。

## 3. EditDeltaV1（A 输出给 B-adapter 的唯一编辑增量）

~~~cpp
namespace pwb::qgis {
struct EditDeltaV1 {
  std::string source_layer_id;      // domain layer ID（pwb/layer_id）
  std::uint64_t base_revision = 0;  // 会话开启时的镜像修订
  std::vector<std::string> added_feature_geojson;    // 新增（含属性）
  std::vector<long long> removed_host_ids;           // 删除（host fid）
  std::vector<GeometryChangeV1> geometry_changes;    // fid → GeoJSON 几何
  std::vector<AttributeChangeV1> attribute_changes;  // fid → {field: value}
};
struct StagedAsset {                // 提交协议落点（B 消费，A 不写 catalog）
  std::filesystem::path geojson_path;   // staged 全量/增量文件
  std::string sha256;
  std::string source_layer_id;
  std::uint64_t base_revision;
};
}
~~~

语义：QGIS edit buffer 是编辑期间唯一几何状态；`commit` 前经拓扑校验，非法 → 拒绝（错误清单返回，缓冲保留）；commit 成功产出 `StagedAsset`（GeoJSON 落临时 staged 目录）+ `EditDeltaV1`。A **不直接写 catalog.sqlite**——由 B 的 CommitRequestV1 通道接收 staged asset。

## 4. 对 B 的 adapter（`libs/application/adapters/`）

A 定义消费接口（B 提供实现；第一轮 A 用测试替身）：

~~~cpp
namespace pwb::application {
struct ProjectSnapshotV1 { /* B 冻结语义；A 只读 */ };
struct LayerBindingV1  { std::string layer_id, asset_id, version_id, kind; };
struct CommitRequestV1 { std::string operation_id; std::string base_version;
                         pwb::qgis::StagedAsset staged; };
struct CommitReceiptV1 { bool ok; std::string new_version, error; };
class IProjectStore {   // B 实现
public:
  virtual std::vector<LayerBindingV1> loadBindings() = 0;
  virtual CommitReceiptV1 commit(const CommitRequestV1&) = 0;
  virtual ~IProjectStore() = default;
};
}
~~~

## 5. 对 C 的 adapter

~~~cpp
namespace pwb::application {
class IResultPublisher {  // C 定义抽象、A 实现到 B 的 adapter
public:
  virtual void publish(/* result assets → B version txn */) = 0;
  virtual ~IResultPublisher() = default;
};
}
~~~

第一轮：A 只保留接口位与测试替身，标注「仅模块验证」；真实 B/C 合入后由本目录接线（集成状态单独记录）。

## 6. ToolPolicy（Qt-free）

- `ToolContextSnapshot`：与 Python `ToolContext`（contract_version=4）同字段集的 C++ 结构（60 字段，含三态 optional bool）。
- `evaluate_tool(tool_id, snapshot) -> ToolAvailability{visible,enabled,checked,disabled_reason,preferred,severity,remediation}`。
- 规则语义 1:1 移植 `paleo_workbench/mapping/tool_availability.py`（门序、阶段 fail-closed、cancel 豁免、checked 派生）；QAction/菜单/快捷键只消费结果，不内嵌规则。
- 本轮 native 路径固定：`native_canvas_available=true`（无 fallback 画布概念），capability manifest 由 `Pwb::Qgis` 编译期/启动探测注入。

## 7. join key（跨线不变量）

沿用现有 QGIS custom property：`pwb/layer_id`、`pwb/version_id`、`pwb/asset_id`、`pwb/kind`（+ 旧栈既有 `pwb/doc_id` 读取兼容）。领域 ID 是唯一连接键；禁止以 QgsMapLayer 指针/QGIS runtime ID 入领域模型。
