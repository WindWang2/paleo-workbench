#include "pwb/catalog/policies.hpp"

#include <algorithm>
#include <map>
#include <set>
#include <sstream>

namespace pwb::catalog {

namespace {

// ASCII case fold (entity_view.hpp search_fold precedent: identical to
// Python casefold for the ASCII + CJK values these tables contain).
std::string folded(std::string_view text) {
    std::string out(text);
    for (char& c : out) {
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    }
    return out;
}

std::string stripped(std::string_view text) {
    std::size_t begin = 0;
    std::size_t end = text.size();
    while (begin < end && std::isspace(static_cast<unsigned char>(text[begin]))) ++begin;
    while (end > begin && std::isspace(static_cast<unsigned char>(text[end - 1]))) --end;
    return std::string(text.substr(begin, end - begin));
}

// Python str(value) shapes for the JSON scalars governance sees.
std::string py_str(const domain::Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_boolean()) return value.get<bool>() ? "True" : "False";
    if (value.is_number_integer()) return value.dump();
    if (value.is_number_float()) return value.dump();
    if (value.is_null()) return "None";
    return value.dump();
}

// Python repr() for the error texts (single quotes, minimal escapes).
std::string py_repr(std::string_view text) {
    std::string out = "'";
    for (char c : text) {
        if (c == '\\' || c == '\'') out.push_back('\\');
        out.push_back(c);
    }
    out.push_back('\'');
    return out;
}

// " ".join(str(value).split()) — whitespace run collapse.
std::string collapsed(std::string_view text) {
    std::string out;
    bool pending = false;
    for (char c : text) {
        if (std::isspace(static_cast<unsigned char>(c))) {
            pending = !out.empty();
        } else {
            if (pending) out.push_back(' ');
            pending = false;
            out.push_back(c);
        }
    }
    return out;
}

std::string join_vocab(const std::vector<std::string>& vocab) {
    std::string out;
    for (std::size_t i = 0; i < vocab.size(); ++i) {
        if (i) out += "、";
        out += vocab[i];
    }
    return out;
}

template <typename Map>
const typename Map::mapped_type* lookup(const Map& m, std::string_view key) {
    auto it = m.find(std::string(key));
    return it == m.end() ? nullptr : &it->second;
}

using PairList = std::vector<std::pair<std::string, std::string>>;

std::map<std::string, std::string> to_map(const PairList& pairs) {
    return std::map<std::string, std::string>(pairs.begin(), pairs.end());
}

}  // namespace

// ---- governance ------------------------------------------------------------

const std::vector<GovernanceFieldSpec>& governance_fields() {
    static const std::vector<GovernanceFieldSpec> kFields = {
        {"source", "来源", {}, {}, {}},
        {"region", "区域", {}, {}, {}},
        {"creator", "负责人", {}, {}, {}},
        {"discipline",
         "学科方向",
         {"seismic", "well_log", "horizon", "interpretation", "correlation",
          "fault", "factor_map", "prediction", "paleomap", "qc", "export",
          "modeling", "general"},
         {{"seismic", "地震"},
          {"well_log", "测井"},
          {"horizon", "层位"},
          {"interpretation", "解释"},
          {"correlation", "地层对比"},
          {"fault", "断层"},
          {"factor_map", "因子制图"},
          {"prediction", "预测"},
          {"paleomap", "古地图编制"},
          {"qc", "质量控制"},
          {"export", "成果导出"},
          {"modeling", "三维建模"},
          {"general", "综合"}},
         {{"seismic", "seismic"},
          {"well_log", "well_log"},
          {"well_log_prediction", "well_log"},
          {"welllog", "well_log"},
          {"horizon", "horizon"},
          {"interpretation", "interpretation"},
          {"correlation", "correlation"},
          {"stratigraphy", "correlation"},
          {"well_stratification", "correlation"},
          {"fault", "fault"},
          {"factor_map", "factor_map"},
          {"interpolation", "factor_map"},
          {"prediction", "prediction"},
          {"paleomap", "paleomap"},
          {"mapping", "paleomap"},
          {"qc", "qc"},
          {"export", "export"},
          {"modeling", "modeling"},
          {"general", "general"},
          {"tabular", "general"},
          {"spreadsheet", "general"},
          {"document", "general"},
          {"image_reference", "general"},
          {"reference_map", "general"},
          {"well_reference", "well_log"},
          {"time_depth", "well_log"},
          {"raster", "general"},
          {"vector", "general"},
          {"unknown", "general"}}},
        {"confidence",
         "可信等级",
         {"high", "medium", "low"},
         {{"high", "高"}, {"medium", "中"}, {"low", "低"}},
         {{"high", "high"},
          {"h", "high"},
          {"a", "high"},
          {"高", "high"},
          {"medium", "medium"},
          {"m", "medium"},
          {"b", "medium"},
          {"中", "medium"},
          {"low", "low"},
          {"l", "low"},
          {"c", "low"},
          {"低", "low"}}},
        {"review_status",
         "审核状态",
         {"draft", "pending_review", "approved", "rejected"},
         {{"draft", "草稿"},
          {"pending_review", "待审核"},
          {"approved", "已通过"},
          {"rejected", "已驳回"}},
         {{"draft", "draft"},
          {"草稿", "draft"},
          {"pending_review", "pending_review"},
          {"pending", "pending_review"},
          {"待审核", "pending_review"},
          {"approved", "approved"},
          {"已通过", "approved"},
          {"通过", "approved"},
          {"rejected", "rejected"},
          {"已驳回", "rejected"},
          {"驳回", "rejected"}}},
    };
    return kFields;
}

