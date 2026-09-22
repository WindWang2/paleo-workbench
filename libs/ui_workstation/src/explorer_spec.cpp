#include "pwb/ui_workstation/explorer_spec.hpp"

#include <algorithm>
#include <set>

#include <pwb/ui_workstation/state_language.hpp>

namespace pwb::ui_workstation {

namespace {

// User-layer geometry kind -> icon/label (Python _USER_LAYER_KIND_*).
const std::map<std::string, std::string>& user_layer_kind_icons() {
    static const std::map<std::string, std::string> icons = {
        {"point", "map/add_point.svg"},
        {"line", "map/add_line.svg"},
        {"polygon", "map/add_polygon.svg"},
    };
    return icons;
}
const std::map<std::string, std::string>& user_layer_kind_labels() {
    static const std::map<std::string, std::string> labels = {
        {"point", "点"}, {"line", "线"}, {"polygon", "面"},
    };
    return labels;
}

// Map-document countable layer categories (Python
// _MAP_LAYER_CATEGORY_LABELS, insertion order).
const std::vector<std::pair<std::string, std::string>>&
map_layer_categories() {
    static const std::vector<std::pair<std::string, std::string>> cats = {
        {"line_features", "线要素"},
        {"facies_polygons", "相区面"},
        {"label_features", "标注"},
        {"reference_layers", "参考图层"},
    };
    return cats;
}

// Data-mode resource type -> group label (Python `labels` dict).
const std::map<std::string, std::string>& resource_type_labels() {
    static const std::map<std::string, std::string> labels = {
        {"well_log", "测井"},           {"seismic", "地震"},
        {"well_head", "井位"},          {"well_stratification", "分层"},
        {"horizon", "层位"},            {"geojson", "矢量"},
        {"raster", "栅格"},             {"tabular", "表格"},
        {"document", "参考资料"},       {"image_reference", "参考图像"},
        {"unknown", "其他"},
    };
    return labels;
}

std::string resource_type_label(const std::string& type) {
    const auto it = resource_type_labels().find(type);
    return it != resource_type_labels().end() ? it->second : type;
}

// Path.stem equivalent for entity names (suffix after last '/', minus
// final extension).
std::string stem_of(const std::string& name) {
    std::string base = name;
    const auto slash = base.find_last_of('/');
    if (slash != std::string::npos) base = base.substr(slash + 1);
    const auto dot = base.find_last_of('.');
    if (dot != std::string::npos && dot != 0) base = base.substr(0, dot);
    return base;
}

std::string file_name_of(const std::string& path) {
    const auto slash = path.find_last_of('/');
    return slash == std::string::npos ? path : path.substr(slash + 1);
}

bool visible_resource(const ExplorerResourceFact& resource) {
    if (resource.path.rfind(".preview_cache/", 0) == 0) return false;
    if (resource.name == "meta.json" || resource.name == "payload.npz")
        return false;
    return true;
}

ExplorerNode group_node(const std::string& key, const std::string& label,
                        std::vector<ExplorerNode> children) {
    // Row cap: over-limit groups truncate with a "… 还有 N 项" tail row.
    if (children.size() > static_cast<std::size_t>(kExplorerGroupRowLimit)) {
        const std::size_t remaining =
            children.size() - kExplorerGroupRowLimit;
        children.resize(kExplorerGroupRowLimit);
        ExplorerNode tail;
        tail.key = key + "/truncated";
        tail.label = "… 还有 " + std::to_string(remaining) +
                     " 项（用搜索过滤）";
        tail.payload = {{"kind", "empty"},
                        {"truncated", std::to_string(remaining)}};
        children.push_back(std::move(tail));
    }
    ExplorerNode node;
    node.key = key;
    node.label = label;
    node.payload = {{"kind", "group"}};
    node.icon = "folder.svg";
    node.children = std::move(children);
    return node;
}

ExplorerNode resource_node(const ExplorerResourceFact& resource) {
    ExplorerNode node;
    node.key = "resource/" + resource.id;
    node.label = resource.name.empty() ? "未命名数据" : resource.name;
    node.payload = {{"kind", "resource"},
                    {"resource_type", resource.type}};
    node.tooltip = resource.path;
    node.object = resource.object;
    return node;
}

ExplorerNode user_layer_node(const ExplorerUserLayerFact& layer) {
    const auto kind_it = user_layer_kind_labels().find(layer.geometry_kind);
    const std::string kind_label =
        kind_it != user_layer_kind_labels().end() ? kind_it->second : "矢量";
    ExplorerNode node;
    node.key = "uvlayer/" + layer.id;
    node.label = (layer.name.empty() ? "编修图层" : layer.name) + " · " +
                 kind_label + " · " + std::to_string(layer.feature_count) +
                 " 要素";
    node.payload = {{"kind", "user_vector_layer"}, {"layer_id", layer.id}};
    const auto icon_it = user_layer_kind_icons().find(layer.geometry_kind);
    if (icon_it != user_layer_kind_icons().end()) {
        node.icon = icon_it->second;
    }
    node.check_state = layer.visible ? 2 : 0;  // Qt::Checked / Unchecked
    node.object = layer.object;
    return node;
}

struct Builder {
    const ExplorerFacts& facts;

