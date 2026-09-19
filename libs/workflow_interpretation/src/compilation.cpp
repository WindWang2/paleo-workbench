// compilation.cpp — C++ port of
// paleo_workbench/workflow/interpretation/compilation.py (CONV-32, task
// I7). Python is authoritative: message text (including the '；' refusal
// separators and the fullwidth '：' colons), key order, and control flow
// are ported verbatim. See include/pwb/workflow_interpretation/
// compilation.hpp for the seam mapping.

#include <pwb/workflow_interpretation/compilation.hpp>

#include <pwb/workflow_runtime/constraint_versions.hpp>

#include <map>
#include <stdexcept>

namespace pwb::workflow_interpretation {

namespace {

using workflow_graph::EvidenceKind;
using workflow_graph::EvidenceStatus;
using workflow_graph::evidence_kind_value;
using workflow_graph::evidence_status_value;
using workflow_graph::parse_evidence_selector;
using workflow_graph::resolve_evidence;

// ---------------------------------------------------------------- helpers
// Python truthiness over a Json value (mirrors the evidence.cpp helper).
bool truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get<std::string>().empty();
    return !v.empty();
}

// Python str() over a Json scalar (null → "" — unreachable through the
// `or ""` guards that precede it at every call site below).
std::string py_str(const Json& v) {
    if (v.is_null()) return "";
    if (v.is_string()) return v.get<std::string>();
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_unsigned())
        return std::to_string(v.get<unsigned long long>());
    return v.dump();
}

// str(value or "") — falsy → "".
std::string str_or_empty(const Json& v) {
    return truthy(v) ? py_str(v) : std::string();
}

// str(value) — Python str(None) == "None" (no `or` guard).
std::string str_strict(const Json& v) {
    return v.is_null() ? std::string("None") : py_str(v);
}

// getattr(obj, key, None) → Json (missing → null sentinel).
Json attr_or_null(const Json& obj, const char* key) {
    if (!obj.is_object() || !obj.contains(key)) return Json(nullptr);
    return obj.at(key);
}

// getattr(obj, key, "") or "" → str.
std::string attr_str(const Json& obj, const char* key) {
    return str_or_empty(attr_or_null(obj, key));
}

// getattr(document, key, None) or [] — the array-ish document sections.
// Non-array carriers cannot occur through the documented Json seam
// (Python would iterate them degenerately); normalized to empty here.
Json attr_or_array(const Json& obj, const char* key) {
    const Json v = attr_or_null(obj, key);
    return v.is_array() ? v : Json::array();
}

// Python "；".join(parts) — fullwidth semicolon separator, verbatim.
std::string join_fullwidth(const std::vector<std::string>& parts) {
    std::string out;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i != 0) out += "；";
        out += parts[i];
    }
    return out;
}

// Python _parses — parse success probe (ValueError → false).
bool parses(const std::string& selector) {
    try {
        parse_evidence_selector(selector);
        return true;
    } catch (const workflow_graph::EvidenceValueError&) {
        return false;
    }
}

}  // namespace

// ------------------------------------------------------------------ context

ResolveContext ResolveContext::for_repository(
    workflow_runtime::CatalogRepository* repository) {
    ResolveContext ctx;
    ctx.repository = repository;
    if (repository != nullptr) {
        // Present catalog backed by the repository (absent stays nullopt).
        ctx.catalog = [repository](const std::string& version_id)
            -> std::optional<workflow_graph::VersionInfo> {
            const auto version = repository->resolve_version(version_id);
            if (!version.has_value()) return std::nullopt;
            return workflow_graph::VersionInfo{version->asset_id,
                                               version->name};
        };
    }
    // Constraint verdicts always route through resolve_constraint_ref; the
    // null repository reproduces Python's catalog=None behavior.
    ctx.constraint_resolver =
        [repository](const Json& document, const std::string& ref) {
            return workflow_runtime::resolve_constraint_ref(document,
                                                            repository, ref);
        };
    return ctx;
}

// -------------------------------------------------------------------- entry

Json CompilationInputSetEntry::to_dict() const {
    Json out = Json::object();
    out["selector"] = selector;
    out["label"] = label;
    out["evidence_kind"] = evidence_kind;
    out["pinned_version_id"] = pinned_version_id;
    out["resolved_asset_id"] = resolved_asset_id;
    out["added_at"] = added_at;
    out["added_by"] = added_by;
    out["note"] = note;
    out["status_at_add"] = status_at_add;
    return out;
}