namespace {
const GovernanceFieldSpec* field(std::string_view key) {
    for (const auto& spec : governance_fields()) {
        if (spec.key == key) return &spec;
    }
    return nullptr;
}
}  // namespace

domain::Result<std::string> normalize_governance_value(
    std::string_view key, const domain::Json& value) {
    const GovernanceFieldSpec* spec = field(key);
    if (spec == nullptr) {
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "unknown governance field: " + py_repr(key));
    }
    if (value.is_null()) return std::string("");
    std::string text = collapsed(py_str(value));
    if (text.empty()) return std::string("");
    if (spec->vocabulary.empty()) {
        return text.substr(0, 200);
    }
    const auto aliases = to_map(spec->aliases);
    std::string lowered = folded(text);
    std::string canonical;
    if (const std::string* hit = lookup(aliases, lowered)) {
        canonical = *hit;
    } else if (const std::string* hit2 = lookup(aliases, text)) {
        canonical = *hit2;
    }
    if (canonical.empty()) {
        const std::vector<std::string>& v = spec->vocabulary;
        if (std::find(v.begin(), v.end(), lowered) != v.end()) {
            canonical = lowered;
        } else if (std::find(v.begin(), v.end(), text) != v.end()) {
            canonical = text;
        }
    }
    if (canonical.empty()) {
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            spec->label + "(" + std::string(key) + ") 的值 " + py_repr(text) +
                " 不在受控词表中: " + join_vocab(spec->vocabulary));
    }
    return canonical;
}

domain::Result<domain::Json> normalize_governance_patch(const domain::Json& patch) {
    if (!patch.is_object()) {
        return domain::DataError(domain::ErrorCode::InvalidArgument,
                                 "governance patch must be an object");
    }
    static const std::set<std::string> kReserved = {"format", "external",
                                                    "trash", "legacy_tags"};
    domain::Json result = domain::Json::object();
    for (auto it = patch.begin(); it != patch.end(); ++it) {
        if (kReserved.count(it.key())) {
            return domain::DataError(
                domain::ErrorCode::InvalidArgument,
                "字段 " + py_repr(it.key()) +
                    " 是目录内部保留键，不能通过治理信息修改");
        }
        if (field(it.key()) != nullptr) {
            auto normalized = normalize_governance_value(it.key(), it.value());
            if (!normalized.is_ok()) return normalized.error();
            result[it.key()] = normalized.value();
        } else {
            result[it.key()] = it.value();
        }
    }
    return result;
}

domain::Json governance_values(const domain::Json& metadata) {
    domain::Json out = domain::Json::object();
    if (!metadata.is_object()) return out;
    for (const auto& spec : governance_fields()) {
        auto it = metadata.find(spec.key);
        if (it == metadata.end()) continue;
        const domain::Json& value = it.value();
        if (value.is_null()) continue;
        if (value.is_string() && value.get<std::string>().empty()) continue;
        out[spec.key] = py_str(value);
    }
    return out;
}

