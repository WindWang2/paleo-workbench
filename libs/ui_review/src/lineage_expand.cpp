#include "pwb/ui_review/lineage_expand.hpp"

#include "pwb/ui_data_core/asset_view.hpp"
#include "pwb/ui_review/tokens.hpp"

#include <algorithm>
#include <set>

namespace pwb::ui_review {

namespace {

bool on_path(const std::vector<std::string>& ancestors,
             const std::string& id) {
    return std::find(ancestors.begin(), ancestors.end(), id) !=
           ancestors.end();
}

std::vector<std::string> push_path(std::vector<std::string> ancestors,
                                   std::string id) {
    ancestors.push_back(std::move(id));
    return ancestors;
}

LineageNodeSpec note(std::string text) {
    LineageNodeSpec spec;
    spec.kind = LineageNodeSpec::Kind::Note;
    spec.label = std::move(text);
    spec.selectable = false;
    spec.show_indicator = false;
    return spec;
}

LineageNodeSpec overflow_note(int remaining) {
    auto spec = note("…还有 " + std::to_string(remaining) + " 个（未展开）");
    spec.kind = LineageNodeSpec::Kind::Overflow;
    spec.disabled = true;
    return spec;
}

LineageNodeSpec version_spec(const catalog::DataVersion& version,
                             const std::string& direction,
                             std::vector<std::string> ancestors,
                             const AssetNameFn& asset_name) {
    LineageNodeSpec spec;
    spec.kind = LineageNodeSpec::Kind::Version;
    spec.label = version_item_label(version, asset_name(version.asset_id.str()));
    spec.version_id = version.id.str();
    spec.asset_id = version.asset_id.str();
    spec.stage = std::string(domain::to_string(version.stage));
    spec.direction = direction;
    spec.ancestors = push_path(std::move(ancestors), version.id.str());
    spec.lazy = true;
    spec.show_indicator = true;
    return spec;
}

}  // namespace

std::vector<LineageNodeSpec>
expand_inputs(const LineageHop* hop,
              const std::vector<std::string>& ancestors,
              const AssetNameFn& asset_name) {
    if (hop == nullptr) {
        return {note("（无法读取血缘）")};
    }
    std::vector<LineageNodeSpec> out;
    if (hop->run.has_value()) {
        LineageNodeSpec run_spec;
        run_spec.kind = LineageNodeSpec::Kind::Run;
        run_spec.label = "⚙ " + hop->run->operation + " · " +
                         (hop->run->status.empty() ? "—" : hop->run->status);
        run_spec.run_id = hop->run->id.str();
        run_spec.output_version_id = hop->version.id.str();
        run_spec.show_indicator = false;
        out.push_back(std::move(run_spec));
    }
    std::set<std::string> resolved;
    for (const auto& p : hop->parents) {
        resolved.insert(p.id.str());
    }
    const auto& parent_ids = hop->version.parent_version_ids;
    int shown = 0;
    for (const auto& pid : parent_ids) {
        if (shown >= kMaxChildrenPerNode) {
            out.push_back(
                overflow_note(int(parent_ids.size()) - shown));
            break;
        }
        const std::string pid_str = pid.str();
        if (on_path(ancestors, pid_str)) {
            // Cycle check FIRST — a resolvable parent already on the
            // path must never become a re-expandable node.
            out.push_back(note("↺ 循环引用: " + pid_str));
            ++shown;
            continue;
        }
        if (resolved.count(pid_str)) {
            const catalog::DataVersion* parent = nullptr;
            for (const auto& p : hop->parents) {
                if (p.id == pid) {
                    parent = &p;
                    break;
                }
            }
            out.push_back(version_spec(*parent, "up",
                                       push_path(ancestors, pid_str),
                                       asset_name));
        } else {
            LineageNodeSpec broken;
            broken.kind = LineageNodeSpec::Kind::Broken;
            broken.label = "⚠ 断链: " + pid_str;
            broken.version_id = pid_str;
            broken.red = true;
            broken.selectable = false;
            broken.show_indicator = false;
            out.push_back(std::move(broken));
        }
        ++shown;
    }
    if (parent_ids.empty()) {
        out.push_back(note("（无上游 — RAW 根）"));
    }
    return out;
}

std::vector<LineageNodeSpec>
expand_outputs(const LineageHop* hop,
               const std::vector<std::string>& ancestors,
               const AssetNameFn& asset_name) {
    if (hop == nullptr) {
        return {note("（无法读取血缘）")};
    }
    std::vector<LineageNodeSpec> out;
    const auto& children = hop->children;
    for (std::size_t i = 0;
         i < children.size() && i < std::size_t(kMaxChildrenPerNode); ++i) {
        const auto& child = children[i];
        if (on_path(ancestors, child.id.str())) {
            out.push_back(note("↺ 循环引用: " + child.id.str()));
            continue;
        }
        out.push_back(version_spec(child, "down",
                                   push_path(ancestors, child.id.str()),
                                   asset_name));
    }
    if (children.size() > std::size_t(kMaxChildrenPerNode)) {
        out.push_back(overflow_note(int(children.size()) -
                                    kMaxChildrenPerNode));
    }
    if (children.empty()) {
        out.push_back(note("（无下游衍生）"));
    }
    return out;
}

std::string version_item_label(const catalog::DataVersion& version,
                               const std::string& asset_name) {
    std::string label =
        ui_data_core::stage_icon(version.stage) + " " + asset_name +
        " · v" + std::to_string(version.version_number) + " · " +
        ui_data_core::stage_label(version.stage) + " · " +
        version.id.str().substr(0, kShortIdLen);
    if (version.trashed) {
        label += " ✕回收站";
    }
    return label;
}

LineageNodeSpec current_item_spec(const catalog::DataVersion& version,
                                  const std::string& asset_name) {
    LineageNodeSpec spec;
    // Python payload kind is "version" for the centered node too —
    // callers treat Version/Current identically; Version is canonical.
    spec.kind = LineageNodeSpec::Kind::Version;
    spec.label = "■ 当前: " + version_item_label(version, asset_name);
    spec.version_id = version.id.str();
    spec.asset_id = version.asset_id.str();
    spec.stage = std::string(domain::to_string(version.stage));
    spec.direction = "";
    spec.ancestors = {version.id.str()};
    spec.lazy = false;
    spec.show_indicator = false;  // DontShowIndicator
    return spec;
}

LineageNodeSpec branch_spec(const std::string& direction,
                            const std::string& version_id) {
    LineageNodeSpec spec;
    spec.kind = LineageNodeSpec::Kind::Branch;
    spec.label = direction == "up" ? "⬆ 上游 (← RAW)" : "⬇ 下游 (→ 产物)";
    spec.direction = direction;
    spec.version_id = version_id;
    spec.ancestors = {version_id};
    spec.lazy = true;
    spec.selectable = false;
    spec.show_indicator = true;
    return spec;
}

SummaryCardText summary_card_text(const catalog::DataVersion& version,
                                  const std::string& asset_name,
                                  bool payload_exists) {
    SummaryCardText out;
    out.title = ui_data_core::stage_icon(version.stage) + " " + asset_name +
                " · v" + std::to_string(version.version_number) + " · " +
                ui_data_core::stage_label(version.stage);
    std::string checksum = version.sha256.value_or("无");
    if (checksum.size() > 16) {
        checksum = checksum.substr(0, 12) + "…";
    }
    out.meta = "ID: " + version.id.str() + " · 校验和: " + checksum +
               " · 创建于: " +
               (version.created_at.empty() ? "—" : version.created_at) +
               " · " + (version.managed ? "受管 (Managed)" : "外部 (External)");
    out.path =
        "路径: " + (version.path.empty() ? "—" : version.path);
    if (!payload_exists) {
        out.path += "　⚠ 源文件缺失";
    }
    return out;
}

RunCardText run_card_text(const catalog::DataRun* run) {
    RunCardText out;
    if (run == nullptr) {
        out.title = "无生成运行";
        out.has_run = false;
        return out;
    }
    out.has_run = true;
    out.title = "⚙ 生成运行 · " + run->operation;
    out.meta = "状态: " + (run->status.empty() ? "—" : run->status) +
               " · 生成器: " +
               (run->generator.empty() ? "—" : run->generator) + " · " +
               (run->created_at.empty() ? "—" : run->created_at);
    // json.dumps(run.parameters or {}, ensure_ascii=False, indent=2) —
    // indent 2, no ascii escape, no trailing newline.
    out.params =
        domain::dump_json_compact_header(run->parameters.is_null()
                                             ? domain::Json::object()
                                             : run->parameters);
    return out;
}

std::string expand_raw_capped_status() {
    return "⚠ 展开至 RAW 已停止：达到保护上限（深度 ≤ " +
           std::to_string(kMaxExpandDepth) + "，节点 ≤ " +
           std::to_string(kMaxExpandNodes) + "）";
}

std::string expand_raw_done_status(int roots, int upstream_versions) {
    return "已展开上游至 " + std::to_string(roots) + " 个 RAW 根（共 " +
           std::to_string(std::max(upstream_versions, 0)) +
           " 个上游版本）";
}

}  // namespace pwb::ui_review
