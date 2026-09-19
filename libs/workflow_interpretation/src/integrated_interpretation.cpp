// CONV-32 — integrated_interpretation.py port (I8). See header.
// Python authoritative: verbatim message strings, Python str() coercion
// semantics, Python json.dumps(sort_keys=True, ensure_ascii=False) payload
// text (DEFAULT separators) for the catalog registration.
#include <pwb/workflow_interpretation/integrated_interpretation.hpp>

#include <pwb/domain/ids.hpp>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <utility>

namespace pwb::workflow_interpretation {
namespace {

// ---- Python value semantics --------------------------------------------

[[nodiscard]] bool py_truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get_ref<const std::string&>().empty();
    if (v.is_array() || v.is_object()) return !v.empty();
    return true;
}

// CPython float repr digits: shortest round-trip (to_chars scientific),
// re-rendered with the fixed/exponential decpt rule of repr().
[[nodiscard]] std::string py_float_digits(double d) {
    if (d == 0.0) return std::signbit(d) ? "-0.0" : "0.0";
    char buf[64];
    const auto res =
        std::to_chars(buf, buf + sizeof buf, d, std::chars_format::scientific);
    const std::string s(buf, static_cast<std::size_t>(res.ptr - buf));
    bool neg = false;
    std::size_t start = 0;
    if (s[0] == '-') {
        neg = true;
        start = 1;
    }
    const std::size_t epos = s.find('e');
    std::string digits;
    for (const char c : s.substr(start, epos - start)) {
        if (c != '.') digits += c;
    }
    int exp10 = 0;
    std::from_chars(s.data() + epos + 1, s.data() + s.size(), exp10);
    const int decpt = exp10 + 1;  // value = 0.<digits> * 10^decpt
    std::string out;
    if (decpt <= -4 || decpt > 16) {
        out = digits.substr(0, 1);
        if (digits.size() > 1) out += "." + digits.substr(1);
        const int e = decpt - 1;
        out += e < 0 ? "e-" : "e+";
        const int ae = e < 0 ? -e : e;
        if (ae < 10) out += '0';
        out += std::to_string(ae);
    } else if (decpt <= 0) {
        out = "0." + std::string(static_cast<std::size_t>(-decpt), '0') +
              digits;
    } else if (static_cast<std::size_t>(decpt) >= digits.size()) {
        out = digits +
              std::string(static_cast<std::size_t>(decpt) - digits.size(),
                          '0') +
              ".0";
    } else {
        out = digits.substr(0, static_cast<std::size_t>(decpt)) + "." +
              digits.substr(static_cast<std::size_t>(decpt));
    }
    return neg ? "-" + out : out;
}

// Python str(v) for scalars (float -> repr spelling: inf / nan).
[[nodiscard]] std::string py_str(const Json& v) {
    if (v.is_null()) return "None";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_unsigned())
        return std::to_string(v.get<unsigned long long>());
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_float()) {
        const double d = v.get<double>();
        if (std::isnan(d)) return "nan";
        if (std::isinf(d)) return d < 0.0 ? "-inf" : "inf";
        return py_float_digits(d);
    }
    if (v.is_string()) return v.get_ref<const std::string&>();
    // Containers (never hit by the frozen field vocabularies): Python repr.
    if (v.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const Json& item : v) {
            if (!first) out += ", ";
            first = false;
            out += item.is_string()
                       ? "'" + item.get_ref<const std::string&>() + "'"
                       : py_str(item);
        }
        return out + "]";
    }
    if (v.is_object()) {
        std::string out = "{";
        bool first = true;
        for (auto it = v.begin(); it != v.end(); ++it) {
            if (!first) out += ", ";
            first = false;
            out += "'" + it.key() + "': " +
                   (it->is_string()
                        ? "'" + it->get_ref<const std::string&>() + "'"
                        : py_str(*it));
        }
        return out + "}";
    }
    return "";
}

// Python str(x or "") — the from_dict coercion.
[[nodiscard]] std::string py_str_or_empty(const Json& v) {
    return py_truthy(v) ? py_str(v) : std::string();
}

// ---- json.dumps(payload, ensure_ascii=False, sort_keys=True) -----------

void dumps_string(const std::string& s, std::string& out) {
    out += '"';
    for (const char c : s) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(c) < 0x20) {
                static constexpr const char* kHex = "0123456789abcdef";
                const auto byte = static_cast<unsigned char>(c);
                out += "\\u00";
                out += kHex[(byte >> 4) & 0xF];
                out += kHex[byte & 0xF];
            } else {
                out += c;  // ensure_ascii=False: raw UTF-8, 0x7F kept
            }
        }
    }
    out += '"';
}

