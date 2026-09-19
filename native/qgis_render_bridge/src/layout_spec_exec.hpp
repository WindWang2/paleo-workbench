// layout_spec_exec — the single layout wire-spec executor (CONV-29 D-02).
//
// Consumes the layout spec JSON produced by the layout-export kernel
// ({"page":{width_mm,height_mm,background},"items":[...]}) and renders it
// through a transient QgsPrintLayout — the layout is never persisted and
// never editable. This TU is the ONE authority for spec → QgsLayout → file:
// it is compiled into the pybind bridge (QgisMapStack::layoutExport
// delegates here) AND into the C++ product chain (pwb::qgis::
// CompositionLayoutService), so the two runtimes can never drift.

#pragma once

#include <functional>
#include <string>
#include <vector>

class QgsMapLayer;
class QgsProject;

namespace pwb::layout_spec_exec {

// Host mirror context: how the executor resolves doc ids and layer order.
// Both hooks are optional — with no hook the executor falls back to
// project-only resolution (qgis layer id / layer name / full tree order).
struct ExecContext {
    QgsProject* project = nullptr;
    // Full-tree top-first layer/doc-id order of the host mirror (the same
    // sequence the screen canvas draws). Empty result or null hook → the
    // executor uses the project layer-tree order.
    std::function<std::vector<std::string>()> order_top_first;
    // Resolves a wire key (host doc id | QGIS layer id | layer name) to a
    // project layer. Null hook → QGIS id/name resolution only.
    std::function<QgsMapLayer*(const std::string&)> resolve_layer;
};

// Executes the spec. format ∈ "pdf"|"svg"|"png". Returns the JSON report
// string {ok,path,format,dpi,items,page_mm[,width_px,height_px]}. Throws
// std::invalid_argument on spec errors and std::runtime_error on export
// failure (the partial file is removed — never-fake contract).
std::string execute_layout_spec(const ExecContext& context,
                                const std::string& spec_json,
                                const std::string& output_path,
                                const std::string& format, double dpi);

}  // namespace pwb::layout_spec_exec
