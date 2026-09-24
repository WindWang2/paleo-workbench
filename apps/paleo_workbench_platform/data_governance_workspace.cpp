// ws0 数据治理闭环 — workspace 接线实现。见 data_governance_workspace.hpp。
#include "data_governance_workspace.hpp"

#include "data_governance_dialogs.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/data/governance.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_asset_table.hpp>
#include <pwb/ui_pages_data/qt/data_toolbar.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>

#include <QMessageBox>
#include <QPointer>

#include <algorithm>
#include <set>

namespace pwb::app::data_governance {

namespace gov = pwb::data::governance;

namespace {

QString zh(const std::string& text) { return QString::fromUtf8(text.c_str()); }

bool default_confirm(QWidget* parent, const QString& impact_text) {
    return QMessageBox::question(
               parent, QStringLiteral("移入回收站"),
               QStringLiteral("所选资产存在下游依赖：\n\n%1\n\n"
                              "软删除不会物理清除原始数据（保留在工程 "
                              "artifacts/trash/，可恢复），但下游成果会"
                              "标记为来源失效。确定继续？")
                   .arg(impact_text),
               QMessageBox::Yes | QMessageBox::No,
               QMessageBox::No) == QMessageBox::Yes;
}

}  // namespace

bool run_trash_flow(const Install& install,
                    const std::vector<pwb::ui_pages_data::AssetRow>& rows,
                    const std::string& reason) {
    if (rows.empty() || install.store == nullptr) return false;
    auto opened = install.store();
    if (opened == nullptr) return false;
    const auto project_file = opened->project_file();

    std::vector<std::string> asset_ids;
    std::vector<std::string> names;
    for (const auto& row : rows) {
        asset_ids.push_back(row.view.id);
        names.push_back(row.view.name.empty() ? row.view.id : row.view.name);
    }

    // Impact preflight（每资产真实查询；聚合后一次决策）。
    int total_descendants = 0;
    int total_entities = 0;
    QStringList impact_lines;
    for (std::size_t i = 0; i < asset_ids.size(); ++i) {
        const auto facts =
            gov::delete_impact_facts(project_file, std::nullopt, asset_ids[i]);
        if (!facts.ok) continue;  // 单资产查询失败不阻塞——trash 自身会校验
        total_descendants += facts.live_descendants;
        total_entities += facts.linked_entities;
        if (facts.live_descendants > 0 || facts.linked_entities > 0) {
            impact_lines << QStringLiteral("· %1：存活下游 %2，关联实体 %3")
                                .arg(zh(names[i]))
                                .arg(facts.live_descendants)
                                .arg(facts.linked_entities);
        }
    }
    if (total_descendants > 0 || total_entities > 0) {
        const bool proceed =
            install.confirm_destructive
                ? install.confirm_destructive(impact_lines.join("\n"))
                : default_confirm(install.dialog_parent,
                                  impact_lines.join("\n"));
        if (!proceed) {
            if (install.status) {
                install.status(QStringLiteral("已取消移出（影响预览未确认）"));
            }
            return false;
        }
    }

    const auto outcome = gov::trash_assets(project_file, asset_ids, reason);
    // 刷新总是执行：部分成功（ok=true 且 error 非空）也要让已落库的
    // 移除反映到 UI；失败路径刷新是无害的空转。
    if (install.refresh_notify) install.refresh_notify();
    if (install.status) {
        // 部分成功时摘要与失败原因合并展示——不吞失败。
        install.status(zh(outcome.error.empty()
                              ? outcome.summary
                              : outcome.summary + "；" + outcome.error));
    }
    return outcome.ok;
}

void install_data_governance(const Install& install) {
    auto* workspace = install.workspace;
    auto* bus = install.bus;
    if (workspace == nullptr || bus == nullptr) return;
    auto* toolbar =
        workspace->findChild<pwb::ui_pages_data::qt::DataToolbar*>();
    const auto status = [&install](const QString& text) {
        if (install.status) install.status(text);
    };

    // ---- 多选跟踪（标签批量 / 批量移除的操作面）--------------------------
    auto selection = std::make_shared<std::vector<pwb::ui_pages_data::AssetRow>>();
    if (auto* table = workspace->asset_table()) {
        QObject::connect(
            table,
            &pwb::ui_pages_data::qt::DataAssetTable::selected_assets_changed,
            table, [selection](const std::vector<pwb::ui_pages_data::AssetRow>&
                                   assets) { *selection = assets; });
    }

    // ---- 行集刷新 → 工具条标签候选（distinct，词序稳定）------------------
    if (toolbar != nullptr) {
        QObject::connect(
            bus, &pwb::ui_pages_data::qt::AssetSelectionBus::assets_changed,
            toolbar,
            [toolbar](const std::vector<pwb::ui_pages_data::AssetRow>& rows,
                      const QString&) {
                std::vector<std::string> tags;
                std::set<std::string> seen;
                for (const auto& row : rows) {
                    for (const auto& tag : row.view.tags) {
                        if (seen.insert(tag).second) tags.push_back(tag);
                    }
                }
                toolbar->set_tag_candidates(tags);
            });
    }

    // ---- 标签过滤（and/or）→ FilterQuery --------------------------------
    if (toolbar != nullptr && workspace->asset_table() != nullptr) {
        auto* table = workspace->asset_table();
        QObject::connect(
            toolbar, &pwb::ui_pages_data::qt::DataToolbar::tag_filter_changed,
            table, [table](const QStringList& tags, const QString& op) {
                pwb::ui_pages_data::FilterQuery query = table->filter_query();
                std::vector<std::string> values;
                values.reserve(tags.size());
                for (const QString& tag : tags) {
                    values.push_back(tag.toStdString());
                }
                query.tags = std::move(values);
                query.tag_operator =
                    op == QStringLiteral("or") ? "or" : "and";
                table->set_filter_query(query);
            });
    }

    // ---- 标签管理入口：多选优先，回退当前选中 ---------------------------
    if (toolbar != nullptr) {
        QObject::connect(
            toolbar,
            &pwb::ui_pages_data::qt::DataToolbar::tag_manager_requested,
            toolbar, [install, selection, toolbar]() {
                std::vector<pwb::ui_pages_data::AssetRow> rows = *selection;
                if (rows.empty() && install.bus != nullptr &&
                    install.bus->current_asset().has_value()) {
                    rows.push_back(*install.bus->current_asset());
                }
                if (rows.empty()) {
                    QMessageBox::information(
                        toolbar, QStringLiteral("标签管理"),
                        QStringLiteral("请先在资产表中选择至少一项资产。"));
                    return;
                }
                std::vector<std::string> ids;
                std::vector<std::string> names;
                for (const auto& row : rows) {
                    ids.push_back(row.view.id);
                    names.push_back(row.view.name);
                }
                auto opened = install.store ? install.store() : nullptr;
                if (opened == nullptr) {
                    QMessageBox::warning(
                        toolbar, QStringLiteral("标签管理"),
                        QStringLiteral("尚未打开工程，无法管理标签。"));
                    return;
                }
                auto* dialog = new TagsDialog(opened->project_file(), ids,
                                              names, install.refresh_notify,
                                              toolbar);
                dialog->setAttribute(Qt::WA_DeleteOnClose);
                QObject::connect(dialog, &TagsDialog::applied, dialog,
                                 [bus_guard = QPointer(install.bus)]() {
                                     if (bus_guard != nullptr) {
                                         bus_guard->republish_current();
                                     }
                                 });
                dialog->show();
            });
    }

    // ---- 移出项目（工具条 remove_requested）→ 软删除流 ------------------
    if (toolbar != nullptr) {
        QObject::connect(
            toolbar, &pwb::ui_pages_data::qt::DataToolbar::remove_requested,
            toolbar, [install, selection]() {
                std::vector<pwb::ui_pages_data::AssetRow> rows = *selection;
                if (rows.empty() && install.bus != nullptr &&
                    install.bus->current_asset().has_value()) {
                    rows.push_back(*install.bus->current_asset());
                }
                if (rows.empty()) {
                    QMessageBox::information(
                        install.dialog_parent, QStringLiteral("移入回收站"),
                        QStringLiteral("请先在资产表中选择要移出的资产。"));
                    return;
                }
                run_trash_flow(install, rows, "移出项目（数据管理）");
            });
    }
}

}  // namespace pwb::app::data_governance
