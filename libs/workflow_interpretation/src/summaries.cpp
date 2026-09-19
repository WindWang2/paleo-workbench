// CONV-32 — Inspector summaries (summaries.py port). See header. The value
// formatting implements Python str() semantics: float -> shortest
// round-trip repr (std::to_chars scientific, re-rendered with the CPython
// fixed/exponential decpt rule), int -> digits, bool -> "True"/"False",
// null -> "None", string verbatim (containers fall back to Python-style
// repr — never hit by the frozen QC/conflict vocabularies).
#include <pwb/workflow_interpretation/summaries.hpp>

#include <pwb/workflow_interpretation/algorithm_registry.hpp>

#include <array>
#include <charconv>
#include <cmath>
#include <string>
#include <utility>

namespace pwb::workflow_interpretation {
namespace {

[[nodiscard]] std::string py_repr_double(double d) {
    if (std::isnan(d)) return "nan";
    if (std::isinf(d)) return d < 0.0 ? "-inf" : "inf";
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
    if (decpt <= -4 || decpt > 16) {  // CPython float repr format rule
        out = digits.substr(0, 1);
        if (digits.size() > 1) out += "." + digits.substr(1);
        const int e = decpt - 1;
        out += e < 0 ? "e-" : "e+";
        const int ae = e < 0 ? -e : e;
        if (ae < 10) out += '0';
        out += std::to_string(ae);
    } else if (decpt <= 0) {
        out = "0." + std::string(static_cast<std::size_t>(-decpt), '0') + digits;
    } else if (static_cast<std::size_t>(decpt) >= digits.size()) {
        out = digits +
              std::string(static_cast<std::size_t>(decpt) - digits.size(), '0') +
              ".0";
    } else {
        out = digits.substr(0, static_cast<std::size_t>(decpt)) + "." +
              digits.substr(static_cast<std::size_t>(decpt));
    }
    return neg ? "-" + out : out;
}

[[nodiscard]] std::string py_repr_string(const std::string& s) {
    std::string out = "'";
    for (const char c : s) {
        if (c == '\\' || c == '\'') out += '\\';
        out += c;
    }
    out += "'";
    return out;
}

// Python str(v) for a JSON value (scalar paths are the frozen vocabularies).
[[nodiscard]] std::string py_str(const Json& v) {
    if (v.is_null()) return "None";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_unsigned()) return std::to_string(v.get<unsigned long long>());
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_float()) return py_repr_double(v.get<double>());
    if (v.is_string()) return v.get_ref<const std::string&>();
    if (v.is_array()) {
        std::string out = "[";
        bool first = true;
        for (const Json& item : v) {
            if (!first) out += ", ";
            first = false;
            out += item.is_string() ? py_repr_string(item.get_ref<const std::string&>())
                                    : py_str(item);
        }
        out += "]";
        return out;
    }
    std::string out = "{";  // dict repr, insertion order (ordered_json)
    bool first = true;
    for (auto it = v.begin(); it != v.end(); ++it) {
        if (!first) out += ", ";
        first = false;
        out += py_repr_string(it.key()) + ": " +
               (it->is_string() ? py_repr_string(it->get_ref<const std::string&>())
                                : py_str(*it));
    }
    out += "}";
    return out;
}

[[nodiscard]] SummaryRow row(const std::string& label, const std::string& value,
                             const std::string& state = "ok") {
    return SummaryRow{label, value, state};
}

[[nodiscard]] std::string str_field(const Json& obj, const char* key) {
    const auto it = obj.find(key);
    if (it != obj.end() && it->is_string()) {
        return it->get_ref<const std::string&>();
    }
    return "";
}

[[nodiscard]] std::string str_value(const Json& v) {
    return v.is_string() ? v.get_ref<const std::string&>() : "";
}

// Python s[:12] — first 12 CODE POINTS (not bytes).
[[nodiscard]] std::string utf8_codepoint_prefix(const std::string& s,
                                                std::size_t count) {
    std::string out;
    std::size_t seen = 0;
    std::size_t i = 0;
    while (i < s.size() && seen < count) {
        const auto lead = static_cast<unsigned char>(s[i]);
        std::size_t len = 1;
        if ((lead & 0xE0) == 0xC0) len = 2;
        else if ((lead & 0xF0) == 0xE0) len = 3;
        else if ((lead & 0xF8) == 0xF0) len = 4;
        if (i + len > s.size()) len = s.size() - i;
        out += s.substr(i, len);
        i += len;
        ++seen;
    }
    return out;
}