    ExplorerNode project_root() const {
        ExplorerNode root;
        root.key = "project";
        root.label = facts.project_name.empty() ? "未命名工程"
                                                : facts.project_name;
        root.payload = {{"kind", "project"}};
        root.icon = "folder-open.svg";
        root.object = facts.project_object;
        return root;
    }

    std::vector<const ExplorerResourceFact*> visible_resources() const {
        std::vector<const ExplorerResourceFact*> out;
        for (const auto& r : facts.resources) {
            if (visible_resource(r)) out.push_back(&r);
        }
        return out;
    }

    // (display name, object) sorted-unique horizon list: geological
    // entities first (stemmed); falling back to horizon /
    // well_stratification resources.
    std::vector<std::pair<std::string, const void*>> horizon_objects()
        const {
        std::map<std::string, const void*> unique;
        for (const auto& entity : facts.geological_entities) {
            if (!entity.name.empty()) {
                unique.emplace(stem_of(entity.name), entity.object);
            }
        }
        if (unique.empty()) {
            for (const auto* r : visible_resources()) {
                if (r->type == "horizon" || r->type == "well_stratification") {
                    unique.emplace(stem_of(r->name), r->object);
                }
            }
        }
        return {unique.begin(), unique.end()};
    }

    ExplorerNode well_group() const {
        std::vector<ExplorerNode> children;
        for (std::size_t i = 0; i < facts.wells.size(); ++i) {
            const auto& well = facts.wells[i];
            ExplorerNode node;
            node.key = "well/" + (well.id.empty()
                                      ? std::to_string(i)
                                      : well.id);
            node.label = well.name.empty() ? "未命名井" : well.name;
            node.payload = {{"kind", "well"}, {"well_name", well.name}};
            node.object = nullptr;  // resolved by the host adapter
            children.push_back(std::move(node));
        }
        return group_node("group/wells",
                          "井数据 (" + std::to_string(facts.wells.size()) +
                              ")",
                          std::move(children));
    }

    ExplorerNode seismic_group() const {
        std::vector<ExplorerNode> children;
        int count = 0;
        for (const auto* r : visible_resources()) {
            if (r->type != "seismic") continue;
            children.push_back(resource_node(*r));
            ++count;
        }
        return group_node("group/seismic",
                          "地震数据 (" + std::to_string(count) + ")",
                          std::move(children));
    }

    ExplorerNode horizon_group() const {
        const auto horizons = horizon_objects();
        std::vector<ExplorerNode> children;
        for (const auto& [name, obj] : horizons) {
            ExplorerNode node;
            node.key = "horizon/" + name;
            node.label = name;
            node.payload = {{"kind", "horizon"}, {"name", name}};
            node.object = obj;
            children.push_back(std::move(node));
        }
        return group_node("group/horizons",
                          "层位 / 地层 (" + std::to_string(horizons.size()) +
                              ")",
                          std::move(children));
    }

