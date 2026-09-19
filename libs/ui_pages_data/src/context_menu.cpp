// UI-06 — asset_context_menu.build menu model.
#include <pwb/ui_pages_data/context_menu.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data {
namespace {

MenuEntry action(std::string object_name, std::string label,
                 std::string tooltip = "", bool enabled = true) {
    MenuEntry entry;
    entry.kind = MenuEntry::Kind::Action;
    entry.object_name = std::move(object_name);
    entry.label = std::move(label);
    entry.tooltip = std::move(tooltip);
    entry.enabled = enabled;
    return entry;
}

MenuEntry separator() {
    MenuEntry entry;
    entry.kind = MenuEntry::Kind::Separator;
    return entry;
}

// str.strip() — ASCII whitespace (paths don't carry CJK space).
std::string strip(const std::string& s) {
    std::size_t lo = 0, hi = s.size();
    auto is_space = [](char c) {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' ||
               c == '\f';
    };
    while (lo < hi && is_space(s[lo])) ++lo;
    while (hi > lo && is_space(s[hi - 1])) --hi;
    return s.substr(lo, hi - lo);
}

bool starts_with(const std::string& s, const char* prefix) {
    return s.rfind(prefix, 0) == 0;
}

}  // namespace

std::pair<bool, std::string> open_system_target(const std::string& path) {
    const std::string stripped = strip(path);
    const bool remote = starts_with(stripped, "http://") ||
                        starts_with(stripped, "https://") ||
                        starts_with(stripped, "ftp://");
    const bool local = !stripped.empty() && !remote;
    return {local, local ? stripped : std::string()};
}

std::vector<MenuEntry>
build_asset_menu_model(const AssetView& view, AssetKind kind,
                       const MenuCapabilities& caps) {
    std::vector<MenuEntry> menu;

    // 0. Trashed assets: restore path, early return.
    if (view.is_trashed) {
        menu.push_back(action("ctx_restore", "还原 (Restore)",
                              "从回收站恢复该数据资产及其版本"));
        menu.push_back(separator());
        menu.push_back(action("ctx_open_folder", "打开目录"));
        const auto [enabled, captured] = open_system_target(view.path);
        auto sys = action("ctx_open_system", "用系统应用打开",
                          enabled ? "" : "无本地文件路径", enabled);
        sys.open_local_path = captured;
        menu.push_back(std::move(sys));
        return menu;
    }

    // 1. Preview.
    menu.push_back(action("ctx_preview", "预览"));

    // 2. Stage-specific actions.
    if (view.stage == stage::kRaw) {
        menu.push_back(action(
            "ctx_create_derived", "创建派生副本 (Create Derived Copy)",
            "从锁定原始输入创建可编辑派生数据"));
        if (view.type == "well_log" || view.type == "las") {
            menu.push_back(action(
                "ctx_curve_interpretation", "曲线解释操作…",
                "深度平移 / 去尖峰 / 基线校正 → 派生曲线版本（原始数据保持不可变）"));
        }
        auto edit = action("ctx_edit_original", "编辑原始数据 (已锁定 ⊘)",
                           "不可用：" + caps.raw_gate_reason, false);
        menu.push_back(std::move(edit));
    } else if (view.stage == stage::kDerived ||
               view.stage == stage::kIntermediate) {
        menu.push_back(action("ctx_new_version",
                              "新建版本 / 工作副本 (New Version)",
                              "创建工作副本并提交为新版本 (需数据目录)"));
        menu.push_back(action("ctx_promote", "提升为正式数据 (Promote)",
                              "将当前版本复制为新的不可变 OUTPUT 版本"));
    } else if (view.stage == stage::kOutput) {
        menu.push_back(action("ctx_export_open", "导出 / 交付",
                              "导出 / 交付成果文件并记录交付元数据"));
    }

    // External items.
    if (!view.managed) {
        menu.push_back(action("ctx_materialize",
                              "纳管至项目 (Import into Project)",
                              "需连接数据目录后端以纳管外部数据", false));
        menu.push_back(action("ctx_relink", "重新链接源… (Relink Source)",
                              "源文件移动后重新指向新位置（需通过身份校验）",
                              false));
    }

    // 3. Verify + catalog-bridged browsers.
    menu.push_back(action("ctx_verify", "校验完整性 (Verify Integrity)"));
    menu.push_back(action("ctx_version_workbench", "版本工作台… (Versions)",
                          "需要数据目录桥接的资产", false));
    menu.push_back(action("ctx_lineage_explorer",
                          "血缘/溯源浏览器… (Lineage)",
                          "需要数据目录桥接的资产", false));

    // 4. Tags.
    menu.push_back(action("ctx_add_tag", "添加标签..."));

    // 5. Rescan + classify (ResourceItem only).
    if (kind == AssetKind::Resource) {
        menu.push_back(action("ctx_rescan", "重新扫描"));
        MenuEntry classify;
        classify.kind = MenuEntry::Kind::Submenu;
        classify.label = "归类为";
        for (const auto& [label, rtype] : categories()) {
            if (!rtype || *rtype == view.type) continue;
            classify.children.push_back(
                action("ctx_classify_" + *rtype, label));
        }
        menu.push_back(std::move(classify));
    }

    // 6. Export submenu.
    if (!caps.export_formats.empty()) {
        MenuEntry export_menu;
        export_menu.kind = MenuEntry::Kind::Submenu;
        export_menu.label = "导出";
        for (const auto& label : caps.export_formats) {
            export_menu.children.push_back(
                action("ctx_export_" + label, label));
        }
        if (kind == AssetKind::Resource) {
            export_menu.children.push_back(
                action("ctx_export_INVENTORY", "工程清单 (JSON)"));
        }
        menu.push_back(std::move(export_menu));
    }

    // 7. Open folder / system app.
    menu.push_back(action("ctx_open_folder", "打开目录"));
    {
        const auto [enabled, captured] = open_system_target(view.path);
        auto sys = action("ctx_open_system", "用系统应用打开",
                          enabled ? "" : "无本地文件路径", enabled);
        sys.open_local_path = captured;
        menu.push_back(std::move(sys));
    }

    // 8. Visualization / prediction entries.
    if (caps.viz_supported)
        menu.push_back(action("ctx_visualize", "在可视化页面打开"));
    if (caps.well_prediction_supported)
        menu.push_back(action("ctx_well_prediction", "在测井预测中打开"));
    if (caps.seismic_prediction_supported)
        menu.push_back(
            action("ctx_seismic_prediction", "在地震预测中打开"));

    menu.push_back(separator());
    auto remove = action("ctx_remove", "移出项目");
    remove.destructive = true;
    menu.push_back(std::move(remove));
    return menu;
}

std::vector<MenuEntry> build_multi_menu_model(int count) {
    const std::string n = std::to_string(count);
    std::vector<MenuEntry> menu;
    auto header = action("", "已选择 " + n + " 项数据资产", "", false);
    menu.push_back(std::move(header));
    menu.push_back(separator());
    menu.push_back(
        action("ctx_bulk_add_tag", "批量添加标签 (" + n + " 项)..."));
    menu.push_back(
        action("ctx_bulk_remove_tag", "批量移除标签 (" + n + " 项)..."));
    menu.push_back(
        action("ctx_bulk_verify", "批量校验完整性 (" + n + " 项)"));
    menu.push_back(separator());
    auto remove = action("ctx_bulk_remove", "批量移出项目 (" + n + " 项)");
    remove.destructive = true;
    menu.push_back(std::move(remove));
    return menu;
}

}  // namespace pwb::ui_pages_data
