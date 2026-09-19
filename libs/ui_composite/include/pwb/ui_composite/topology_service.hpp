#pragma once

// Port of paleo_workbench/mapping/topology.py (UI-13): map-layer
// topology validation + per-layer cached error counts.
//
// Python's validation engine prefers the QGIS bridge (geometry.validate /
// validate_many) with a Shapely fallback. In C++ the engine is an
// injected seam — the QGIS target installs a QgsGeometry-backed
// validator; tests install stubs; absence of every engine produces the
// same "validator_unavailable" issue record Python emits when neither
// bridge nor shapely is importable.
//
// Qt-free.

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

class TopologyChecker;  // topology_checker.hpp

// Single-geometry validity verdicts: geometry → message list
// ([] = valid). Batch variant processes a vector in one shot.
using GeometryValidateFn =
    std::function<std::vector<std::string>(const Json&)>;
using GeometryValidateManyFn = std::function<std::vector<
    std::vector<std::string>>(const std::vector<Json>&)>;

// Host geometry validation + checker holder. Shared-vertex Python
// propagation retired in M5 (native vertex topological editing + gesture
// manager).
class TopologyService {
public:
    explicit TopologyService(bool enabled = false);
    ~TopologyService();
    TopologyService(TopologyService&&) noexcept;
    TopologyService& operator=(TopologyService&&) noexcept;
    TopologyService(const TopologyService&) = delete;
    TopologyService& operator=(const TopologyService&) = delete;

    bool enabled;

    // M4 §5：analysis 检查器结果 + 双豁免（owned, lazily同 Python 属性）。
    TopologyChecker& checker();
    const TopologyChecker& checker() const;

    // -- validator seams -----------------------------------------------------
    // Install the single-geometry engine (QGIS target: QgsGeometry;
    // tests: stub). nullptr mirrors "bridge/shapely unavailable".
    void set_validate_fn(GeometryValidateFn fn);
    void set_validate_many_fn(GeometryValidateManyFn fn);
    bool has_validator() const { return static_cast<bool>(validate_); }

    // -- V9 W2：运行时拓扑错误计数（merge 门禁的事实生产者） -------------------
    // 每图层最近一次校验的错误计数。键 = layer id，值 = (data_revision,
    // session_revision, count, session 身份)。只在有界刷新点写；上下文
    // 采集只读缓存——帧级链不做 O(要素) 校验。会话对象身份入键值：回
    // 滚/提交后新建的会话即使 layer id 相同也不继承旧计数。
    void record_validation(const VectorLayer& layer, int error_count);
    // 校验一层并记录（有界刷新点）；返回错误数。
    int refresh_error_count(const VectorLayer& layer);
    // 各活跃编辑会话最近一次校验的错误数之和（缓存读，O(层数)）。
    // 语义与 save 时校验门禁一致：从未校验过 = 0；同一会话内校验后又
    // 编辑 → 保持最近已知值直到下一刷新点；会话终结或换新会话对象后
    // 不计入（按未知处理，门不拦）。
    int cached_error_count(const std::vector<const VectorLayer*>& layers)
        const;
    void forget_error_count(const std::vector<std::string>& layer_ids);
    void forget_all_error_counts();

    // -- validation -----------------------------------------------------------
    // validate: issues across layers (session features when editing,
    // committed otherwise) — {"severity","layer_id","feature_id",
    // "message"} records.
    std::vector<Json> validate(
        const std::vector<const VectorLayer*>& layers) const;

    // validate_records: (feature_id, geometry) record sets — native edit
    // session geometry facts read back from the mirror (no Python
    // session/layer objects available). Batch path when the engine
    // supports it; batch failure falls back per-record with the same
    // diagnostics discipline as Python (report once, then degrade).
    std::vector<Json> validate_records(
        const std::string& layer_id,
        const std::vector<Json>& records) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    GeometryValidateFn validate_;
    GeometryValidateManyFn validate_many_;
};

// repair_invalid_geometry: auto-heal invalid Polygon/MultiPolygon
// geometries (ring closure first, then the injected repair backend —
// QGIS makeValid/orient equivalent). Without a backend the ring-closed
// geometry is returned unchanged (Python shapely-ImportError path).
using GeometryRepairFn = std::function<Json(const Json&)>;
Json repair_invalid_geometry(const Json& geometry,
                             const GeometryRepairFn& backend = nullptr);

}  // namespace pwb::ui_composite