CompilationInputSetEntry CompilationInputSetEntry::from_dict(
    const Json& data) {
    CompilationInputSetEntry entry;
    entry.selector = attr_str(data, "selector");
    entry.label = attr_str(data, "label");
    entry.evidence_kind = attr_str(data, "evidence_kind");
    entry.pinned_version_id = attr_str(data, "pinned_version_id");
    entry.resolved_asset_id = attr_str(data, "resolved_asset_id");
    entry.added_at = attr_str(data, "added_at");
    entry.added_by = attr_str(data, "added_by");
    entry.note = attr_str(data, "note");
    entry.status_at_add = attr_str(data, "status_at_add");
    return entry;
}

// ---------------------------------------------------------------------- set

const CompilationInputSetEntry* CompilationInputSet::entry_for_selector(
    const std::string& selector) const {
    for (const auto& entry : entries) {
        if (entry.selector == selector) return &entry;
    }
    return nullptr;
}

std::vector<std::string> CompilationInputSet::selectors() const {
    std::vector<std::string> out;
    out.reserve(entries.size());
    for (const auto& entry : entries) out.push_back(entry.selector);
    return out;
}

std::vector<std::pair<std::string, std::string>>
CompilationInputSet::legacy_view() const {
    std::vector<std::pair<std::string, std::string>> out;
    out.reserve(entries.size());
    for (const auto& entry : entries) {
        out.emplace_back(!entry.label.empty() ? entry.label : entry.selector,
                         entry.selector);
    }
    return out;
}

Json CompilationInputSet::to_dict() const {
    Json entries_arr = Json::array();
    for (const auto& entry : entries) entries_arr.push_back(entry.to_dict());
    Json out = Json::object();
    out["id"] = id;
    out["name"] = name;
    out["entries"] = std::move(entries_arr);
    out["created_at"] = created_at;
    out["created_by"] = created_by;
    out["recommendation"] =
        recommendation.is_object() ? recommendation : Json::object();
    out["manual_overrides"] =
        manual_overrides.is_object() ? manual_overrides : Json::object();
    out["configuration"] =
        configuration.is_object() ? configuration : Json::object();
    out["frozen"] = frozen;
    out["frozen_at"] = frozen_at;
    out["schema_version"] = schema_version;
    return out;
}

CompilationInputSet CompilationInputSet::from_dict(const Json& data) {
    CompilationInputSet set;
    set.id = attr_str(data, "id");
    set.name = attr_str(data, "name");
    for (const Json& e : attr_or_array(data, "entries")) {
        if (!e.is_object()) continue;
        if (!truthy(attr_or_null(e, "selector"))) continue;
        set.entries.push_back(CompilationInputSetEntry::from_dict(e));
    }
    set.created_at = attr_str(data, "created_at");
    set.created_by = attr_str(data, "created_by");
    const Json recommendation = attr_or_null(data, "recommendation");
    set.recommendation =
        recommendation.is_object() ? recommendation : Json::object();
    const Json manual_overrides = attr_or_null(data, "manual_overrides");
    set.manual_overrides =
        manual_overrides.is_object() ? manual_overrides : Json::object();
    const Json configuration = attr_or_null(data, "configuration");
    set.configuration =
        configuration.is_object() ? configuration : Json::object();
    set.frozen = truthy(attr_or_null(data, "frozen"));
    set.frozen_at = attr_str(data, "frozen_at");
    // int(data.get("schema_version") or 1).
    const Json schema = attr_or_null(data, "schema_version");
    set.schema_version = 1;
    if (truthy(schema)) {
        if (schema.is_number_integer())
            set.schema_version = static_cast<int>(schema.get<long long>());
        else if (schema.is_number_unsigned())
            set.schema_version =
                static_cast<int>(schema.get<unsigned long long>());
        else if (schema.is_number_float())
            set.schema_version = static_cast<int>(schema.get<double>());
        else if (schema.is_boolean())
            set.schema_version = schema.get<bool>() ? 1 : 0;
        else if (schema.is_string()) {
            // Python int(str) — non-numeric text would raise; clamped here
            // (documented divergence, never exercised by the oracle).
            try {
                set.schema_version = std::stoi(schema.get<std::string>());
            } catch (const std::exception&) {
                set.schema_version = 1;
            }
        }
    }
    return set;
}