    ExplorerNode interpretation_group() const {
        // 原型工区树「解释要素」—— 列出真实解释成果；无解释时退回
        // 目标层位节点（target_horizon 权威），再退诚实空态。
        std::vector<ExplorerNode> children;
        for (std::size_t i = 0; i < facts.interpretations.size(); ++i) {
            const auto& interp = facts.interpretations[i];
            ExplorerNode node;
            node.key = "interpretation/" +
                       (interp.id.empty() ? std::to_string(i) : interp.id);
            node.label = interp.name.empty() ? "解释成果" : interp.name;
            if (!interp.current_version_id.empty()) {
                node.label += " " + interp.current_version_id;
            }
            node.payload = {{"kind", "interpretation"},
                            {"id", interp.id}};
            node.object = interp.object;
            children.push_back(std::move(node));
        }
        if (children.empty()) {
            ExplorerNode child;
            if (!facts.target_horizon.empty()) {
                child.key = "interpretation/" + facts.target_horizon;
                child.label = facts.target_horizon;
                child.payload = {{"kind", "interpretation"},
                                 {"name", facts.target_horizon}};
            } else {
                child.key = "interpretation/empty";
                child.label = "未设置目标层位";
                child.payload = {{"kind", "empty"}};
            }
            children.push_back(std::move(child));
        }
        return group_node(
            "group/interpretation",
            "解释要素 (" + std::to_string(children.size()) + ")",
            std::move(children));
    }

    // 原型工区树「约束与单因素图」—— factor_map_tasks + constraint
    // 组的合并投影（facts.factor_maps）；空则整组不出现。
    std::optional<ExplorerNode> factor_map_group() const {
        if (facts.factor_maps.empty()) return std::nullopt;
        std::vector<ExplorerNode> children;
        for (std::size_t i = 0; i < facts.factor_maps.size(); ++i) {
            const auto& entry = facts.factor_maps[i];
            ExplorerNode node;
            node.key = "factormap/" +
                       (entry.id.empty() ? std::to_string(i) : entry.id);
            node.label = entry.name.empty() ? "未命名图" : entry.name;
            node.payload = {{"kind", "factor_map"},
                            {"id", entry.id},
                            {"source_type", entry.type}};
            node.object = entry.object;
            children.push_back(std::move(node));
        }
        return group_node(
            "group/factor-maps",
            "约束与单因素图 (" +
                std::to_string(facts.factor_maps.size()) + ")",
            std::move(children));
    }

    // Null when there are no user vector layers (Python
    // _user_layer_group_node -> None).
    std::optional<ExplorerNode> user_layer_group() const {
        if (facts.user_layers.empty()) return std::nullopt;
        std::vector<ExplorerNode> children;
        for (const auto& layer : facts.user_layers) {
            children.push_back(user_layer_node(layer));
        }
        return group_node("group/user-layers",
                          "编修数据 (" +
                              std::to_string(facts.user_layers.size()) + ")",
                          std::move(children));
    }

    // --- mode builders -------------------------------------------------