// json.dumps float spelling (differs from repr for the specials).
[[nodiscard]] std::string json_float(double d) {
    if (std::isnan(d)) return "NaN";
    if (std::isinf(d)) return d < 0.0 ? "-Infinity" : "Infinity";
    return py_float_digits(d);
}

void dumps_encode(const Json& v, std::string& out) {
    switch (v.type()) {
    case Json::value_t::null: out += "null"; break;
    case Json::value_t::boolean: out += v.get<bool>() ? "true" : "false"; break;
    case Json::value_t::number_integer:
        out += std::to_string(v.get<long long>());
        break;
    case Json::value_t::number_unsigned:
        out += std::to_string(v.get<unsigned long long>());
        break;
    case Json::value_t::number_float: out += json_float(v.get<double>()); break;
    case Json::value_t::string:
        dumps_string(v.get_ref<const std::string&>(), out);
        break;
    case Json::value_t::array: {
        out += '[';
        bool first = true;
        for (const Json& item : v) {
            if (!first) out += ", ";
            first = false;
            dumps_encode(item, out);
        }
        out += ']';
        break;
    }
    case Json::value_t::object: {
        // sort_keys: byte-wise key order == Python code-point order.
        std::vector<const std::string*> keys;
        keys.reserve(v.size());
        for (auto it = v.begin(); it != v.end(); ++it) {
            keys.push_back(&it.key());
        }
        std::sort(keys.begin(), keys.end(),
                  [](const std::string* a, const std::string* b) {
                      return *a < *b;
                  });
        out += '{';
        bool first = true;
        for (const std::string* key : keys) {
            if (!first) out += ", ";
            first = false;
            dumps_string(*key, out);
            out += ": ";  // Python default item separator
            dumps_encode(v.at(*key), out);
        }
        out += '}';
        break;
    }
    default: break;  // binary/discarded never occur in document trees
    }
}

// ---- document array seam -------------------------------------------------

// getattr(document, "integrated_interpretations", None) or [] — missing /
// non-array -> empty array, else a copy (Python list() copy semantics).
[[nodiscard]] Json records_copy(const Json& document) {
    const auto it = document.find("integrated_interpretations");
    if (it != document.end() && it->is_array()) return *it;
    return Json::array();
}

void records_assign(Json& document, Json records) {
    document["integrated_interpretations"] = std::move(records);
}

[[nodiscard]] Json schema_to_json(const std::vector<std::string>& schema) {
    Json out = Json::array();
    for (const std::string& c : schema) out.push_back(c);
    return out;
}

}  // namespace

// ---- IntegratedInterpretation -------------------------------------------

bool IntegratedInterpretation::has_uncommitted_edits() const {
    return !committed_version_id.empty() && !revision_ids.empty() &&
           revision_ids.back() != last_committed_revision_id;
}

Json IntegratedInterpretation::to_dict() const {
    Json out = Json::object();
    out["interpretation_id"] = interpretation_id;
    out["name"] = name;
    out["input_set_id"] = input_set_id;
    out["layer_id"] = layer_id;
    out["fusion_version_id"] = fusion_version_id;
    out["latest_fusion_version_id"] = latest_fusion_version_id;
    out["run_id"] = run_id;
    out["committed_version_id"] = committed_version_id;
    out["class_schema"] = schema_to_json(class_schema);
    out["confidence_summary"] = confidence_summary;
    out["uncertainty_summary"] = uncertainty_summary;
    out["conflicts"] = conflicts;
    Json revisions = Json::array();
    for (const std::string& r : revision_ids) revisions.push_back(r);
    out["revision_ids"] = std::move(revisions);
    out["last_committed_revision_id"] = last_committed_revision_id;
    out["qa_report_ref"] = qa_report_ref;
    out["maturity"] = maturity;
    out["created_at"] = created_at;
    out["created_by"] = created_by;
    out["committed_at"] = committed_at;
    out["active"] = true;
    return out;
}