// --------------------------------------------------------------- validation

std::vector<std::string> CompilationValidation::factor_selectors() const {
    std::vector<std::string> out;
    for (const auto& r : resolutions) {
        const std::string raw = r.selector.str();
        if (raw.rfind("factor:", 0) == 0) out.push_back(raw);
    }
    return out;
}

Json CompilationValidation::to_dict() const {
    Json entries_arr = Json::array();
    for (const auto& r : resolutions) entries_arr.push_back(r.to_dict());
    Json out = Json::object();
    out["input_set_id"] = input_set_id;
    out["verdict"] = verdict;
    out["detail"] = detail;
    out["entries"] = std::move(entries_arr);
    return out;
}

// --------------------------------------------------------------- lifecycle

CompilationInputSet create_input_set(
    const Json& document,
    const std::vector<std::string>& selectors,
    const ResolveContext& ctx,
    const std::string& name,
    const std::string& created_by,
    const std::string& set_id,
    const std::string& now,
    const IdGen& idgen) {
    std::vector<CompilationInputSetEntry> entries;
    for (const std::string& raw : selectors) {
        // malformed → ValueError (propagates).
        const auto selector = parse_evidence_selector(raw);
        const EvidenceResolution resolution =
            resolve_evidence(document, selector, ctx.catalog, ctx.workspace,
                             ctx.constraint_resolver);
        CompilationInputSetEntry entry;
        entry.selector = selector.str();
        entry.label = !resolution.display.empty() ? resolution.display
                                                  : selector.str();
        entry.evidence_kind = evidence_kind_value(selector.kind);
        entry.pinned_version_id = "";
        entry.resolved_asset_id = resolution.asset_id;
        entry.added_at = now;
        entry.added_by = created_by;
        entry.note = resolution.detail;
        entry.status_at_add = evidence_status_value(resolution.status);
        entries.push_back(std::move(entry));
    }
    CompilationInputSet set;
    if (!set_id.empty()) {
        set.id = set_id;
    } else if (idgen) {
        set.id = "ciset_" + idgen();
    } else {
        set.id = domain::make_id("ciset_");
    }
    set.name = !name.empty()
                   ? name
                   : "综合编图输入集（" +
                         std::to_string(entries.size()) + " 项证据）";
    set.entries = std::move(entries);
    set.created_at = now;
    set.created_by = created_by;
    return set;
}

CompilationValidation validate_input_set(
    const CompilationInputSet& input_set, const Json& document,
    const ResolveContext& ctx) {
    std::vector<EvidenceResolution> resolutions;
    for (const auto& entry : input_set.entries) {
        if (!entry.pinned_version_id.empty()) {
            // Frozen entries validate against the pinned version (the
            // version inside the selector IS the pin).
            const std::string pinned_selector = selector_with_version(
                entry.selector, entry.pinned_version_id);
            resolutions.push_back(resolve_evidence(
                document, pinned_selector, ctx.catalog, ctx.workspace,
                ctx.constraint_resolver));
        } else {
            resolutions.push_back(resolve_evidence(
                document, entry.selector, ctx.catalog, ctx.workspace,
                ctx.constraint_resolver));
        }
    }
    std::string verdict = "ready";
    std::string detail;
    std::vector<std::string> bad;
    std::vector<std::string> unpinned;
    for (const auto& r : resolutions) {
        if (r.status == EvidenceStatus::Missing ||
            r.status == EvidenceStatus::Unknown) {
            bad.push_back(r.selector.str());
        } else if (r.status == EvidenceStatus::Unpinned) {
            unpinned.push_back(r.selector.str());
        }
    }
    if (!bad.empty()) {
        verdict = "blocked";
        detail = "存在不可用证据（缺失/未知）：" + join_fullwidth(bad);
    } else if (!unpinned.empty()) {
        verdict = "degraded";
        detail =
            "存在未钉版本的证据（保存/提交后可冻结）：" +
            join_fullwidth(unpinned);
    }
    CompilationValidation out;
    out.input_set_id = input_set.id;
    out.resolutions = std::move(resolutions);
    out.verdict = std::move(verdict);
    out.detail = std::move(detail);
    return out;
}