[[nodiscard]] Json rows_to_json(const std::vector<SummaryRow>& rows) {
    Json out = Json::array();
    for (const SummaryRow& r : rows) {
        Json item = Json::object();
        item["label"] = r.label;
        item["value"] = r.value;
        item["state"] = r.state;
        out.push_back(std::move(item));
    }
    return out;
}

}  // namespace

Json FactorSummary::to_display_dict() const {
    Json out = Json::object();
    out["kind"] = "factor";
    out["factor_id"] = factor_id;
    out["title"] = title;
    out["rows"] = rows_to_json(rows);
    return out;
}

Json InterpretationSummary::to_display_dict() const {
    Json out = Json::object();
    out["kind"] = "integrated_interpretation";
    out["interpretation_id"] = interpretation_id;
    out["title"] = title;
    out["rows"] = rows_to_json(rows);
    return out;
}

FactorSummary factor_summary(const FactorProduct* product) {
    if (product == nullptr) {
        return FactorSummary{"", "单因素（不存在）",
                             {row("状态", "任务不存在", "missing")}};
    }
    const std::string method = !product->algorithm_id.empty()
                                   ? display_label(product->algorithm_id)
                                   : product->method_label + "（未注册方法）";
    std::vector<SummaryRow> rows;
    rows.push_back(row("方法", method,
                       product->algorithm_id.empty() ? "unknown" : "ok"));
    rows.push_back(row(
        "单位",
        product->unit_declared
            ? product->unit
            : (!product->unit.empty()
                   ? product->unit + "（家族默认/未声明）"
                   : "未声明"),
        product->unit_declared ? "ok"
                               : (!product->unit.empty() ? "unknown" : "missing")));
    rows.push_back(row("CRS", product->crs_declared ? product->crs : "未声明",
                       product->crs_declared ? "ok" : "unknown"));
    rows.push_back(row(
        "输入版本",
        !product->input_version_ids.empty()
            ? std::to_string(product->input_version_ids.size()) + " 项已钉住"
            : "未登记（保存后登记）",
        !product->input_version_ids.empty() ? "ok" : "unknown"));
    rows.push_back(row(
        "结果版本",
        !product->grid_version_id.empty() ? product->grid_version_id
                                          : "未登记（保存后登记）",
        !product->grid_version_id.empty() ? "ok" : "unknown"));
    rows.push_back(row("Run", !product->run_id.empty() ? product->run_id : "无",
                       !product->run_id.empty() ? "ok" : "unknown"));
    rows.push_back(row("成熟度", product->maturity));
    const bool freshness_warn = product->freshness == "stale" ||
                                product->freshness == "missing_input" ||
                                product->freshness == "superseded";
    const bool freshness_unknown =
        product->freshness.empty() || product->freshness == "unknown";
    rows.push_back(row("新鲜度",
                       !product->freshness.empty() ? product->freshness : "未评估",
                       freshness_warn ? "warn"
                                      : (freshness_unknown ? "unknown" : "ok")));
    rows.push_back(row(
        "不确定度",
        product->has_uncertainty() ? "方差面（kriging）"
                                   : "无（方法不产生/任务无方差记录）",
        product->has_uncertainty() ? "ok" : "unknown"));
    rows.push_back(row(
        "数据来源",
        product->source_kind + (product->is_mock() ? "（含模拟数据）" : ""),
        product->is_mock() ? "warn" : "ok"));
    for (const char* key :
         {"r_squared", "n_points", "backend", "distance_policy"}) {
        const auto it = product->qc.find(key);
        if (it != product->qc.end()) {
            rows.push_back(row(std::string("QC·") + key, py_str(*it)));
        }
    }
    if (!product->freshness_detail.empty()) {
        rows.push_back(row("说明", product->freshness_detail));
    }
    return FactorSummary{product->factor_id,
                         product->name + "（" + product->factor_type + "）",
                         std::move(rows)};
}

FactorSummary factor_summary_for_task(const Json& tasks_array,
                                      const std::string& task_id,
                                      const CatalogResolver& catalog,
                                      const WorkspaceView& workspace_state) {
    const std::optional<FactorProduct> product = factor_product_for_task(
        tasks_array, task_id, catalog, workspace_state);
    return factor_summary(product.has_value() ? &*product : nullptr);
}