IntegratedInterpretation IntegratedInterpretation::from_dict(const Json& data) {
    const auto str_field = [&data](const char* key) {
        const auto it = data.find(key);
        return it == data.end() ? std::string() : py_str_or_empty(*it);
    };
    // [str(x) for x in (data.get(key) or [])] — elements coerced verbatim
    // (str(None) == "None"); a falsy / non-array value -> [].
    const auto strs_field = [&data](const char* key) {
        std::vector<std::string> out;
        const auto it = data.find(key);
        if (it != data.end() && it->is_array() && py_truthy(*it)) {
            for (const Json& item : *it) out.push_back(py_str(item));
        }
        return out;
    };
    // dict(data.get(key) or {}) — non-object values coerce to {} (Python
    // would raise on a truthy non-mapping; never produced by the model).
    const auto dict_field = [&data](const char* key) {
        const auto it = data.find(key);
        if (it != data.end() && it->is_object()) return *it;
        return Json::object();
    };

    IntegratedInterpretation out;
    out.interpretation_id = str_field("interpretation_id");
    out.name = str_field("name");
    out.input_set_id = str_field("input_set_id");
    out.layer_id = str_field("layer_id");
    out.fusion_version_id = str_field("fusion_version_id");
    out.latest_fusion_version_id = str_field("latest_fusion_version_id");
    out.run_id = str_field("run_id");
    out.committed_version_id = str_field("committed_version_id");
    out.class_schema = strs_field("class_schema");
    out.confidence_summary = dict_field("confidence_summary");
    out.uncertainty_summary = dict_field("uncertainty_summary");
    out.conflicts = dict_field("conflicts");
    out.revision_ids = strs_field("revision_ids");
    out.last_committed_revision_id = str_field("last_committed_revision_id");
    out.qa_report_ref = str_field("qa_report_ref");
    out.maturity = str_field("maturity");
    if (out.maturity.empty()) out.maturity = MATURITY_DRAFT;
    out.created_at = str_field("created_at");
    out.created_by = str_field("created_by");
    out.committed_at = str_field("committed_at");
    return out;
}

IntegratedIdGen default_integrated_id_gen() {
    return [] { return domain::make_id(""); };  // 12 hex, "iint_" prefixed by caller
}

// ---- create / lookup / upsert -------------------------------------------

IntegratedInterpretation create_integrated_interpretation(
    Json& document, const std::string& name, const std::string& layer_id,
    const std::string& input_set_id, const std::string& fusion_version_id,
    const std::string& run_id, const std::vector<std::string>& class_schema,
    const Json& confidence_summary, const Json& conflicts,
    const std::string& created_by, const std::string& created_at,
    const IntegratedIdGen& id_gen) {
    if (find_by_layer(document, layer_id).has_value()) {
        throw IntegratedInterpretationValueError(
            "层 " + layer_id + " 已有综合解释记录（不可重复创建）");
    }
    const IntegratedIdGen gen =
        id_gen != nullptr ? id_gen : default_integrated_id_gen();

    IntegratedInterpretation interpretation;
    interpretation.interpretation_id = "iint_" + gen();
    interpretation.name = name.empty() ? "综合解释" : name;
    interpretation.layer_id = layer_id;
    interpretation.input_set_id = input_set_id;
    interpretation.fusion_version_id = fusion_version_id;
    interpretation.run_id = run_id;
    interpretation.class_schema = class_schema;
    interpretation.confidence_summary =
        confidence_summary.is_object() ? confidence_summary : Json::object();
    interpretation.conflicts =
        conflicts.is_object() ? conflicts : Json::object();
    interpretation.created_by = created_by;
    interpretation.created_at = created_at;

    Json records = records_copy(document);
    records.push_back(interpretation.to_dict());
    records_assign(document, std::move(records));
    return interpretation;
}

std::vector<IntegratedInterpretation> interpretations_for_document(
    const Json& document) {
    std::vector<IntegratedInterpretation> out;
    for (const Json& record : records_copy(document)) {
        if (!record.is_object()) continue;
        const auto it = record.find("interpretation_id");
        if (it == record.end() || !py_truthy(*it)) continue;
        out.push_back(IntegratedInterpretation::from_dict(record));
    }
    return out;
}

std::optional<IntegratedInterpretation> find_by_layer(
    const Json& document, const std::string& layer_id) {
    for (const IntegratedInterpretation& interpretation :
         interpretations_for_document(document)) {
        if (interpretation.layer_id == layer_id) return interpretation;
    }
    return std::nullopt;
}

void upsert_interpretation(Json& document,
                           const IntegratedInterpretation& interpretation) {
    Json records = records_copy(document);
    const Json payload = interpretation.to_dict();
    for (std::size_t i = 0; i < records.size(); ++i) {
        const Json& existing = records.at(i);
        if (!existing.is_object()) continue;
        const auto it = existing.find("interpretation_id");
        // str(existing.get("interpretation_id")) — missing -> "None".
        const std::string key =
            it == existing.end() ? "None" : py_str(*it);
        if (key == interpretation.interpretation_id) {
            records.at(i) = payload;
            records_assign(document, std::move(records));
            return;
        }
    }
    records.push_back(payload);
    records_assign(document, std::move(records));
}