std::string governance_display(std::string_view key, const std::string& value) {
    const GovernanceFieldSpec* spec = field(key);
    if (spec == nullptr || value.empty()) return value;
    for (const auto& [v, label] : spec->display) {
        if (v == value) return label;
    }
    return value;
}

std::vector<std::pair<std::string, std::string>> governance_display_rows(
    const domain::Json& metadata) {
    std::vector<std::pair<std::string, std::string>> rows;
    domain::Json values = governance_values(metadata);
    for (const auto& spec : governance_fields()) {
        auto it = values.find(spec.key);
        if (it == values.end()) continue;
        rows.emplace_back(
            spec.label,
            governance_display(spec.key, it.value().get<std::string>()));
    }
    return rows;
}

// ---- artifact policy ---------------------------------------------------------

namespace {
const std::map<std::string, ArtifactPolicy>& artifact_table() {
    using Stage = domain::DataStage;
    static const std::map<std::string, ArtifactPolicy> kTable = {
        {"render_temp_svg", {"ephemeral", false, std::nullopt, "",
                             "任务/会话期存续，结束即弃（渲染临时体、预览缓存）"}},
        {"atomic_write_tmp", {"ephemeral", false, std::nullopt, "",
                              "任务/会话期存续，结束即弃（渲染临时体、预览缓存）"}},
        {"workflow_checkpoint", {"ephemeral", false, std::nullopt, "",
                                 "任务/会话期存续，结束即弃（渲染临时体、预览缓存）"}},
        {"seismic_attribute_temp", {"ephemeral", false, std::nullopt, "",
                                    "任务/会话期存续，结束即弃（渲染临时体、预览缓存）"}},
        {"north_arrow_cache", {"cache", false, std::nullopt, "",
                               "可由上游重算的本地缓存；删除无损（指北针 SVG、缩放金字塔）"}},
        {"preview_cache", {"cache", false, std::nullopt, "",
                           "可由上游重算的本地缓存；删除无损（指北针 SVG、缩放金字塔）"}},
        {"interchange_workdir", {"ephemeral", false, std::nullopt, "",
                                 "任务/会话期存续，结束即弃（渲染临时体、预览缓存）"}},
        {"factor_map_grid",
         {"intermediate", true, Stage::Intermediate, "recomputable",
          "科学过程正式中间成果（因子格网、预测中间体）"}},
        {"prediction_intermediate",
         {"intermediate", true, Stage::Intermediate, "recomputable",
          "科学过程正式中间成果（因子格网、预测中间体）"}},
        {"seismic_attribute", {"derived", true, Stage::Derived, "user",
                               "具科学语义的衍生成果（解释、属性体）"}},
        {"curve_interpretation", {"derived", true, Stage::Derived, "user",
                                  "具科学语义的衍生成果（解释、属性体）"}},
        {"horizon_interpretation", {"derived", true, Stage::Derived, "user",
                                    "具科学语义的衍生成果（解释、属性体）"}},
        {"fault_interpretation", {"derived", true, Stage::Derived, "user",
                                  "具科学语义的衍生成果（解释、属性体）"}},
        {"constraint_group", {"derived", true, Stage::Derived, "user",
                              "具科学语义的衍生成果（解释、属性体）"}},
        {"geomodel", {"derived", true, Stage::Derived, "user",
                      "具科学语义的衍生成果（解释、属性体）"}},
        {"map_product", {"output", true, Stage::Output, "user",
                         "用户认可的最终成果（成图产品、导出件）"}},
        {"qc_report", {"output", true, Stage::Output, "user",
                       "用户认可的最终成果（成图产品、导出件）"}},
        {"export", {"output", true, Stage::Output, "user",
                    "用户认可的最终成果（成图产品、导出件）"}},
        {"map_compile", {"output", true, Stage::Output, "user",
                         "用户认可的最终成果（成图产品、导出件）"}},
    };
    return kTable;
}
}  // namespace

ArtifactPolicy artifact_policy_for(std::string_view kind) {
    std::string key = stripped(kind);
    auto it = artifact_table().find(key);
    if (it != artifact_table().end()) return it->second;
    ArtifactPolicy fallback;
    fallback.artifact_class = "intermediate";
    fallback.must_register = true;
    fallback.data_stage = domain::DataStage::Intermediate;
    fallback.retention_class = "recomputable";
    fallback.rationale = "未登记 kind " + py_repr(key) +
                         "——按 INTERMEDIATE 兜底（请补 KNOWN_ARTIFACT_POLICIES）";
    return fallback;
}