InterpretationSummary interpretation_summary_rows(const Json& interpretation,
                                                  const Json* latest_revision) {
    if (!interpretation.is_object()) {
        return InterpretationSummary{"", "综合解释（无记录）",
                                     {row("状态", "无综合解释记录（旧工程或未创建）",
                                          "missing")}};
    }
    const std::string input_set_id = str_field(interpretation, "input_set_id");
    const std::string fusion_version_id =
        str_field(interpretation, "fusion_version_id");
    const std::string committed_version_id =
        str_field(interpretation, "committed_version_id");
    const Json class_schema =
        interpretation.contains("class_schema") &&
                interpretation.at("class_schema").is_array()
            ? interpretation.at("class_schema")
            : Json::array();
    const Json conflicts = interpretation.contains("conflicts") &&
                                   interpretation.at("conflicts").is_object()
                               ? interpretation.at("conflicts")
                               : Json::object();
    const Json revision_ids =
        interpretation.contains("revision_ids") &&
                interpretation.at("revision_ids").is_array()
            ? interpretation.at("revision_ids")
            : Json::array();
    const std::string last_committed =
        str_field(interpretation, "last_committed_revision_id");
    // 已提交且有后续修订 → live 层 ≠ 最新提交。
    const bool has_uncommitted_edits = !committed_version_id.empty() &&
                                       !revision_ids.empty() &&
                                       str_value(revision_ids.back()) != last_committed;
    std::vector<SummaryRow> rows;
    rows.push_back(row(
        "输入集", !input_set_id.empty() ? input_set_id : "未绑定（旧工程）",
        !input_set_id.empty() ? "ok" : "unknown"));
    rows.push_back(row("算法种子",
                       !fusion_version_id.empty() ? fusion_version_id
                                                  : "人工起草（无算法种子）",
                       !fusion_version_id.empty() ? "ok" : "unknown"));
    rows.push_back(row("提交版本",
                       !committed_version_id.empty()
                           ? committed_version_id
                           : "未提交（编辑中）",
                       !committed_version_id.empty() ? "ok" : "unknown"));
    rows.push_back(row("成熟度", str_field(interpretation, "maturity")));
    std::string schema_join;
    for (const Json& item : class_schema) {
        if (!schema_join.empty()) schema_join += "、";
        schema_join += item.is_string()
                           ? item.get_ref<const std::string&>()
                           : (item.is_null() ? "None" : py_str(item));
    }
    rows.push_back(row("分类", !schema_join.empty() ? schema_join : "未声明",
                       !schema_join.empty() ? "ok" : "unknown"));
    rows.push_back(row("未提交编辑", has_uncommitted_edits ? "有" : "无",
                       has_uncommitted_edits ? "warn" : "ok"));
    rows.push_back(row("修订", std::to_string(revision_ids.size()) + " 条"));
    if (latest_revision != nullptr && latest_revision->is_object()) {
        const std::string actor = str_field(*latest_revision, "actor");
        const std::string created_at = str_field(*latest_revision, "created_at");
        const std::string base_kind = str_field(*latest_revision, "base_kind");
        const std::string base_version_id =
            str_field(*latest_revision, "base_version_id");
        rows.push_back(row(
            "最近修订",
            (actor.empty() ? "未知" : actor) + " @ " +
                (created_at.empty() ? "?" : created_at) + "（base=" + base_kind +
                (!base_version_id.empty()
                     ? ":" + utf8_codepoint_prefix(base_version_id, 12)
                     : "") +
                "）"));
        const Json evidence_refs =
            latest_revision->contains("evidence_refs") &&
                    latest_revision->at("evidence_refs").is_array()
                ? latest_revision->at("evidence_refs")
                : Json::array();
        if (!evidence_refs.empty()) {
            std::string joined;
            for (const Json& ref : evidence_refs) {
                if (!joined.empty()) joined += "；";
                joined += ref.is_string() ? ref.get_ref<const std::string&>()
                                          : (ref.is_null() ? "None" : py_str(ref));
            }
            rows.push_back(row("依据证据", joined));
        }
    }
    // FUSION_CONFLICT_KEYS order (integrated_interpretation.py, verbatim).
    static const std::array<const char*, 4> kConflictKeys{{
        "low_confidence_fraction",
        "mean_conflict_fraction",
        "high_conflict_fraction",
        "low_margin_fraction",
    }};
    for (const char* key : kConflictKeys) {
        const auto it = conflicts.find(key);
        if (it != conflicts.end()) {
            rows.push_back(row(std::string("冲突·") + key, py_str(*it)));
        }
    }
    return InterpretationSummary{
        str_field(interpretation, "interpretation_id"),
        str_field(interpretation, "name") + "（" +
            str_field(interpretation, "layer_id") + "）",
        std::move(rows)};
}

}  // namespace pwb::workflow_interpretation