// ---- payload -------------------------------------------------------------

Json layer_payload(const IntegratedInterpretation& interpretation,
                   const Json& layer) {
    Json features = Json::array();
    if (layer.is_object()) {
        const auto raw = layer.find("features");
        if (raw != layer.end() && raw->is_array()) {
            for (const Json& feature : *raw) {
                Json out = Json::object();
                std::string id;
                Json geometry = Json::object();
                Json properties = Json::object();
                if (feature.is_object()) {
                    // str(feature_id or id or "") — feature_id wins.
                    const auto feature_id = feature.find("feature_id");
                    if (feature_id != feature.end() &&
                        py_truthy(*feature_id)) {
                        id = py_str(*feature_id);
                    } else {
                        const auto plain_id = feature.find("id");
                        if (plain_id != feature.end() &&
                            py_truthy(*plain_id)) {
                            id = py_str(*plain_id);
                        }
                    }
                    // geometry or {} — falsy / missing -> {}.
                    const auto geom = feature.find("geometry");
                    if (geom != feature.end() && py_truthy(*geom)) {
                        geometry = *geom;
                    }
                    // dict(attributes or properties or {}) — attributes
                    // wins; non-object values coerce to {} (documented
                    // divergence, Python would raise on truthy non-mapping).
                    const auto attributes = feature.find("attributes");
                    if (attributes != feature.end() &&
                        attributes->is_object() && py_truthy(*attributes)) {
                        properties = *attributes;
                    } else {
                        const auto props = feature.find("properties");
                        if (props != feature.end() && props->is_object() &&
                            py_truthy(*props)) {
                            properties = *props;
                        }
                    }
                }
                out["id"] = std::move(id);
                out["geometry"] = std::move(geometry);
                out["properties"] = std::move(properties);
                features.push_back(std::move(out));
            }
        }
    }
    Json payload = Json::object();
    payload["schema"] = 1;
    payload["interpretation_id"] = interpretation.interpretation_id;
    payload["layer_id"] = interpretation.layer_id;
    payload["class_schema"] = schema_to_json(interpretation.class_schema);
    payload["input_set_id"] = interpretation.input_set_id;
    payload["fusion_version_id"] = interpretation.fusion_version_id;
    payload["features"] = std::move(features);
    return payload;
}

std::string python_dumps_sorted(const Json& payload) {
    std::string out;
    out.reserve(256);
    dumps_encode(payload, out);
    return out;
}

// ---- commit -------------------------------------------------------------