std::string selector_with_version(const std::string& selector,
                                  const std::string& version_id) {
    const auto parsed = parse_evidence_selector(selector);
    const char* kind_text = evidence_kind_value(parsed.kind);
    const std::string kind(kind_text ? kind_text : "");
    if (kind == "factor" || kind == "prediction") {
        return kind + ":" + parsed.ref_id + ":" + version_id;
    }
    if (kind == "constraint_group" && !parsed.ref_id.empty()) {
        return "constraints:" + parsed.ref_id + ":" + version_id;
    }
    return selector;
}

CompilationInputSet& freeze_input_set(CompilationInputSet& input_set,
                                      const Json& document,
                                      const ResolveContext& ctx,
                                      const std::string& now) {
    if (input_set.frozen) {
        throw CompilationValueError("输入集已冻结（不可重复冻结——新建输入集替代）");
    }
    const CompilationValidation validation =
        validate_input_set(input_set, document, ctx);
    std::vector<std::string> refusals;
    // {r.selector.raw: r for r in resolutions} — later duplicates win.
    std::map<std::string, EvidenceResolution> by_selector;
    for (const auto& r : validation.resolutions) {
        by_selector[r.selector.str()] = r;
    }
    std::vector<std::pair<std::string, std::string>> snapshots;
    snapshots.reserve(input_set.entries.size());
    for (const auto& entry : input_set.entries) {
        snapshots.emplace_back(entry.selector, entry.pinned_version_id);
    }
    for (auto& entry : input_set.entries) {
        const auto it = by_selector.find(entry.selector);
        if (it == by_selector.end()) {
            refusals.push_back(entry.label + "：无法解析");
            continue;
        }
        const EvidenceResolution& resolution = it->second;
        if (resolution.status == EvidenceStatus::Floating) {
            const auto pinned =
                pin_floating_constraints(document, ctx.repository);
            if (!pinned.has_value()) {
                refusals.push_back(
                    entry.label +
                    "：constraints:current 无法安全钉住——无目录/无提交，或多个"
                    "约束组各有提交（请改用显式 constraints:<组>:<版本> 条目逐组"
                    "钉住）");
                continue;
            }
            entry.pinned_version_id = pinned->second;
            entry.selector =
                "constraints:" + pinned->first + ":" + pinned->second;
            continue;
        }
        if (resolution.status == EvidenceStatus::Resolved ||
            resolution.status == EvidenceStatus::Stale) {
            entry.pinned_version_id = resolution.pinned_version_id;
            const std::string rewritten = selector_with_version(
                entry.selector, resolution.pinned_version_id);
            if (rewritten != entry.selector && parses(rewritten)) {
                entry.selector = rewritten;
            }
            continue;
        }
        refusals.push_back(
            entry.label + "：" +
            evidence_status_value(resolution.status) + "（" +
            resolution.detail + "）");
    }
    if (!refusals.empty()) {
        // Roll back EVERY change of this attempt: selector rewrites + pins
        // (freeze is atomic).
        for (std::size_t i = 0; i < input_set.entries.size(); ++i) {
            input_set.entries[i].selector = snapshots[i].first;
            input_set.entries[i].pinned_version_id = snapshots[i].second;
        }
        throw CompilationValueError(
            "输入集冻结被拒绝——以下证据无法钉住版本：" +
            join_fullwidth(refusals));
    }
    input_set.frozen = true;
    input_set.frozen_at = now;
    return input_set;
}

std::optional<std::pair<std::string, std::string>> pin_floating_constraints(
    const Json& document,
    workflow_runtime::CatalogRepository* repository) {
    if (repository == nullptr) return std::nullopt;
    try {
        std::optional<std::pair<std::string, std::string>> pinned;
        for (const Json& group :
             attr_or_array(document, "constraint_layers")) {
            if (!group.is_object()) continue;
            const std::string group_id = attr_str(group, "id");
            const auto latest =
                workflow_runtime::current_constraint_version(*repository,
                                                              group_id);
            if (!latest.has_value()) continue;
            if (pinned.has_value()) {
                return std::nullopt;  // 多组有提交：拒绝浮动钉住
            }
            pinned = std::make_pair(
                group_id, latest->version_id.empty()
                              ? std::string()
                              : latest->version_id);
        }
        return pinned;
    } catch (...) {  // 查询失败=不可钉
        return std::nullopt;
    }
}

// ------------------------------------------------------ persistence helpers

