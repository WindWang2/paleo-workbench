// ws0 数据治理闭环 — ribbon 命令回调体（全壳装配专用：依赖
// AppShell/AppContext/closure_preview 刷新注册表）。见 data_governance_install.hpp。
#include "data_governance_install.hpp"

#include "app_context.hpp"
#include "app_shell.hpp"
#include "closure_preview_install.hpp"
#include "data_governance_dialogs.hpp"
#include "data_lineage_panel.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/data/governance.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>

#include <QListWidget>
#include <QPointer>
#include <QTabWidget>

#include <functional>
#include <optional>

namespace pwb::app::data_governance {

namespace gov = pwb::data::governance;

// ---- ribbon 命令回调体 ------------------------------------------------------

namespace {

// (store, bus, refresh) 三件套：ribbon Ctx 的公共分解。store 为空 →
// 返回 false（命令 applicability 已挡，这里是防御）。
struct CommandHost {
    std::shared_ptr<pwb::application::PwbDataStore> store;
    QPointer<pwb::ui_pages_data::qt::AssetSelectionBus> bus;
    std::function<void()> refresh;
};

CommandHost command_host(AppContext* context, AppShell* shell) {
    CommandHost host;
    host.store = context != nullptr ? context->projectStore() : nullptr;
    if (shell != nullptr && shell->data_workspace() != nullptr) {
        host.bus = shell->data_workspace()->selection_bus();
    }
    host.refresh = [context, bus = host.bus]() {
        // 治理写用的是短命 session/深核打开——常驻 store 的磁盘基线
        //（disk_sha256_/CAS）在写后会拒绝它自己的下一次 save。写成功后
        // 原位重开 store（失败保留旧 store，诚实降级），再走全局刷新。
        if (context != nullptr) {
            if (auto stale = context->projectStore()) {
                const auto path = stale->project_file();
                if (auto fresh =
                        pwb::application::PwbDataStore::open(path, nullptr)) {
                    context->setProjectStore(fresh);
                }
            }
        }
        closure_preview::notify_project_store_changed();
        if (bus != nullptr) bus->republish_current();
    };
    return host;
}

std::optional<pwb::ui_pages_data::AssetRow> current_row(
    const CommandHost& host) {
    if (host.bus == nullptr || !host.bus->current_asset().has_value()) {
        return std::nullopt;
    }
    return *host.bus->current_asset();
}

}  // namespace

void open_link_well_dialog(AppContext* context, AppShell* shell,
                           QWidget* window) {
    const auto host = command_host(context, shell);
    if (host.store == nullptr) return;
    const auto asset = current_row(host);
    if (!asset.has_value()) return;
    auto* dialog = new LinkWellDialog(host.store->project_file(),
                                      asset->view.id, asset->view.name,
                                      host.refresh, window);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    if (shell != nullptr) {
        QObject::connect(dialog, &LinkWellDialog::status_message, dialog,
                         [shell](const QString& text) {
                             emit shell->status_message(text);
                         });
    }
    dialog->show();
}

void open_set_role_dialog(AppContext* context, AppShell* shell,
                          QWidget* window) {
    const auto host = command_host(context, shell);
    if (host.store == nullptr) return;
    const auto asset = current_row(host);
    if (!asset.has_value()) return;
    if (gov::links_for_asset(host.store->project_file(), asset->view.id)
            .empty()) {
        if (shell != nullptr) {
            emit shell->status_message(
                QStringLiteral("该资产尚无实体关联——请先用「关联到井」"
                               "建立链接，再设置角色。"));
        }
        return;
    }
    auto* dialog = new SetRoleDialog(host.store->project_file(),
                                     asset->view.id, asset->view.name,
                                     host.refresh, window);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    if (shell != nullptr) {
        QObject::connect(dialog, &SetRoleDialog::status_message, dialog,
                         [shell](const QString& text) {
                             emit shell->status_message(text);
                         });
    }
    dialog->show();
}

void open_tags_dialog(AppContext* context, AppShell* shell, QWidget* window) {
    const auto host = command_host(context, shell);
    if (host.store == nullptr) return;
    const auto asset = current_row(host);
    if (!asset.has_value()) return;
    auto* dialog = new TagsDialog(host.store->project_file(),
                                  {asset->view.id}, {asset->view.name},
                                  host.refresh, window);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    if (shell != nullptr) {
        QObject::connect(dialog, &TagsDialog::status_message, dialog,
                         [shell](const QString& text) {
                             emit shell->status_message(text);
                         });
    }
    dialog->show();
}

void open_trash_dialog(AppContext* context, AppShell* shell, QWidget* window) {
    const auto host = command_host(context, shell);
    if (host.store == nullptr) return;
    auto* dialog =
        new TrashDialog(host.store->project_file(), host.refresh, window);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    if (shell != nullptr) {
        QObject::connect(dialog, &TrashDialog::status_message, dialog,
                         [shell](const QString& text) {
                             emit shell->status_message(text);
                         });
    }
    dialog->show();
}

void focus_impact_tab(AppShell* shell) {
    if (shell == nullptr) return;
    shell->navigate_workspace(0);
    if (auto* panel = shell->findChild<pwb::app::DataLineagePanel*>(
            QStringLiteral("DataLineagePanel"));
        panel != nullptr) {
        panel->tabs()->setCurrentIndex(2);
    }
    // m5 装配把第二实例的三页 reparent 进页内底签——底签也要切过去，
    // 否则命令在底签可见的布局里是空操作。按 objectName 找影响页的
    // 宿主 tab（不猜层级）。
    if (auto* impact = shell->findChild<QListWidget*>(
            QStringLiteral("DataLineageImpact"));
        impact != nullptr) {
        for (auto* tabs : shell->findChildren<QTabWidget*>()) {
            for (int i = 0; i < tabs->count(); ++i) {
                if (tabs->widget(i) == impact) {
                    tabs->setCurrentIndex(i);
                    break;
                }
            }
        }
    }
}

}  // namespace pwb::app::data_governance