    ExplorerSpec spec_project() const {
        ExplorerSpec spec;
        ExplorerNode root = project_root();
        if (!facts.project_open) {
            spec.footer = "未打开工程";
            spec.roots.push_back(std::move(root));
            return spec;
        }
        ExplorerNode overview;
        overview.key = "overview";
        overview.label = "概览";
        overview.payload = {{"kind", "overview"}};
        overview.navigation = std::pair{0, std::string("overview")};
        root.children.push_back(std::move(overview));

        ExplorerNode area;
        area.key = "area";
        area.label = "工区 · " + (facts.workarea_name.empty()
                                      ? std::string("未命名工区")
                                      : facts.workarea_name);
        area.payload = {{"kind", "area"}};
        area.object = facts.workarea_object;
        area.children.push_back(well_group());
        area.children.push_back(seismic_group());
        area.children.push_back(horizon_group());
        area.children.push_back(interpretation_group());
        if (auto group = factor_map_group()) {
            area.children.push_back(std::move(*group));
        }
        if (!facts.map_documents.empty()) {
            // 原型工区树尾部「综合编图」分组 —— 文档计数进组名。
            std::vector<ExplorerNode> docs;
            for (const auto& doc : facts.map_documents) {
                ExplorerNode node;
                node.key = "mapdoc/" + doc.id;
                node.label =
                    doc.name.empty() ? "未命名图件" : doc.name;
                node.payload = {{"kind", "map_document"}, {"id", doc.id}};
                node.object = doc.object;
                docs.push_back(std::move(node));
            }
            area.children.push_back(group_node(
                "group/map-docs",
                "综合编图 (" +
                    std::to_string(facts.map_documents.size()) + ")",
                std::move(docs)));
        }
        area.children.push_back(group_node(
            "group/results", "成果",
            [] {
                std::vector<ExplorerNode> rows;
                for (const auto& [label, key] :
                     std::vector<std::pair<std::string, std::string>>{
                         {"剖面", "section"},
                         {"平面图", "map"},
                         {"数据导出", "export"},
                     }) {
                    ExplorerNode n;
                    n.key = "result/" + key;
                    n.label = label;
                    n.payload = {{"kind", "result"}, {"result_type", key}};
                    rows.push_back(std::move(n));
                }
                return rows;
            }()));
        if (auto group = user_layer_group()) {
            area.children.push_back(std::move(*group));
        }
        root.children.push_back(std::move(area));

        int seismic = 0;
        for (const auto* r : visible_resources()) {
            if (r->type == "seismic") ++seismic;
        }
        spec.footer = std::to_string(facts.wells.size()) + " 口井 · " +
                      std::to_string(seismic) + " 个地震体 · " +
                      std::to_string(horizon_objects().size()) + " 个层位";
        spec.roots.push_back(std::move(root));
        return spec;
    }

    ExplorerSpec spec_data() const {
        ExplorerSpec spec;
        ExplorerNode root = project_root();
        std::map<std::string, std::vector<const ExplorerResourceFact*>>
            grouped;
        for (const auto* r : visible_resources()) {
            grouped[r->type.empty() ? "unknown" : r->type].push_back(r);
        }
        std::vector<std::string> ordered;
        ordered.reserve(grouped.size());
        for (const auto& [key, _] : grouped) ordered.push_back(key);
        std::sort(ordered.begin(), ordered.end(), [](const auto& a, const auto& b) {
            const std::string la = resource_type_label(a);
            const std::string lb = resource_type_label(b);
            return la != lb ? la < lb : a < b;
        });
        int count = 0;
        for (const auto& key : ordered) {
            const auto& resources = grouped[key];
            std::vector<ExplorerNode> children;
            for (const auto* r : resources) children.push_back(resource_node(*r));
            root.children.push_back(group_node(
                "group/data/" + key,
                resource_type_label(key) + " (" +
                    std::to_string(resources.size()) + ")",
                std::move(children)));
            count += static_cast<int>(resources.size());
        }
        if (auto group = user_layer_group()) {
            count += static_cast<int>(group->children.size());
            root.children.push_back(std::move(*group));
        }
        spec.footer = std::to_string(count) +
                      " 个项目数据对象；存储缓存默认隐藏";
        spec.roots.push_back(std::move(root));
        return spec;
    }

