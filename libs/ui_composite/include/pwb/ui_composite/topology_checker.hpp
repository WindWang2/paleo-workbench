#pragma once

// Port of paleo_workbench/mapping/topology_checker.py (UI-13): 拓扑检查
// 器宿主面（拓扑编辑迁移 M4 §5）。
//
// Bridge run_geometry_checks / fix_geometry_error results + double
// exemptions (ignore list, gap whitelist) + save-gate filtering. The
// workspace margin comes back from the bridge's own rules.
//
// The bridge itself is an injected seam — run/fix accept callback
// functions so the QGIS target wires native geometry checks and tests
// stub them; state (ignore/exemptions/persist) is pure and bridge-free.
// Qt-free.

#include <array>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// 忽略身份：规则 + 层 + 要素 + 对方要素（不依赖一次运行的临时 id）。
using IgnoreKey = std::array<std::string, 4>;
IgnoreKey ignore_key(const Json& error);

// Bridge call signatures (the stack/canvas pair collapses into a single
// host-injected callable taking the config/error payloads):
//   run:   config Json → raw payload (Json object or JSON text)
//   fix:   (error_id, method) → payload
//   fix_all: (error_ids, method) → payload
using RunGeometryChecksFn = std::function<Json(const Json&)>;
using FixGeometryErrorFn =
    std::function<Json(const std::string&, int)>;
using FixGeometryErrorsFn =
    std::function<Json(const std::vector<std::string>&, int)>;

// 上次检查结果 + 豁免 + 桥运行/修复。
class TopologyChecker {
public:
    TopologyChecker() = default;

    std::vector<Json> last_errors;
    std::optional<std::string> last_run_at;  // ISO-8601 UTC
    std::optional<Json> workspace;           // bridge-side margin config
    std::vector<Json> allowed_gaps;          // gap whitelist geometries

    // -- 豁免 --------------------------------------------------------------
    void ignore(const Json& error, const std::string& reason = "");
    void restore(const Json& error);
    bool is_ignored(const Json& error) const;
    std::set<IgnoreKey> ignored_keys() const;

    void add_allowed_gap(const Json& geometry);

    // blocking_errors: non-ignored errors from `errors` (or last_errors
    // when nullopt) — save-gate input.
    std::vector<Json> blocking_errors(
        const std::optional<std::vector<Json>>& errors =
            std::nullopt) const;

    // persist/restore_state: exemption + workspace state for project
    // documents (纯数据 round-trip).
    Json persist() const;
    void restore_state(const Json& snapshot);

    // -- 运行 --------------------------------------------------------------
    // run: execute the injected bridge checks with the composite rule
    // config (overlap/gap/is_valid/workspace_remainder/dangle,
    // precision=8) + workspace/allowed_gaps merge + extra_config; stores
    // last_errors/harvested allowed_gaps/last_run_at. Throws
    // std::runtime_error when no run seam is installed.
    std::vector<Json> run(const std::vector<std::string>& layer_ids,
                          const Json& extra_config = Json());

    // run_for_commit: 保存前自动全量检查；返回未忽略错误（门禁输入）。
    std::vector<Json> run_for_commit(
        const std::vector<std::string>& layer_ids);

    // fix / fix_all: route through the injected fix seams; refresh
    // last_errors when the payload carries an error list.
    Json fix(const std::string& error_id, int method = 0);
    Json fix_all(const std::vector<std::string>& error_ids,
                 int method = 0);

    // Seam installation (host wires the bridge; tests stub).
    void set_run_fn(RunGeometryChecksFn fn) { run_fn_ = std::move(fn); }
    void set_fix_fn(FixGeometryErrorFn fn) { fix_fn_ = std::move(fn); }
    void set_fix_all_fn(FixGeometryErrorsFn fn) {
        fix_all_fn_ = std::move(fn);
    }

private:
    std::map<IgnoreKey, std::string> ignored_;
    RunGeometryChecksFn run_fn_;
    FixGeometryErrorFn fix_fn_;
    FixGeometryErrorsFn fix_all_fn_;
};

}  // namespace pwb::ui_composite
