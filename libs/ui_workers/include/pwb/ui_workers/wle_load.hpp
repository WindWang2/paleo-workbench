#pragma once

// VIZ-A — production engine load for the well_log worker seam (UI-04
// WellLogLoadFn). Bridges WLE LasSourceAdapter: on success LoadedWellLog::data
// holds std::shared_ptr<const welllog::WellLogDocument> (copyable across the
// JobOutcome GUI hop; consumers any_cast that type and include
// welllog/core/document.hpp themselves). LAS goes through the SDK parser;
// 05 线补齐 XML：识别+解析（well_log_xml_data 纯核）→ WLE 文档装配
// （wle_xml_load.cpp），载荷类型与 LAS 相同。两者之外的资源保持诚实消息
// 路径（viz_resolve 语义），不伪造解析。Built only when the WLE SDK
// participates in the build; without it the seam keeps reporting the engine
// as unavailable.

#include <memory>
#include <string>

#include <pwb/ui_workers/viz_resolve.hpp>

namespace welllog {
class WellLogDocument;
}

namespace pwb::ui_workers {

// The engine payload inside LoadedWellLog::data (any_cast this type). The
// document is the same object graph the well-log dock's load_las builds;
// `diagnostics` carries the SDK's recoverable parse warnings so consumers
// can report data/units/diagnostics consistently across all paths.
struct WleDocumentPayload {
    std::shared_ptr<const welllog::WellLogDocument> document;
    std::size_t diagnostics = 0;
};

// Production load_fn. Reads the file, checks the cooperative cancel token
// before and after parsing, parses through WLE (byte-identical to the
// well-log dock path) or the XML well-log core (05 线), and reports the
// well name (~W scan / XML 显式井名字段；path stem fallback). Unreadable/
// unparseable/non-well files return nullopt; cancellation propagates as
// WellLogLoadCancelled.
WellLogLoadFn make_wle_load_fn();

// XML 分派后端（wle_xml_load.cpp）：bytes 已读入的前提下做识别、解析与
// WLE 文档装配。非井曲线 XML / 语义解析失败 → nullopt；取消 → 抛
// WellLogLoadCancelled。
std::optional<LoadedWellLog> load_well_log_xml(
    std::string_view bytes, const std::string& path,
    const std::function<bool()>& is_cancelled);

}  // namespace pwb::ui_workers