    // ws4 验证：勾选式「项目资源管理器」—— 成果（图件/解释版本）与
    // 参考数据（井/地震/编修图层）全部可勾选，默认勾选；勾选状态经
    // check_toggled 回到验证页（参与对比的对象集）。
    ExplorerSpec spec_review() const {
        ExplorerSpec spec;
        ExplorerNode root = project_root();
        if (!facts.project_open) {
            spec.footer = "未打开工程";
            spec.roots.push_back(std::move(root));
            return spec;
        }
        const auto checkable = [](ExplorerNode& node) {
            node.check_state = 2;  // Qt::Checked
            return node;
        };
        std::vector<ExplorerNode> results;
        for (const auto& doc : facts.map_documents) {
            ExplorerNode node;
            node.key = "review/map/" + doc.id;
            node.label = doc.name.empty() ? "未命名图件" : doc.name;
            node.payload = {{"kind", "map_document"}, {"id", doc.id}};
            node.object = doc.object;
            results.push_back(checkable(node));
        }
        for (const auto& interp : facts.interpretations) {
            ExplorerNode node;
            node.key = "review/interp/" + interp.id;
            node.label = interp.name.empty() ? "解释成果" : interp.name;
            node.payload = {{"kind", "interpretation_result"},
                            {"id", interp.id}};
            node.object = interp.object;
            results.push_back(checkable(node));
        }
        if (results.empty()) {
            ExplorerNode empty;
            empty.key = "review/results-empty";
            empty.label = "暂无成果 — 先在综合编图产出";
            empty.payload = {{"kind", "empty"}};
            results.push_back(std::move(empty));
        }
        const std::string horizon = facts.target_horizon.empty()
                                        ? std::string("当前层位")
                                        : facts.target_horizon;
        root.children.push_back(group_node("group/review-results",
                                           horizon + " 成果",
                                           std::move(results)));

        std::vector<ExplorerNode> refs;
        for (const auto& interp : facts.interpretations) {
            ExplorerNode node;
            node.key = "review/ref-interp/" + interp.id;
            node.label = "井解释 " + (interp.name.empty()
                                          ? std::string("未命名")
                                          : interp.name);
            node.payload = {{"kind", "interpretation_reference"},
                            {"id", interp.id}};
            node.object = interp.object;
            refs.push_back(checkable(node));
        }
        for (const auto& well : facts.wells) {
            ExplorerNode node;
            node.key = "review/well/" + well.id;
            node.label = well.name.empty() ? "未命名井" : well.name;
            node.payload = {{"kind", "well"}, {"well_name", well.name}};
            refs.push_back(checkable(node));
        }
        for (const auto* r : visible_resources()) {
            if (r->type != "seismic") continue;
            ExplorerNode node = resource_node(*r);
            refs.push_back(checkable(node));
        }
        for (const auto& layer : facts.user_layers) {
            ExplorerNode node;
            node.key = "review/uvlayer/" + layer.id;
            node.label = "单因素 " + (layer.name.empty()
                                          ? std::string("编修图层")
                                          : layer.name);
            node.payload = {{"kind", "user_vector_layer"},
                            {"layer_id", layer.id}};
            node.object = layer.object;
            refs.push_back(checkable(node));
        }
        if (refs.empty()) {
            ExplorerNode empty;
            empty.key = "review/refs-empty";
            empty.label = "暂无参考数据";
            empty.payload = {{"kind", "empty"}};
            refs.push_back(std::move(empty));
        }
        root.children.push_back(group_node("group/review-refs", "参考数据",
                                           std::move(refs)));
        spec.footer = "勾选参与验证对比的对象";
        spec.roots.push_back(std::move(root));
        return spec;
    }

