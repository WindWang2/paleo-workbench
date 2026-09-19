#include "pwb/ui_workstation/inspector_spec.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include <pwb/ui_workstation/state_language.hpp>

namespace pwb::ui_workstation {

const std::vector<std::string>& inspector_page_titles() {
    static const std::vector<std::string> titles = {
        "属性", "解释", "样式", "历史",
    };
    return titles;
}

namespace {

// getattr-parity read: missing key == Python None == "".
std::string f(const InspectorPayload& p, const std::string& key) {
    const auto it = p.fields.find(key);
    return it != p.fields.end() ? it->second : "";
}

int count(const InspectorPayload& p, const std::string& key) {
    const auto it = p.list_counts.find(key);
    return it != p.list_counts.end() ? it->second : 0;
}

// Python `value or fallback` for strings (empty/whitespace is falsy).
std::string or_default(const std::string& value, const std::string& dflt) {
    const bool empty = value.find_first_not_of(" \t\n") == std::string::npos;
    return empty ? dflt : value;
}

void row(std::vector<std::pair<std::string, std::string>>& rows,
         const std::string& label, const std::string& value) {
    rows.emplace_back(label, value);
}

// _readonly + unit: "123 m"; unparseable → "123 m" anyway (Python keeps
// the text on ValueError). Missing → "" (renders "—" with missing flag).
std::string with_unit(const std::string& value, const std::string& unit) {
    if (inspector_value_missing(value)) return "";
    if (unit.empty()) return value;
    return value + " " + unit;
}

// State row through the state_language vocabulary (unknown → "—";
// Python _add_state_row). Throws-free: unknown values → "—".
void state_row(std::vector<std::pair<std::string, std::string>>& rows,
               const std::string& label, const std::string& category,
               const std::string& value) {
    if (value.empty()) {
        row(rows, label, "");
        return;
    }
    const StateToken token = state_token(category, value);
    row(rows, label, token.glyph + " " + token.label);
}

// _VERTICAL_DOMAIN_LABELS parity.
std::string vertical_domain_label(const std::string& domain) {
    static const std::map<std::string, std::string> labels = {
        {"twt", "双程时间 (TWT)"}, {"depth", "深度"},
        {"time", "时间"},
    };
    const auto it = labels.find(domain);
    return it != labels.end() ? it->second : domain;
}

// show_feature's _GEOMETRY_LABELS parity.
std::string geometry_label(const std::string& type) {
    static const std::map<std::string, std::string> labels = {
        {"Point", "点"},          {"MultiPoint", "多点"},
        {"LineString", "线"},     {"MultiLineString", "多线"},
        {"Polygon", "面"},        {"MultiPolygon", "多面"},
    };
    const auto it = labels.find(type);
    return it != labels.end() ? it->second : type;
}

// --- builders (Python show_* parity) ----------------------------------

InspectorDocument doc_project(const InspectorPayload& p) {
    InspectorDocument d;
    d.header = "检查器 · 工程";
    row(d.properties_rows, "工程名", f(p, "name"));
    row(d.properties_rows, "区域", f(p, "region"));
    row(d.properties_rows, "CRS", f(p, "project_crs"));
    row(d.properties_rows, "井", f(p, "wells_count") + " 口");
    row(d.properties_rows, "地震", f(p, "seismic_count") + " 个");
    row(d.interpretation_rows, "目标层位", f(p, "target_horizon"));
    d.history_rows = {"工程上下文已绑定", "工作区布局可保存和恢复"};
    return d;
}

InspectorDocument doc_well(const InspectorPayload& p,
                           const std::string& target_horizon) {
    InspectorDocument d;
    const std::string name = or_default(f(p, "name"), "未命名井");
    d.header = "检查器 · 井 " + name;
    row(d.properties_rows, "井名", name);
    row(d.properties_rows, "井 ID", f(p, "id"));
    row(d.properties_rows, "坐标 X", f(p, "project_x"));
    row(d.properties_rows, "坐标 Y", f(p, "project_y"));
    row(d.properties_rows, "KB 高程", with_unit(f(p, "kb"), "m"));
    row(d.properties_rows, "总深度", with_unit(f(p, "td"), "m"));
    // 关联数据角色概要（adapter renders "role×n / role×m"; empty → "—").
    row(d.properties_rows, "关联数据", f(p, "asset_roles"));
    row(d.interpretation_rows, "活动层位", target_horizon);
    // 联动状态：adapter resolves 井位坐标/轨迹 from live data.
    row(d.interpretation_rows, "联动状态", f(p, "link_state"));
    d.history_rows = {"已选择井 " + name, "选择通过共享 SelectionContext 发布"};
    return d;
}

InspectorDocument doc_resource(const InspectorPayload& p,
                               const std::string& target_horizon) {
    InspectorDocument d;
    const std::string name = or_default(f(p, "name"), "未命名数据");
    d.header = "检查器 · " + name;
    row(d.properties_rows, "名称", name);
    row(d.properties_rows, "类型", f(p, "type"));
    row(d.properties_rows, "格式", f(p, "format"));
    row(d.properties_rows, "路径", f(p, "path"));
    row(d.properties_rows, "状态", f(p, "status"));
    row(d.interpretation_rows, "活动层位", target_horizon);
    d.history_rows = {"项目数据对象",
                      "存储详情可在数据目录高级视图中查看"};
    return d;
}

InspectorDocument doc_horizon(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string name = f(p, "name");
    d.header = "检查器 · " + or_default(name, "层位");
    row(d.properties_rows, "名称", name);
    row(d.properties_rows, "类型",
        or_default(f(p, "entity_kind"), f(p, "type")));
    row(d.properties_rows, "格式", f(p, "format"));
    row(d.properties_rows, "路径", f(p, "path"));
    row(d.properties_rows, "CRS", f(p, "crs"));
    row(d.properties_rows, "域",
        vertical_domain_label(f(p, "vertical_domain")));
    row(d.interpretation_rows, "层位", name);
    row(d.interpretation_rows, "状态", f(p, "status"));
    row(d.interpretation_rows, "解释版本",
        f(p, "interpretation_version"));
    d.history_rows = {name.empty() ? "层位" : "层位 " + name};
    const std::string shape = f(p, "shape_text");
    if (!shape.empty()) d.history_rows.push_back("构件 " + shape);
    const std::string artifact = f(p, "artifact_path");
    if (!artifact.empty()) d.history_rows.push_back(artifact);
    return d;
}

InspectorDocument doc_seismic(const InspectorPayload& p,
                              const std::string& target_horizon) {
    InspectorDocument d;
    const std::string label =
        or_default(f(p, "name"), "地震数据");
    d.header = "检查器 · " + label;
    const std::string type =
        f(p, "survey_type") == "3d"
            ? "三维 (3D)"
            : (f(p, "survey_type") == "2d" ? "二维 (2D)" : "地震数据");
    row(d.properties_rows, "名称", label);
    row(d.properties_rows, "类型", type);
    row(d.properties_rows, "格式", f(p, "format"));
    row(d.properties_rows, "路径", f(p, "path"));
    row(d.properties_rows, "Inline 范围", f(p, "inline_range_text"));
    row(d.properties_rows, "Crossline 范围",
        f(p, "crossline_range_text"));
    row(d.interpretation_rows, "活动层位", target_horizon);
    d.history_rows = {"地震数据 " + label};
    return d;
}

InspectorDocument doc_map_component(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string name = or_default(f(p, "name"), "图件组件");
    d.header = "检查器 · " + name;
    row(d.properties_rows, "名称", name);
    row(d.properties_rows, "组件类型", f(p, "component_type"));
    row(d.properties_rows, "位置", f(p, "position_text"));
    row(d.properties_rows, "可见", inspector_yes_no(f(p, "visible")));
    d.history_rows = {"图件组件 " + name};
    return d;
}

InspectorDocument doc_curve(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string mnemonic =
        or_default(f(p, "mnemonic"), f(p, "curve_name"));
    d.header = "检查器 · 曲线 " + or_default(mnemonic, "—");
    row(d.properties_rows, "曲线名", mnemonic);
    row(d.properties_rows, "井",
        or_default(f(p, "well"), f(p, "well_name")));
    row(d.properties_rows, "单位", f(p, "unit"));
    row(d.properties_rows, "深度",
        with_unit(or_default(f(p, "depth"), f(p, "md")), "m"));
    row(d.properties_rows, "值",
        or_default(f(p, "value"), f(p, "amplitude")));
    row(d.interpretation_rows, "提示",
        "拾取自测井引擎；校正操作产生 DERIVED 版本，RAW 不变");
    d.history_rows = {"曲线拾取进入检查器（V6）"};
    return d;
}

InspectorDocument doc_feature(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string name =
        or_default(f(p, "layer_name"), or_default(f(p, "name"), "要素"));
    d.header = "检查器 · 要素 · " + name;
    row(d.properties_rows, "要素 ID", f(p, "feature_id"));
    row(d.properties_rows, "图层", f(p, "layer_name"));
    row(d.properties_rows, "几何", geometry_label(f(p, "geometry_type")));
    row(d.properties_rows, "可编辑", inspector_yes_no(f(p, "editable")));
    int shown = 0;
    for (const auto& [key, value] : p.attributes) {
        row(d.properties_rows, key, value);
        if (++shown >= 12) break;
    }
    if (static_cast<int>(p.attributes.size()) > 12) {
        row(d.interpretation_rows, "属性",
            "共 " + std::to_string(p.attributes.size()) +
                " 项（显示前 12）");
    }
    const std::string tmpl = f(p, "template");
    if (!tmpl.empty()) row(d.interpretation_rows, "模板角色", tmpl);
    row(d.interpretation_rows, "来源", or_default(f(p, "source"), "identify"));
    d.feature_assign_button = true;  // 指定相带… (Q3-d)
    const std::string fid = f(p, "feature_id");
    d.history_rows = {"要素 " + (fid.empty() ? std::string("—") : fid)};
    return d;
}

InspectorDocument doc_factor(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string title =
        or_default(f(p, "name"), "单因素");
    d.header = "检查器 · 单因素 · " + title;
    const std::string task_id = or_default(f(p, "id"), "—");
    d.history_rows = {"单因素任务 " + task_id};
    if (!p.summary_rows.empty()) {
        // V9 summary contract: adapter-projected rows win over the
        // internal-model fallback.
        for (const auto& [label, value, state] : p.summary_rows) {
            std::string text = inspector_value_missing(value) ? "—" : value;
            if (state == "missing") {
                text += "（缺失）";
            } else if (state == "unknown") {
                text += "（未知）";
            } else if (state == "warn") {
                text += "（注意）";
            }
            row(d.properties_rows, label, text);
        }
        return d;
    }
    row(d.properties_rows, "因素", f(p, "factor_type"));
    row(d.properties_rows, "目标层位", f(p, "target_horizon"));
    row(d.properties_rows, "方法", f(p, "method"));
    row(d.properties_rows, "单位", f(p, "unit"));
    const std::string params = f(p, "parameters_compact");
    if (!params.empty()) row(d.properties_rows, "参数", params);
    const std::string gmin = f(p, "grid_min"), gmax = f(p, "grid_max");
    if (!gmin.empty() && !gmax.empty()) {
        row(d.properties_rows, "取值范围", gmin + " ~ " + gmax);
    }
    const std::string unc = f(p, "uncertainty_text");
    if (!unc.empty()) row(d.properties_rows, "不确定性", unc);
    const std::string quality = f(p, "quality_compact");
    if (!quality.empty()) row(d.properties_rows, "QC", quality);
    const std::string snapshot = f(p, "input_snapshot_hash");
    row(d.interpretation_rows, "源版本",
        snapshot.size() > 12 ? snapshot.substr(0, 12) + "…" : snapshot);
    row(d.interpretation_rows, "源类型", f(p, "source_kind"));
    row(d.interpretation_rows, "状态", f(p, "status"));
    return d;
}

InspectorDocument doc_map_product(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string name = or_default(f(p, "product_name"), "MapProduct");
    d.header = "检查器 · 成果 · " + name;
    row(d.properties_rows, "产品", name);
    std::string status = f(p, "status");
    if (f(p, "frozen") == "1" || f(p, "frozen") == "true") {
        status = "已冻结";
    } else if (status == "final") {
        status = "最终";
    } else if (status == "superseded") {
        status = "已被取代";
    }
    row(d.properties_rows, "状态", status);
    const int factor_ids = count(p, "factor_task_ids");
    if (factor_ids > 0) {
        row(d.properties_rows, "因子输入",
            std::to_string(factor_ids) + " 项");
    }
    const int refs = count(p, "interpretation_refs");
    if (refs > 0) {
        row(d.properties_rows, "解释引用", std::to_string(refs) + " 项");
    }
    row(d.properties_rows, "运行", f(p, "run_id"));
    row(d.properties_rows, "输出版本", f(p, "output_version_id"));
    const std::string fp = f(p, "scientific_fingerprint");
    row(d.properties_rows, "指纹",
        fp.size() > 16 ? fp.substr(0, 16) + "…" : fp);
    const int adj = count(p, "manual_adjustments");
    row(d.properties_rows, "手工调整",
        adj > 0 ? std::to_string(adj) + " 项" : "无");
    const std::string staleness = f(p, "staleness_text");
    if (!staleness.empty()) {
        row(d.interpretation_rows, "新鲜度", staleness);
    }
    const std::string readiness = f(p, "readiness");
    if (!readiness.empty()) {
        row(d.interpretation_rows, "发布就绪", readiness);
    }
    d.history_rows = {"MapProduct " + or_default(f(p, "id"), "—")};
    return d;
}

InspectorDocument doc_version(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string name =
        or_default(f(p, "asset_name"), or_default(f(p, "name"), "版本"));
    const std::string number = f(p, "version_number");
    d.header = "检查器 · 版本 · " + name +
               (number.empty() ? "" : " v" + number);
    row(d.properties_rows, "资产", name);
    if (!number.empty()) row(d.properties_rows, "版本号", "v" + number);
    state_row(d.properties_rows, "阶段", "maturity",
              or_default(f(p, "stage"), f(p, "life_stage")));
    const std::string created = f(p, "created_at");
    if (!created.empty()) row(d.properties_rows, "创建时间", created);
    const std::string checksum =
        or_default(f(p, "checksum"), f(p, "sha256"));
    row(d.properties_rows, "SHA-256",
        checksum.size() > 12 ? checksum.substr(0, 12) + "…" : checksum);
    const int parents = count(p, "parent_ids") + count(p, "parent_version_ids");
    row(d.properties_rows, "父版本",
        parents > 0 ? std::to_string(parents) + " 项"
                    : "源头（无父版本）");
    row(d.properties_rows, "生成 Run", f(p, "run_id"));
    row(d.interpretation_rows, "来源",
        or_default(f(p, "source"), f(p, "source_kind")));
    const auto downstream = p.list_counts.find("downstream_count");
    if (downstream != p.list_counts.end()) {
        row(d.interpretation_rows, "下游",
            downstream->second > 0
                ? std::to_string(downstream->second) + " 项"
                : "无");
    }
    if (f(p, "trashed") == "1" || f(p, "trashed") == "true") {
        row(d.interpretation_rows, "回收站", "已在回收站");
    }
    d.history_rows = {"版本 " +
                      or_default(or_default(f(p, "version_id"), f(p, "id")),
                                 "—")};
    return d;
}

InspectorDocument doc_run(const InspectorPayload& p) {
    InspectorDocument d;
    std::string run_id =
        or_default(f(p, "run_id"), or_default(f(p, "id"), "Run"));
    d.header = "检查器 · Run · " +
               (run_id.size() > 16 ? run_id.substr(0, 16) : run_id);
    row(d.properties_rows, "Run ID", run_id);
    row(d.properties_rows, "操作", f(p, "operation"));
    // Status vocabulary remap (Python dict.get(status, status or None)).
    const std::string raw_status = f(p, "status");
    const std::map<std::string, std::string> remap = {
        {"complete", "done"}, {"completed", "done"},
        {"pending", "queued"}, {"running", "running"},
        {"failed", "failed"},  {"warning", "degraded"},
    };
    const auto it = remap.find(raw_status);
    state_row(d.properties_rows, "状态", "task",
              it != remap.end() ? it->second : raw_status);
    const int inputs = count(p, "input_version_ids") + count(p, "inputs");
    if (inputs > 0) {
        row(d.properties_rows, "输入版本", std::to_string(inputs) + " 项");
    }
    const int outputs =
        count(p, "output_version_ids") + count(p, "outputs");
    if (outputs > 0) {
        row(d.properties_rows, "输出版本", std::to_string(outputs) + " 项");
    }
    row(d.interpretation_rows, "模型",
        or_default(f(p, "model"), f(p, "model_type")));
    const std::string params = f(p, "parameters_compact");
    if (!params.empty()) {
        row(d.interpretation_rows, "参数",
            inspector_compact_text(params));
    }
    const std::string started = f(p, "started_at");
    if (!started.empty()) {
        row(d.interpretation_rows, "开始",
            started + inspector_elapsed_text(started, f(p, "finished_at")));
    }
    d.history_rows = {"Run " + run_id};
    return d;
}

InspectorDocument doc_layer(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string layer_type = or_default(f(p, "layer_type"), "图层");
    d.header = "检查器 · " + layer_type;
    row(d.properties_rows, "类型", layer_type);
    row(d.properties_rows, "作用域", "当前文档");
    for (const auto& [label, value] : p.seam_rows) {
        row(d.properties_rows, label, value);
    }
    row(d.properties_rows, "可见", inspector_yes_no(f(p, "visible")));
    const auto it = p.list_counts.find("features");
    if (it != p.list_counts.end()) {
        row(d.properties_rows, "要素数", std::to_string(it->second));
    }
    return d;
}

InspectorDocument doc_generic(const InspectorPayload& p) {
    InspectorDocument d;
    const std::string name = f(p, "name");
    d.header = name.empty() ? "检查器" : "检查器 · " + name;
    std::vector<std::pair<std::string, std::string>> rows;
    // Payload scalar keys first (sorted — std::map), minus "object".
    for (const auto& [key, value] : p.fields) {
        if (key == "object") continue;
        rows.emplace_back(key, inspector_compact_text(value));
    }
    // Then the _OBJECT_ATTR_ROWS object attributes the adapter surfaced.
    for (const auto& [key, value] : p.attrs) {
        const bool seen = std::any_of(
            rows.begin(), rows.end(),
            [&](const auto& r) { return r.first == key; });
        if (!seen) rows.emplace_back(key, inspector_compact_text(value));
    }
    if (rows.empty()) rows.emplace_back("状态", "无属性");
    d.properties_rows = std::move(rows);
    return d;
}

}  // namespace

bool inspector_value_missing(const std::string& value) {
    const auto pos = value.find_first_not_of(" \t\n");
    return pos == std::string::npos || value == "—";
}

std::string inspector_yes_no(const std::string& value) {
    if (value.empty()) return "";
    return (value == "0" || value == "false" || value == "False")
               ? "否"
               : "是";
}

std::string inspector_compact_text(const std::string& value) {
    return value.size() <= 80 ? value : value.substr(0, 77) + "…";
}

std::string inspector_elapsed_text(const std::string& started,
                                   const std::string& finished) {
    if (finished.empty()) return "";
    try {
        const double s = std::stod(started);
        const double e = std::stod(finished);
        char buf[64];
        std::snprintf(buf, sizeof(buf), "（耗时 %.1fs）",
                      std::max(0.0, e - s));
        return buf;
    } catch (...) {
        return "";
    }
}

InspectorDocument empty_inspector_document() {
    InspectorDocument d;
    d.header = "检查器";
    row(d.properties_rows, "状态", "未选择对象");
    return d;
}

namespace {

// _update_style_page parity: honest summary + edit entry only for
// layer/user_vector_layer payloads (layer_id or id key).
void apply_style_page(const InspectorPayload& p,
                      InspectorDocument& d) {
    const std::string layer_id =
        !f(p, "layer_id").empty() ? f(p, "layer_id") : f(p, "id");
    if ((p.kind == "layer" || p.kind == "user_vector_layer") &&
        !layer_id.empty()) {
        std::vector<std::string> facts;
        const std::string name =
            !f(p, "name").empty() ? f(p, "name") : f(p, "title");
        if (!name.empty()) facts.push_back("图层 " + name);
        const std::string geometry = f(p, "geometry_kind");
        if (!geometry.empty()) facts.push_back("几何 " + geometry);
        const auto it = p.list_counts.find("feature_count");
        if (it != p.list_counts.end()) {
            facts.push_back(std::to_string(it->second) + " 个要素");
        }
        std::string joined;
        for (std::size_t i = 0; i < facts.size(); ++i) {
            if (i) joined += "、";
            joined += facts[i];
        }
        d.style_summary =
            joined +
            "\n\n样式、标注与渲染规则在图层属性中编辑（与编图画布同一套"
            "符号系统）。";
        d.style_edit_visible = true;
        d.style_edit_layer_id = layer_id;
        return;
    }
    if (p.kind == "map_component") {
        d.style_summary =
            "图件组件的样式（字体、颜色、位置）在编图组件面板中编辑。";
        return;
    }
    d.style_summary =
        "当前选择没有可编辑的地图样式。\n\n图层样式：在资源树或图层面板"
        "选择图层；图件组件样式：在编图组件面板中选择组件。";
}

}  // namespace

InspectorDocument build_inspector_document(
    const InspectorPayload& payload, const std::string& target_horizon) {
    const std::string& kind = payload.kind;
    InspectorDocument d;
    if (kind == "well") {
        d = doc_well(payload, target_horizon);
    } else if (kind == "horizon" || kind == "interpretation") {
        d = doc_horizon(payload);
    } else if (kind == "layer") {
        d = doc_layer(payload);
    } else if (kind == "project") {
        d = doc_project(payload);
    } else if (kind == "seismic" ||
               (kind == "resource" && f(payload, "type") == "seismic")) {
        d = doc_seismic(payload, target_horizon);
    } else if (kind == "resource") {
        d = doc_resource(payload, target_horizon);
    } else if (kind == "map_component") {
        d = doc_map_component(payload);
    } else if (kind == "curve") {
        d = doc_curve(payload);
    } else if (kind == "feature") {
        d = doc_feature(payload);
    } else if (kind == "factor") {
        d = doc_factor(payload);
    } else if (kind == "map_product") {
        d = doc_map_product(payload);
    } else if (kind == "version") {
        d = doc_version(payload);
    } else if (kind == "run") {
        d = doc_run(payload);
    } else {
        // 未知 kind：通用键值表，不丢弃（B4）。
        d = doc_generic(payload);
    }
    apply_style_page(payload, d);
    return d;
}

}  // namespace pwb::ui_workstation
