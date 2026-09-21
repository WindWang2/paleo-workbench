#include <pwb/workflow_graph/evidence.hpp>

#include "py_text.hpp"

namespace pwb::workflow_graph {

using detail::attr_or_empty;
using detail::attr_str;
using detail::attr_str_or_empty;
using detail::py_repr_string;
using detail::py_strip;
using detail::str_or_empty;
using detail::truthy;
using detail::utf8_code_point;

namespace {

// ---------------------------------------------------------------------------
// Python scalar helpers come from src/py_text.hpp (#1345 — one copy).

// catalog.resolve_version seam — exceptions map to "not resolvable"
// exactly where Python's _resolve_version swallows them.
std::optional<VersionInfo> resolve_version(
    const std::optional<CatalogResolver>& catalog, const std::string& vid) {
    if (!catalog.has_value() || !*catalog || vid.empty()) return std::nullopt;
    try {
        return (*catalog)(vid);
    } catch (...) {
        return std::nullopt;
    }
}

// Python _PREFIX_KINDS — explicit (prefix, kind) pairs; the previous
// kPrefixes[i] -> EvidenceKind(i) relied on implicit enum order (#1345).
constexpr std::pair<std::string_view, EvidenceKind> kPrefixes[] = {
    {"draft:", EvidenceKind::Phase1Draft},
    {"factor:", EvidenceKind::Factor},
    {"prediction:", EvidenceKind::Prediction},
    {"constraints:", EvidenceKind::ConstraintGroup},
    {"version:", EvidenceKind::CatalogVersion},
};

// Python _looks_like_version_id (module-private — internal here, #1345).
bool looks_like_version_id(const std::string& ref) {
    if (ref.rfind("ver_", 0) == 0 || ref.rfind("dver_", 0) == 0) return true;
    // Python len() counts code points.
    std::size_t cps = 0;
    for (std::size_t i = 0; i < ref.size();) {
        const auto d = utf8_code_point(ref, i);
        i += d ? d->size : 1;
        ++cps;
    }
    return cps >= 32 && ref.find('-') != std::string::npos &&
           ref.rfind("sha:", 0) != 0;
}

// verdict.get(key, "") — Python's .get on a non-dict verdict runs OUTSIDE
// the try that maps resolver failures to UNKNOWN, so a malformed verdict
// propagates out of resolve_evidence as AttributeError (#1344).
Json verdict_get(const Json& verdict, const char* key) {
    if (!verdict.is_object()) {
        throw EvidenceAttributeError("'" + detail::py_type_name(verdict) +
                                     "' object has no attribute 'get'");
    }
    // .get(key, "") — a missing key yields "" (not None).
    return verdict.contains(key) ? verdict.at(key) : Json("");
}

// Python's `from ... import resolve_constraint_ref` executes BEFORE the
// try that maps call failures to UNKNOWN — an empty seam is the
// missing-import state, not a call failure (#1343 item 5). Throwing here
// propagates out of resolve_evidence.
void require_constraint_resolver(const ConstraintResolver& resolver) {
    if (!resolver) {
        throw EvidenceImportError(
            "constraint resolver seam not provided "
            "(resolve_constraint_ref unavailable)");
    }
}

}  // namespace

// ---------------------------------------------------------------------------

const char* evidence_kind_value(EvidenceKind kind) {
    switch (kind) {
        case EvidenceKind::Phase1Draft: return "phase1_draft";
        case EvidenceKind::Factor: return "factor";
        case EvidenceKind::Prediction: return "prediction";
        case EvidenceKind::ConstraintGroup: return "constraint_group";
        case EvidenceKind::CatalogVersion: return "catalog_version";
    }
    return "";
}

const char* evidence_status_value(EvidenceStatus status) {
    switch (status) {
        case EvidenceStatus::Resolved: return "resolved";
        case EvidenceStatus::Floating: return "floating";
        case EvidenceStatus::Unpinned: return "unpinned";
        case EvidenceStatus::Stale: return "stale";
        case EvidenceStatus::Missing: return "missing";
        case EvidenceStatus::Unknown: return "unknown";
    }
    return "";
}

std::string EvidenceSelector::str() const {
    return format_evidence_selector(kind, ref_id, version_id, floating);
}

std::string format_evidence_selector(EvidenceKind kind,
                                     const std::string& ref_id,
                                     const std::string& version_id,
                                     bool floating) {
    switch (kind) {
        case EvidenceKind::Phase1Draft:
            return "draft:" + ref_id;
        case EvidenceKind::Factor:
            return version_id.empty() ? "factor:" + ref_id
                                      : "factor:" + ref_id + ":" + version_id;
        case EvidenceKind::Prediction:
            return version_id.empty()
                       ? "prediction:" + ref_id
                       : "prediction:" + ref_id + ":" + version_id;
        case EvidenceKind::ConstraintGroup:
            if (floating || (ref_id.empty() && version_id.empty()))
                return "constraints:current";
            if (ref_id == "current" && version_id.empty()) {
                throw EvidenceValueError(
                    "constraint group named 'current' collides with the "
                    "floating constraints:current reference — pin an "
                    "explicit version");
            }
            return version_id.empty()
                       ? "constraints:" + ref_id
                       : "constraints:" + ref_id + ":" + version_id;
        case EvidenceKind::CatalogVersion:
            return "version:" + (version_id.empty() ? ref_id : version_id);
    }
    return "";
}

EvidenceSelector parse_evidence_selector(const std::string& value) {
    const std::string text = py_strip(value);
    if (text.empty()) throw EvidenceValueError("empty evidence selector");
    if (text == "constraints:current") {
        return EvidenceSelector{EvidenceKind::ConstraintGroup, "", "", true};
    }
    for (const auto& [prefix, kind] : kPrefixes) {
        const std::string p(prefix);
        if (text.rfind(p, 0) != 0) continue;
        const std::string body = text.substr(p.size());
        if (kind == EvidenceKind::Phase1Draft) {
            if (body.empty()) {
                throw EvidenceValueError("draft selector missing layer id: " +
                                         py_repr_string(text));
            }
            return EvidenceSelector{kind, body, "", false};
        }
        if (kind == EvidenceKind::CatalogVersion) {
            if (body.empty()) {
                throw EvidenceValueError(
                    "version selector missing version id: " +
                    py_repr_string(text));
            }
            return EvidenceSelector{kind, body, body, false};
        }
        // body.split(":") — Python keeps empty segments.
        std::vector<std::string> parts;
        std::size_t pos = 0;
        while (true) {
            const auto colon = body.find(':', pos);
            if (colon == std::string::npos) {
                parts.push_back(body.substr(pos));
                break;
            }
            parts.push_back(body.substr(pos, colon - pos));
            pos = colon + 1;
        }
        if (parts.empty() || parts[0].empty()) {
            throw EvidenceValueError("malformed evidence selector: " +
                                     py_repr_string(text));
        }
        if (parts.size() == 1) {
            return EvidenceSelector{kind, parts[0], "", false};
        }
        if (parts.size() == 2 && !parts[1].empty()) {
            return EvidenceSelector{kind, parts[0], parts[1], false};
        }
        throw EvidenceValueError("malformed evidence selector: " +
                                 py_repr_string(text));
    }
    if (looks_like_version_id(text)) {
        return EvidenceSelector{EvidenceKind::CatalogVersion, text, "", false};
    }
    throw EvidenceValueError("unrecognized evidence selector: " +
                             py_repr_string(text));
}

// ---------------------------------------------------------------------------

bool EvidenceResolution::is_usable() const {
    return status == EvidenceStatus::Resolved ||
           status == EvidenceStatus::Floating ||
           status == EvidenceStatus::Stale;
}

Json EvidenceResolution::to_dict() const {
    return Json{
        {"selector", selector.str()},
        {"kind", evidence_kind_value(selector.kind)},
        {"ref_id", selector.ref_id},
        {"version_id", selector.version_id},
        {"status", evidence_status_value(status)},
        {"pinned_version_id", pinned_version_id},
        {"asset_id", asset_id},
        {"display", display},
        {"detail", detail},
        {"quality", quality.is_object() ? quality : Json::object()},
    };
}

namespace {

EvidenceResolution make_res(const EvidenceSelector& sel, EvidenceStatus st,
                            const std::string& pinned = "",
                            const std::string& asset = "",
                            const std::string& display = "",
                            const std::string& detail = "",
                            Json quality = Json::object()) {
    EvidenceResolution r;
    r.selector = sel;
    r.status = st;
    r.pinned_version_id = pinned;
    r.asset_id = asset;
    r.display = display;
    r.detail = detail;
    r.quality = std::move(quality);
    return r;
}

EvidenceResolution resolve_draft(const Json& document,
                                 const EvidenceSelector& sel,
                                 const WorkspaceView* workspace,
                                 const std::optional<CatalogResolver>& catalog) {
    const std::string& layer_id = sel.ref_id;
    std::string display = layer_id;
    const Json layers = attr_or_empty(document, "user_vector_layers");
    if (layers.is_array()) {
        for (const auto& layer : layers) {
            if (attr_str(layer, "id") == layer_id) {
                // str(getattr(layer,"name","") or layer_id) — falsy names
                // collapse to the layer id (#1339).
                display = attr_str_or_empty(layer, "name");
                if (display.empty()) display = layer_id;
                break;
            }
        }
    }
    std::optional<WorkspaceMembership> membership;
    if (workspace && workspace->membership)
        membership = workspace->membership(layer_id);
    if (!membership.has_value()) {
        return make_res(sel, EvidenceStatus::Missing, "", "", display,
                        "草稿图层无工作区成员资格：" + layer_id);
    }
    const std::string pinned = membership->source_version_id;
    if (pinned.empty()) {
        return make_res(sel, EvidenceStatus::Unpinned, "", "", display,
                        "草稿未钉住 RAW 源版本（旧工程或未走 checkout）");
    }
    const auto info = resolve_version(catalog, pinned);
    if (!info.has_value()) {
        if (!catalog.has_value()) {
            return make_res(sel, EvidenceStatus::Unknown, "", "", display,
                            "无目录服务，无法验证钉住的 RAW 版本",
                            {{"identity", "content_fingerprint"}});
        }
        return make_res(sel, EvidenceStatus::Missing, pinned, "", display,
                        "钉住的 RAW 版本不可解析：" + pinned,
                        {{"identity", "content_fingerprint"}});
    }
    return make_res(sel, EvidenceStatus::Resolved, pinned, info->asset_id,
                    display,
                    "草稿（几何为内容指纹身份，输入 RAW 版本已钉住）",
                    {{"identity", "content_fingerprint"}});
}

EvidenceResolution resolve_factor(
    const Json& document, const EvidenceSelector& sel,
    const std::optional<CatalogResolver>& catalog) {
    const Json tasks = attr_or_empty(document, "factor_map_tasks");
    const Json* task = nullptr;
    if (tasks.is_array()) {
        for (const auto& candidate : tasks) {
            if (attr_str(candidate, "id") == sel.ref_id) {
                task = &candidate;
                break;
            }
        }
    }
    if (!task) {
        return make_res(sel, EvidenceStatus::Missing, "", "", sel.ref_id,
                        "单因素任务不存在：" + sel.ref_id);
    }
    // str(getattr(task,"name","") or ref_id) / str(getattr(task,
    // "grid_artifact_version_id","") or "") — falsy values collapse (#1339).
    const std::string name = attr_str_or_empty(*task, "name");
    const std::string display = name.empty() ? sel.ref_id : name;
    const std::string current =
        attr_str_or_empty(*task, "grid_artifact_version_id");
    const std::string version_id =
        sel.version_id.empty() ? current : sel.version_id;
    if (version_id.empty()) {
        return make_res(sel, EvidenceStatus::Unpinned, "", "", display,
                        "插值结果尚未登记版本（保存后登记）");
    }
    const auto info = resolve_version(catalog, version_id);
    if (!info.has_value()) {
        if (!catalog.has_value()) {
            return make_res(sel, EvidenceStatus::Unknown, "", "", display,
                            "无目录服务，无法验证版本");
        }
        return make_res(sel, EvidenceStatus::Missing, version_id, "", display,
                        "钉住版本不可解析：" + version_id);
    }
    if (!current.empty() && current != version_id) {
        return make_res(sel, EvidenceStatus::Stale, version_id, info->asset_id,
                        display, "钉住 " + version_id +
                                     "，任务当前结果版本为 " + current);
    }
    Json quality = Json::object();
    const Json metrics = attr_or_empty(*task, "quality_metrics");
    if (metrics.is_object()) {
        for (const char* key : {"r2", "n_points", "variance_min",
                               "variance_max"}) {
            if (metrics.contains(key)) quality[key] = metrics.at(key);
        }
    }
    const std::string source_kind = attr_str(*task, "source_kind");
    if (source_kind == "mock" || source_kind == "mixed")
        quality["mock_data"] = true;
    return make_res(sel, EvidenceStatus::Resolved, version_id, info->asset_id,
                    display, "", quality);
}

EvidenceResolution resolve_prediction(
    const Json& document, const EvidenceSelector& sel,
    const std::optional<CatalogResolver>& catalog) {
    const Json tasks = attr_or_empty(document, "prediction_tasks");
    const Json* task = nullptr;
    if (tasks.is_array()) {
        for (const auto& candidate : tasks) {
            if (attr_str(candidate, "id") == sel.ref_id) {
                task = &candidate;
                break;
            }
        }
    }
    if (!task) {
        return make_res(sel, EvidenceStatus::Missing, "", "", sel.ref_id,
                        "预测任务不存在：" + sel.ref_id);
    }
    // name/status both go through `or ""` in Python (#1339): a falsy status
    // means "not finished-looking" but Python lets it proceed to UNPINNED.
    const std::string name = attr_str_or_empty(*task, "name");
    const std::string display = name.empty() ? sel.ref_id : name;
    const std::string status = attr_str_or_empty(*task, "status");
    if (!status.empty() && status != "complete" && status != "completed" &&
        status != "done") {
        return make_res(sel, EvidenceStatus::Missing, "", "", display,
                        "预测任务未完成（status=" + status + "）");
    }
    Json quality = Json::object();
    if (attr_str(*task, "adapter_kind") == "mock")
        quality["mock_data"] = true;
    const Json summary = attr_or_empty(*task, "probability_summary");
    if (summary.is_object()) {
        for (const char* key : {"classes", "mean_confidence"}) {
            if (summary.contains(key)) quality[key] = summary.at(key);
        }
    }
    if (sel.version_id.empty()) {
        return make_res(sel, EvidenceStatus::Unpinned, "", "", display,
                        "预测结果为 run 级溯源（无文件版本可钉）", quality);
    }
    const auto info = resolve_version(catalog, sel.version_id);
    if (!info.has_value()) {
        return make_res(sel, EvidenceStatus::Missing, sel.version_id, "",
                        display, "钉住版本不可解析：" + sel.version_id,
                        quality);
    }
    return make_res(sel, EvidenceStatus::Resolved, sel.version_id,
                    info->asset_id, display, "", quality);
}

EvidenceResolution resolve_constraint_group(
    const Json& document, const EvidenceSelector& sel,
    const ConstraintResolver& constraint_resolver) {
    // Python's `from ... import resolve_constraint_ref` runs before the try;
    // an empty seam is ImportError, not an UNKNOWN call failure (#1343-5).
    require_constraint_resolver(constraint_resolver);
    if (sel.floating) {
        Json verdict;
        try {
            verdict = constraint_resolver(document, "constraints:current");
        } catch (const std::exception& exc) {
            return make_res(sel, EvidenceStatus::Unknown, "", "",
                            "地质约束（当前内容）",
                            std::string("约束解析失败：") + exc.what());
        } catch (...) {
            return make_res(sel, EvidenceStatus::Unknown, "", "",
                            "地质约束（当前内容）",
                            "约束解析失败：<non-std exception>");
        }
        static const std::pair<const char*, EvidenceStatus> map[] = {
            {"clean", EvidenceStatus::Floating},
            {"current", EvidenceStatus::Floating},
            {"stale", EvidenceStatus::Stale},
            {"superseded", EvidenceStatus::Stale},
            {"unknown", EvidenceStatus::Unknown},
        };
        // verdict.get(...) is outside the try — non-dict verdicts raise
        // AttributeError, not UNKNOWN (#1344).
        const std::string status_text =
            detail::py_str(verdict_get(verdict, "status"));
        EvidenceStatus st = EvidenceStatus::Unknown;
        for (const auto& [k, v] : map)
            if (status_text == k) st = v;
        return make_res(sel, st, "", "", "地质约束（当前内容）",
                        str_or_empty(verdict_get(verdict, "detail")));
    }
    const std::string raw =
        sel.version_id.empty()
            ? "constraints:" + sel.ref_id
            : "constraints:" + sel.ref_id + ":" + sel.version_id;
    Json verdict;
    try {
        verdict = constraint_resolver(document, raw);
    } catch (const std::exception& exc) {
        return make_res(sel, EvidenceStatus::Unknown, "", "", sel.ref_id,
                        std::string("约束解析失败：") + exc.what());
    } catch (...) {
        return make_res(sel, EvidenceStatus::Unknown, "", "", sel.ref_id,
                        "约束解析失败：<non-std exception>");
    }
    const std::string status_text =
        detail::py_str(verdict_get(verdict, "status"));
    const std::string detail = str_or_empty(verdict_get(verdict, "detail"));
    if (status_text == "missing") {
        return make_res(sel, EvidenceStatus::Missing, sel.version_id, "",
                        sel.ref_id, detail);
    }
    static const std::pair<const char*, EvidenceStatus> map[] = {
        {"clean", EvidenceStatus::Resolved},
        {"current", EvidenceStatus::Resolved},
        {"stale", EvidenceStatus::Stale},
        {"superseded", EvidenceStatus::Stale},
        {"unknown", EvidenceStatus::Unknown},
    };
    EvidenceStatus st = EvidenceStatus::Unknown;
    for (const auto& [k, v] : map)
        if (status_text == k) st = v;
    return make_res(sel, st,
                    st == EvidenceStatus::Unknown ? "" : sel.version_id, "",
                    sel.ref_id, detail);
}

EvidenceResolution resolve_catalog_version(
    const EvidenceSelector& sel,
    const std::optional<CatalogResolver>& catalog) {
    const std::string version_id =
        sel.version_id.empty() ? sel.ref_id : sel.version_id;
    const auto info = resolve_version(catalog, version_id);
    if (!info.has_value()) {
        if (!catalog.has_value()) {
            return make_res(sel, EvidenceStatus::Unknown, "", "", "",
                            "无目录服务，无法验证版本");
        }
        return make_res(sel, EvidenceStatus::Missing, version_id, "", "",
                        "版本不可解析：" + version_id);
    }
    return make_res(sel, EvidenceStatus::Resolved, version_id, info->asset_id,
                    "", info->name);
}

}  // namespace

EvidenceResolution resolve_evidence(
    const Json& document, const EvidenceSelector& selector,
    const std::optional<CatalogResolver>& catalog,
    const WorkspaceView* workspace,
    const ConstraintResolver& constraint_resolver) {
    switch (selector.kind) {
        case EvidenceKind::Phase1Draft:
            return resolve_draft(document, selector, workspace, catalog);
        case EvidenceKind::Factor:
            return resolve_factor(document, selector, catalog);
        case EvidenceKind::Prediction:
            return resolve_prediction(document, selector, catalog);
        case EvidenceKind::ConstraintGroup:
            return resolve_constraint_group(document, selector,
                                            constraint_resolver);
        case EvidenceKind::CatalogVersion:
            return resolve_catalog_version(selector, catalog);
    }
    return make_res(selector, EvidenceStatus::Unknown);
}

EvidenceResolution resolve_evidence(
    const Json& document, const std::string& value,
    const std::optional<CatalogResolver>& catalog,
    const WorkspaceView* workspace,
    const ConstraintResolver& constraint_resolver) {
    return resolve_evidence(document, parse_evidence_selector(value), catalog,
                            workspace, constraint_resolver);
}

std::vector<EvidenceResolution> available_evidence(
    const Json& document, const WorkspaceView* workspace,
    const ConstraintResolver& constraint_resolver) {
    std::vector<EvidenceResolution> out;
    if (document.is_null()) return out;
    if (workspace && workspace->layers_with_role) {
        for (const auto& layer_id :
             workspace->layers_with_role("initial_facies_draft")) {
            // Python builds the selector STRING (f"draft:{layer_id}") and
            // resolves it — parse() path, not a direct EvidenceSelector
            // (#1341).
            out.push_back(resolve_evidence(
                document, "draft:" + layer_id, std::nullopt, workspace,
                constraint_resolver));
        }
    }
    const Json factors = attr_or_empty(document, "factor_map_tasks");
    if (factors.is_array()) {
        for (const auto& task : factors) {
            if (attr_str(task, "status") != "complete") continue;
            // version goes through `or ""` in Python; f"{task.id}" is bare
            // str() (#1339).
            const std::string version =
                attr_str_or_empty(task, "grid_artifact_version_id");
            std::string raw = "factor:" + attr_str(task, "id") + ":" + version;
            while (!raw.empty() && raw.back() == ':') raw.pop_back();
            out.push_back(resolve_evidence(document, raw, std::nullopt,
                                           workspace, constraint_resolver));
        }
    }
    const Json preds = attr_or_empty(document, "prediction_tasks");
    if (preds.is_array()) {
        for (const auto& task : preds) {
            const std::string status = attr_str(task, "status");
            if (status != "complete" && status != "completed" &&
                status != "done")
                continue;
            // f"prediction:{task.id}" — string selector through parse()
            // (#1341); bare str() on the id (no `or` collapse).
            out.push_back(resolve_evidence(
                document, "prediction:" + attr_str(task, "id"), std::nullopt,
                workspace, constraint_resolver));
        }
    }
    const Json constraints = attr_or_empty(document, "constraint_layers");
    if (truthy(constraints)) {
        out.push_back(resolve_evidence(
            document, "constraints:current", std::nullopt, workspace,
            constraint_resolver));
    }
    return out;
}

}  // namespace pwb::workflow_graph