bool is_registered_artifact_kind(std::string_view kind) {
    return artifact_table().count(stripped(kind)) != 0;
}

const std::vector<std::pair<std::string, const ArtifactPolicy*>>&
known_artifact_policies() {
    static const std::vector<std::pair<std::string, const ArtifactPolicy*>> kList = [] {
        std::vector<std::pair<std::string, const ArtifactPolicy*>> out;
        for (const auto& [key, policy] : artifact_table()) {
            out.emplace_back(key, &policy);
        }
        return out;
    }();
    return kList;
}

// ---- port roles ---------------------------------------------------------------

const std::vector<std::pair<std::string, std::string>>& known_port_roles() {
    static const std::vector<std::pair<std::string, std::string>> kRoles = {
        {"well_logs", "测井曲线"},
        {"sonic", "曲线"},
        {"density", "曲线"},
        {"gamma", "曲线"},
        {"resistivity", "曲线"},
        {"lithology", "曲线"},
        {"trajectory", "井斜"},
        {"tops", "分层"},
        {"time_depth", "时深"},
        {"checkshot", "时深"},
        {"seismic_volume", "地震体"},
        {"horizon", "层位"},
        {"faults", "断层"},
        {"constraints", "制图约束"},
        {"constraint_groups", "制图约束"},
        {"factor_grids", "因子格网"},
        {"factor_grid", "因子格网"},
        {"basemap", "底图"},
        {"model", "模型"},
        {"model_version", "模型"},
        {"stratigraphy", "地层框架"},
        {"prediction", "预测结果"},
        {"normalized_log", "标准化曲线"},
        {"fusion_result", "融合结果"},
        {"map_product", "成图产品"},
        {"correlation", "对比成果"},
        {"calibrated_td", "标定时深"},
        {"qc_report", "QC 报告"},
        {"export", "导出"},
        {"interpretation", "解释成果"},
        {"manual_edit", "人工修改"},
    };
    return kRoles;
}

std::string port_role_display(std::string_view role) {
    if (role.empty()) return std::string();
    for (const auto& [name, label] : known_port_roles()) {
        if (name == role) return label;
    }
    return std::string(role);
}

// ---- model gates ---------------------------------------------------------------

std::pair<bool, std::string> can_promote_to_production(
    const std::optional<ModelGateFacts>& model,
    const std::optional<ModelVersionGateFacts>& version,
    const std::optional<std::string>& lookup_error,
    bool require_input_schema) {
    if (lookup_error.has_value()) {
        return {false, *lookup_error};
    }
    if (!model.has_value() || !version.has_value()) {
        return {false, "model or model version not found"};
    }
    if (version->demo_only) {
        return {false, "demo_only model versions cannot be promoted to production"};
    }
    std::string provider = stripped(model->provider);
    std::string provider_folded = folded(provider);
    for (std::string_view banned : kNonPromotableProviders) {
        if (provider_folded == folded(stripped(banned))) {
            return {false, "provider " + py_repr(model->provider) +
                               " is not promotable to production"};
        }
    }
    std::string model_type = stripped(model->model_type);
    std::string type_folded = folded(model_type);
    for (std::string_view banned : kNonPromotableModelTypes) {
        if (type_folded == folded(stripped(banned))) {
            return {false, "model_type " + py_repr(model->model_type) +
                               " is not promotable to production"};
        }
    }
    auto scientific_false = [](const domain::Json& metadata) {
        return metadata.is_object() && metadata.contains("scientific") &&
               metadata["scientific"].is_boolean() &&
               metadata["scientific"].get<bool>() == false;
    };
    if (scientific_false(model->metadata)) {
        return {false, "model metadata marks scientific=False"};
    }
    if (scientific_false(version->metadata)) {
        return {false, "version metadata marks scientific=False (H4-3b)"};
    }
    if (require_input_schema &&
        (version->input_schema.is_null() || !version->input_schema.is_object() ||
         version->input_schema.empty())) {
        return {false, "input_schema is required for production promotion (H5-b)"};
    }
    return {true, "ok"};
}

}  // namespace pwb::catalog