    ExplorerSpec spec_layers() const {
        ExplorerSpec spec;
        ExplorerNode root;
        root.key = "layers-root";
        root.label = "解释图层";
        root.payload = {{"kind", "document"}};
        if (facts.user_layers.empty() && facts.map_documents.empty()) {
            ExplorerNode empty;
            empty.key = "layers-empty";
            empty.label = "暂无图层 — 在编图文档中创建";
            empty.payload = {{"kind", "empty"}};
            root.children.push_back(std::move(empty));
            spec.footer = "暂无图层 — 在编图文档中创建";
            spec.roots.push_back(std::move(root));
            return spec;
        }
        for (const auto& layer : facts.user_layers) {
            root.children.push_back(user_layer_node(layer));
        }
        for (const auto& doc : facts.map_documents) {
            ExplorerNode node;
            node.key = "mapdoc/" + doc.id;
            node.label = doc.name.empty() ? "未命名文档" : doc.name;
            node.payload = {{"kind", "layer"},
                            {"layer_type", "map_document"},
                            {"map_document_id", doc.id}};
            node.object = doc.object;
            const int counts[] = {doc.line_features, doc.facies_polygons,
                                  doc.label_features, doc.reference_layers};
            for (std::size_t i = 0; i < map_layer_categories().size(); ++i) {
                if (counts[i] <= 0) continue;
                ExplorerNode cat;
                cat.key = "mapdoc/" + doc.id + "/" +
                          map_layer_categories()[i].first;
                cat.label = map_layer_categories()[i].second + " (" +
                            std::to_string(counts[i]) + ")";
                cat.payload = {{"kind", "layer"},
                               {"layer_type", map_layer_categories()[i].first}};
                cat.object = doc.object;
                node.children.push_back(std::move(cat));
            }
            root.children.push_back(std::move(node));
        }
        spec.footer = std::to_string(facts.user_layers.size()) +
                      " 个编修图层 · " +
                      std::to_string(facts.map_documents.size()) +
                      " 个编图文档；图层仅影响当前文档";
        spec.roots.push_back(std::move(root));
        return spec;
    }

    ExplorerNode process_results_node() const {
        // Process results: workspace memberships grouped by role label,
        // each row carrying role/maturity/pinned-source tooltips.
        ExplorerNode empty;
        empty.key = "group/history-process/empty";
        empty.label = "尚无过程成果";
        empty.payload = {{"kind", "empty"}};
        if (facts.memberships.empty()) {
            return group_node("group/history-process", "过程成果", {empty});
        }
        std::map<std::string, std::vector<ExplorerNode>> grouped;
        std::vector<std::string> order;
        for (const auto& m : facts.memberships) {
            const std::string role_label =
                m.role_label.empty() ? "未分类" : m.role_label;
            const std::string maturity =
                m.maturity.empty() ? "draft" : m.maturity;
            const StateToken token = state_token("maturity", maturity);
            const std::string maturity_text =
                token.glyph + " " + token.label;
            const std::string name =
                m.layer_name.empty() ? m.layer_id : m.layer_name;

            ExplorerNode node;
            node.key = "process/" + m.layer_id;
            node.label = name + " · " + maturity_text;
            node.payload = {{"kind", "layer"}, {"layer_id", m.layer_id}};
            node.tooltip = "角色：" + role_label + "\n成熟度：" +
                           maturity_text +
                           (m.source_version_id.empty()
                                ? ""
                                : "\n钉住来源版本：" +
                                      m.source_version_id);
            node.object = m.object;
            if (grouped.find(role_label) == grouped.end()) {
                order.push_back(role_label);
            }
            grouped[role_label].push_back(std::move(node));
        }
        std::vector<ExplorerNode> children;
        for (const auto& label : order) {
            children.push_back(ExplorerNode{});
            auto& group = children.back();
            group.key = "group/history-process/" + label;
            group.label = label + " (" +
                          std::to_string(grouped[label].size()) + ")";
            group.payload = {{"kind", "group"}};
            group.children = std::move(grouped[label]);
        }
        return group_node("group/history-process",
                          "过程成果 (" +
                              std::to_string(facts.memberships.size()) + ")",
                          std::move(children));
    }