std::string commit_integrated_interpretation(
    Json& document, const IntegratedInterpretation& interpretation,
    const Json& layer, workflow_runtime::CatalogRepository* catalog,
    const std::string& actor, const std::string& now,
    const std::vector<std::string>& evidence_refs,
    const RevisionIdGen& revision_id_gen) {
    if (catalog == nullptr) {
        throw IntegratedInterpretationValueError(
            "目录服务不可用——综合解释提交需要 catalog（不伪称已提交）");
    }
    const Json payload = layer_payload(interpretation, layer);
    if (payload.at("features").empty()) {
        throw IntegratedInterpretationValueError("解释层没有要素——拒绝提交空几何");
    }
    const std::string payload_text = python_dumps_sorted(payload);

    // Lazy-safe PUBLIC lookup: list_assets() is the sanctioned path.
    std::optional<workflow_runtime::AssetRecord> asset;
    for (const workflow_runtime::AssetRecord& candidate :
         catalog->list_assets()) {
        if (candidate.type != ASSET_TYPE_INTEGRATED_INTERPRETATION) continue;
        const auto meta = candidate.metadata.find("interpretation_id");
        if (meta == candidate.metadata.end()) continue;
        if (py_str_or_empty(*meta) == interpretation.interpretation_id) {
            asset = candidate;
            break;
        }
    }
    // 评审 R2-F6：用 catalog 认可的当前版本指针（而非自行推导）。
    const std::string previous_version =
        asset.has_value() ? asset->current_version_id.value_or("") : "";

    std::vector<std::string> input_version_ids;
    if (!interpretation.fusion_version_id.empty()) {
        input_version_ids.push_back(interpretation.fusion_version_id);
    }
    if (!previous_version.empty()) {
        input_version_ids.push_back(previous_version);
    }
    Json parameters = Json::object();
    parameters["interpretation_id"] = interpretation.interpretation_id;
    parameters["layer_id"] = interpretation.layer_id;
    parameters["input_set_id"] = interpretation.input_set_id;
    parameters["n_features"] = payload.at("features").size();
    parameters["actor"] = actor;
    const std::string run_id = catalog->register_run(
        OPERATION_INTEGRATED_INTERPRETATION, input_version_ids, parameters,
        std::optional<std::string>("interpretation-v9"), "running");

    std::string version_id;
    try {
        if (!asset.has_value()) {
            Json asset_metadata = Json::object();
            asset_metadata["interpretation_id"] =
                interpretation.interpretation_id;
            Json version_metadata = Json::object();
            version_metadata["interpretation_id"] =
                interpretation.interpretation_id;
            version_metadata["actor"] = actor;
            const workflow_runtime::RegisteredAssetVersion registered =
                catalog->register_result_asset(
                    "interpretation:" + interpretation.name,
                    ASSET_TYPE_INTEGRATED_INTERPRETATION, "json",
                    asset_metadata, payload_text, "derived", run_id,
                    version_metadata);
            version_id = registered.version_id;
        } else {
            std::vector<std::string> parents;
            if (!previous_version.empty()) parents.push_back(previous_version);
            Json version_metadata = Json::object();
            version_metadata["interpretation_id"] =
                interpretation.interpretation_id;
            version_metadata["actor"] = actor;
            version_id = catalog->register_version(
                asset->id, payload_text, "derived", parents, run_id,
                version_metadata);
        }
        catalog->update_run_status(run_id, "complete");
    } catch (...) {
        try {
            catalog->update_run_status(run_id, "failed");
        } catch (...) {  // noqa — swallow secondary failures, rethrow primary
        }
        throw;
    }

    // 文档侧同步（记录 + revision 链）。
    IntegratedInterpretation updated = interpretation;
    updated.committed_version_id = version_id;
    updated.run_id = run_id;
    updated.committed_at = now;
    upsert_interpretation(document, updated);
    const std::optional<InterpretationRevision> revision =
        record_interpretation_revision(
            document, TARGET_INTEGRATED_FACIES, interpretation.layer_id, layer,
            actor.empty() ? "commit" : actor, now,
            interpretation.interpretation_id, "commit", version_id,
            evidence_refs, "综合解释提交（commit → DERIVED 版本）",
            revision_id_gen);
    if (revision.has_value()) {
        // revision 链接已由领域函数维护（防止拷贝双写）；此处只钉
        // last_committed 锚点——重读文档侧对象避免覆盖中间状态。
        const std::optional<IntegratedInterpretation> fresh =
            find_by_layer(document, interpretation.layer_id);
        IntegratedInterpretation target = fresh.has_value() ? *fresh : updated;
        if (std::find(target.revision_ids.begin(), target.revision_ids.end(),
                      revision->revision_id) == target.revision_ids.end()) {
            target.revision_ids.push_back(revision->revision_id);
        }
        target.last_committed_revision_id = revision->revision_id;
        upsert_interpretation(document, target);
    } else {
        // 内容自上次修订未变——仍推进 last_committed 锚点到链尾。
        const std::optional<InterpretationRevision> latest =
            latest_revision_for_layer(document, interpretation.layer_id);
        if (latest.has_value()) {
            const std::optional<IntegratedInterpretation> fresh =
                find_by_layer(document, interpretation.layer_id);
            IntegratedInterpretation target =
                fresh.has_value() ? *fresh : updated;
            target.last_committed_revision_id = latest->revision_id;
            upsert_interpretation(document, target);
        }
    }
    return version_id;
}

// ---- summary -------------------------------------------------------------

Json interpretation_summary(const Json& document,
                            const std::string& layer_id) {
    const std::optional<IntegratedInterpretation> interpretation =
        find_by_layer(document, layer_id);
    if (!interpretation.has_value()) {
        Json out = Json::object();
        out["layer_id"] = layer_id;
        out["status"] = "missing";
        out["detail"] = "无综合解释记录（旧工程或未创建）";
        return out;
    }
    Json out = Json::object();
    out["layer_id"] = layer_id;
    out["status"] = "ok";
    out["interpretation_id"] = interpretation->interpretation_id;
    out["name"] = interpretation->name;
    out["input_set_id"] = interpretation->input_set_id;
    out["fusion_version_id"] = interpretation->fusion_version_id;
    out["committed_version_id"] = interpretation->committed_version_id;
    out["maturity"] = interpretation->maturity;
    out["class_schema"] = schema_to_json(interpretation->class_schema);
    out["confidence_summary"] = interpretation->confidence_summary;
    out["conflicts"] = interpretation->conflicts;
    out["has_uncommitted_edits"] = interpretation->has_uncommitted_edits();
    out["revisions"] = revision_summary(document, layer_id);
    return out;
}

}  // namespace pwb::workflow_interpretation