void persist_input_set(Json& document, const CompilationInputSet& input_set,
                       bool active) {
    Json sets = attr_or_array(document, "compilation_input_sets");
    Json payload = input_set.to_dict();
    if (active) {
        payload["active"] = true;
        for (Json& s : sets) {
            if (s.is_object()) s["active"] = false;  // dict(s, active=False)
        }
    }
    bool replaced = false;
    for (std::size_t i = 0; i < sets.size(); ++i) {
        // str(existing.get("id")) — no `or ""` guard (str(None) == "None").
        const Json& existing = sets[i];
        const Json id_value = attr_or_null(existing, "id");
        if (str_strict(id_value) == input_set.id) {
            sets[i] = payload;
            replaced = true;
            break;
        }
    }
    if (!replaced) sets.push_back(payload);
    document["compilation_input_sets"] = std::move(sets);
}

std::optional<CompilationInputSet> active_input_set(const Json& document) {
    for (const Json& payload :
         attr_or_array(document, "compilation_input_sets")) {
        if (payload.is_object() && truthy(attr_or_null(payload, "active"))) {
            return CompilationInputSet::from_dict(payload);
        }
    }
    return std::nullopt;
}

std::vector<CompilationInputSet> input_sets_for_document(
    const Json& document) {
    std::vector<CompilationInputSet> out;
    for (const Json& s : attr_or_array(document, "compilation_input_sets")) {
        if (s.is_object() && truthy(attr_or_null(s, "id"))) {
            out.push_back(CompilationInputSet::from_dict(s));
        }
    }
    return out;
}

std::vector<std::pair<std::string, std::string>> evidence_view(
    const Json& document, const Json* workspace_state) {
    const std::optional<CompilationInputSet> input_set =
        active_input_set(document);
    if (input_set.has_value()) {
        std::vector<std::pair<std::string, std::string>> view =
            input_set->legacy_view();
        if (!view.empty()) return view;
    }
    if (workspace_state == nullptr) return {};
    std::vector<std::pair<std::string, std::string>> out;
    const Json legacy = attr_or_null(*workspace_state,
                                     "compilation_input_set");
    if (legacy.is_object()) {
        for (auto it = legacy.begin(); it != legacy.end(); ++it) {
            // {str(k): str(v)} — str(v) without an `or` guard.
            out.emplace_back(it.key(), str_strict(it.value()));
        }
    }
    return out;
}

std::optional<CompilationInputSet> create_input_set_shell_from_legacy(
    Json& document, const Json& workspace_state,
    const std::string& created_by, const IdGen& idgen) {
    try {
        CompilationInputSet shell;
        shell.id = idgen ? "ciset_" + idgen() : domain::make_id("ciset_");
        shell.name = "综合编图输入集";
        shell.created_by = created_by;
        const Json legacy_raw =
            attr_or_null(workspace_state, "compilation_input_set");
        // dict(ws.compilation_input_set or {}) — a truthy NON-object would
        // raise in Python and abort the migration (→ None); mirror that.
        if (truthy(legacy_raw) && !legacy_raw.is_object()) {
            throw std::runtime_error(
                "compilation_input_set must be an object");
        }
        const Json legacy = legacy_raw.is_object() ? legacy_raw
                                                   : Json::object();
        if (legacy.is_object()) {
            for (auto it = legacy.begin(); it != legacy.end(); ++it) {
                // Unparseable legacy selectors are skipped per-item
                // (Python's inner try/except ValueError: continue) — they
                // never abort the migration.
                workflow_graph::EvidenceSelector parsed;
                try {
                    parsed = parse_evidence_selector(str_strict(it.value()));
                } catch (const workflow_graph::EvidenceValueError&) {
                    continue;
                }
                CompilationInputSetEntry entry;
                entry.selector = parsed.str();
                entry.label = it.key();
                entry.evidence_kind = evidence_kind_value(parsed.kind);
                entry.pinned_version_id = "";
                entry.resolved_asset_id = "";
                entry.added_at = "";
                entry.added_by = created_by;
                entry.note = "";
                entry.status_at_add = "";
                shell.entries.push_back(std::move(entry));
            }
        }
        persist_input_set(document, shell);
        return shell;
    } catch (...) {  // 迁移失败不阻断旧视图路径
        return std::nullopt;
    }
}

}  // namespace pwb::workflow_interpretation