    ExplorerSpec spec_history() const {
        ExplorerSpec spec;
        ExplorerNode root = project_root();
        std::vector<ExplorerNode> version_children;
        for (const auto& ref : facts.interpretations) {
            const std::string version = ref.current_version_id;
            std::string label =
                ref.name.empty() ? "未命名解释" : ref.name;
            if (!version.empty()) label += " · " + version;
            ExplorerNode node;
            node.key = "interp/" + (ref.id.empty() ? label : ref.id);
            node.label = label;
            node.payload = {{"kind", "version"},
                            {"name", version.empty() ? label : version}};
            node.object = ref.object;
            version_children.push_back(std::move(node));
        }
        if (version_children.empty()) {
            ExplorerNode empty;
            empty.key = "group/history-versions/empty";
            empty.label = "尚无解释版本";
            empty.payload = {{"kind", "empty"}};
            version_children.push_back(std::move(empty));
        }
        root.children.push_back(group_node("group/history-versions",
                                           "解释版本",
                                           std::move(version_children)));

        std::vector<ExplorerNode> export_children;
        for (const auto& artifact : facts.export_artifacts) {
            std::string label = artifact.name;
            if (label.empty()) label = file_name_of(artifact.output_path);
            if (label.empty()) label = "导出成果";
            ExplorerNode node;
            node.key = "export/" + artifact.id;
            node.label = label;
            node.payload = {{"kind", "export"}};
            node.tooltip = artifact.output_path;
            node.object = artifact.object;
            export_children.push_back(std::move(node));
        }
        if (export_children.empty()) {
            ExplorerNode empty;
            empty.key = "group/history-exports/empty";
            empty.label = "尚无导出成果";
            empty.payload = {{"kind", "empty"}};
            export_children.push_back(std::move(empty));
        }
        root.children.push_back(group_node("group/history-exports",
                                           "成果输出",
                                           std::move(export_children)));
        root.children.push_back(process_results_node());
        spec.footer = "过程成果、解释、校验与导出历史";
        spec.roots.push_back(std::move(root));
        return spec;
    }

    ExplorerSpec spec_workspaces() const {
        ExplorerSpec spec;
        ExplorerNode joint;
        joint.key = "workspace/joint";
        joint.label = "井震联合解释";
        joint.payload = {{"kind", "workspace"}, {"workspace", "joint"}};
        joint.icon = "visualization.svg";
        spec.roots.push_back(std::move(joint));

        const std::vector<std::tuple<std::string, int, std::string>>
            entries = {
                {"项目概述", 0, "overview"},
                {"数据管理", 0, "management"},
                {"测井预测", 1, "well_log"},
                {"层序格架", 1, "sequence"},
                {"地层对比", 1, "stratigraphy"},
                {"地震预测", 2, "seismic"},
                {"井震联合 3D", 2, "geomodel"},
                {"编图画布", 3, "canvas"},
                {"数据制备", 3, "preparation"},
                {"成图审核", 3, "review"},
            };
        std::vector<ExplorerNode> children;
        for (const auto& [label, hub, key] : entries) {
            ExplorerNode node;
            node.key = "module/" + key;
            node.label = label;
            node.payload = {{"kind", "module"}};
            node.navigation = std::pair{hub, key};
            children.push_back(std::move(node));
        }
        spec.roots.push_back(group_node("group/workspaces-modules",
                                        "兼容工作流", std::move(children)));
        spec.footer = "工作区保存文档、分屏、面板与联动状态";
        return spec;
    }
};

}  // namespace

const std::map<std::string, std::string>& explorer_mode_titles() {
    static const std::map<std::string, std::string> titles = {
        {"project", "资源管理器"}, {"data", "数据目录"},
        {"layers", "图层管理器"},  {"search", "全局搜索"},
        {"history", "历史与成果"}, {"workspaces", "工作区"},
        {"review", "项目资源管理器"},
    };
    return titles;
}

std::string normalize_explorer_mode(const std::string& mode) {
    return explorer_mode_titles().count(mode) ? mode : "project";
}

ExplorerSpec build_explorer_spec(const std::string& mode,
                                 const ExplorerFacts& facts) {
    const Builder builder{facts};
    const std::string normalized = normalize_explorer_mode(mode);
    if (normalized == "data" || normalized == "search") {
        return builder.spec_data();
    }
    if (normalized == "layers") return builder.spec_layers();
    if (normalized == "review") return builder.spec_review();
    if (normalized == "history") return builder.spec_history();
    if (normalized == "workspaces") return builder.spec_workspaces();
    return builder.spec_project();
}

}  // namespace pwb::ui_workstation
