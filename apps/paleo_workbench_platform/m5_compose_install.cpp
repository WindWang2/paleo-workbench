#include "m5_compose_install.hpp"

#if defined(PWB_WITH_CLOSURE_MAPPING)

#include <functional>
#include <utility>

#include <QAction>
#include <QPushButton>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "closure_mapping_document.hpp"
#include "closure_mapping_install.hpp"
// AUTOMOC scans includes textually (no #if evaluation) — macro-indirect
// include keeps the Q_OBJECT moc out of builds where this TU is empty.
#define PWB_M5_LAYOUT_PANEL_HPP "layout_compose_panel.hpp"
#include PWB_M5_LAYOUT_PANEL_HPP
#include "main_window.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_data_qt/map_edit_items.hpp>
#include <pwb/ui_map/map_chrome_panel.hpp>
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_ribbon/ribbon_spec.hpp>
#include <pwb/ui_shell/command_registry.hpp>

namespace pwb::app::m5_compose {

namespace {

using pwb::domain::Json;
using pwb::ui_ribbon::CommandKind;
using pwb::ui_ribbon::RibbonCommand;
using pwb::ui_ribbon::RibbonGroup;

// The 约束线 context group (R:33): appears on ws2 AND ws3 when a line
// feature is selected in the edit scene. Commands are the M4-registered
// ids — binding/evaluator/overflow ride the same paths.
RibbonGroup constraint_group_spec() {
    RibbonGroup group;
    group.id = "ctx_constraint";
    group.label = "约束线编辑";
    group.commands = {
        RibbonCommand{"factor.edit_sourcing", "编辑物源线", "rb-fence.svg",
                      CommandKind::Secondary, false},
        RibbonCommand{"factor.edit_trend", "展布线", "rb-analysis.svg",
                      CommandKind::Secondary, false},
        RibbonCommand{"factor.snap", "捕捉", "map/snapping.svg",
                      CommandKind::Toggle, false},
    };
    return group;
}

RibbonGroup annotation_group_spec() {
    RibbonGroup group;
    group.id = "ctx_annotation";
    group.label = "标注";
    group.commands = {
        RibbonCommand{"map.annotate", "标注", "menu-new.svg",
                      CommandKind::Secondary, false},
        RibbonCommand{"map.legend", "图例", "rb-colorbar.svg",
                      CommandKind::Secondary, false},
    };
    return group;
}

QString selected_kind(ui_pages_mapedit::MapEditScene* scene,
                      const QStringList& ids) {
    for (const QString& id : ids) {
        if (auto* item = scene->item_by_id(id.toStdString());
            item != nullptr) {
            const Json record = item->to_record();
            const auto it = record.find("kind");
            if (it != record.end() && it->is_string()) {
                return QString::fromStdString(it->get<std::string>());
            }
        }
    }
    return QString();
}

}  // namespace

void install(const Install& install) {
    auto* window = dynamic_cast<MainWindow*>(install.window);
    auto* shell = install.shell;
    if (window == nullptr || shell == nullptr ||
        shell->validation_page() == nullptr) {
        return;
    }
    auto* bank = closure_mapping::document_bank(window);
    if (bank == nullptr) return;

    // ---- 版式轻量面板 (ws3 底部栈第 2 页) --------------------------------
    auto* panel = new LayoutComposePanel(shell);
    panel->set_chrome_reader([bank]() -> Json {
        auto* doc = bank->active_document();
        if (doc == nullptr) return Json::object();
        const auto it = doc->find("map_chrome");
        return it != doc->end() && it->is_object() ? *it : Json::object();
    });
    panel->set_chrome_writer([bank, shell](const Json& payload) {
        auto* doc = bank->active_document();
        if (doc == nullptr) {
            emit shell->status_message(
                QStringLiteral("版式整饰：无活动编图文档"));
            return;
        }
        // 单一状态：写回文档 map_chrome 并通知 bank —— workflow 的
        // document_saved 推送让 MapChromePanel 同步镜像（F:69）。
        (*doc)["map_chrome"] = payload;
        emit bank->document_saved(
            QString::fromStdString(bank->active_id()));
        emit shell->status_message(QStringLiteral("图件整饰已更新"));
    });
    panel->set_export_action(window->governedAction(QStringLiteral("map_export")));
    QObject::connect(panel, &LayoutComposePanel::status_message, shell,
                     &AppShell::status_message);
    shell->set_stage3_compose(panel);
    QObject::connect(bank, &closure_mapping::MapDocumentBank::active_changed,
                     panel, [panel] { panel->refresh_chrome(); });

    // ---- 图件整饰 panel (ws3 右栏「图件整饰」tab) ------------------------
    // 与 LayoutComposePanel 同一 map_chrome 文档节、同一写回路径（F:69
    // 单一权威）：读 active_document 快照，写 doc["map_chrome"] 后广播
    // document_saved 让另一面板同步镜像。
    if (auto* decor = qobject_cast<pwb::ui_map::MapChromePanel*>(
            shell->map_decor_panel())) {
        const auto sync_decor = [bank, decor] {
            if (auto* doc = bank->active_document(); doc != nullptr) {
                decor->update_state(*doc);
            }
        };
        QObject::connect(bank,
                         &closure_mapping::MapDocumentBank::active_changed,
                         decor, [sync_decor](const QString&) {
                             sync_decor();
                         });
        QObject::connect(bank,
                         &closure_mapping::MapDocumentBank::document_saved,
                         decor, [sync_decor](const QString&) {
                             sync_decor();
                         });
        QObject::connect(decor, &pwb::ui_map::MapChromePanel::chrome_changed,
                         shell, [bank, shell](const Json& payload) {
                             auto* doc = bank->active_document();
                             if (doc == nullptr) {
                                 emit shell->status_message(QStringLiteral(
                                     "图件整饰：无活动编图文档"));
                                 return;
                             }
                             (*doc)["map_chrome"] = payload;
                             emit bank->document_saved(
                                 QString::fromStdString(bank->active_id()));
                         });
        // 保存/送交验证按钮 = 既有 ribbon 命令同一回调（无第二实现）。
        auto& registry = pwb::ui_shell::command_registry();
        const auto bind = [&registry](QPushButton* button,
                                    const char* command_id) {
            if (button == nullptr) return;
            const auto* spec = registry.get(command_id);
            if (spec == nullptr || !spec->callback) return;
            QObject::connect(button, &QPushButton::clicked, button,
                             [callback = spec->callback] { callback(); });
        };
        bind(decor->save_button(), "map.save_plan");
        bind(decor->review_button(), "map.submit");
        sync_decor();
    }

    // ---- 上下文 Ribbon 组 (R:33) ------------------------------------------
    auto* scene = bank->edit_scene();
    auto* ribbon = shell->ribbon();
    if (scene == nullptr || ribbon == nullptr) return;

    // 捕捉开关：与场景 snap_manager 同一状态（禁止第二份）。QAction
    // 绑定让 Ribbon 的 Toggle 按钮随状态走。
    auto* snap_action = new QAction(QStringLiteral("捕捉"), shell);
    snap_action->setObjectName(QStringLiteral("FactorSnapToggle"));
    snap_action->setCheckable(true);
    snap_action->setChecked(scene->snap_enabled());
    QObject::connect(snap_action, &QAction::toggled, scene,
                     [scene](bool on) { scene->set_snap_enabled(on); });
    ribbon->set_command_action(QStringLiteral("factor.snap"), snap_action);

    // 选中驱动：line → 约束线组（ws2+ws3）；label → 标注组（ws3）；
    // 其它/空 → 清除。facies/well 无新增上下文组：ws3 静态带已有
    // 相界编辑/参考图组覆盖（诚实说明，见报告）。
    QObject::connect(scene, &ui_pages_mapedit::MapEditScene::selection_ids_changed,
                     ribbon, [scene, ribbon](const QStringList& ids) {
                         const QString kind = selected_kind(scene, ids);
                         const bool line = kind == QStringLiteral("line");
                         const bool label = kind == QStringLiteral("label");
                         for (const int workspace : {2, 3}) {
                             if (line) {
                                 ribbon->set_context_group(
                                     workspace, QStringLiteral("constraint"),
                                     constraint_group_spec());
                             } else {
                                 ribbon->clear_context_group(
                                     workspace, QStringLiteral("constraint"));
                             }
                         }
                         if (label) {
                             ribbon->set_context_group(
                                 3, QStringLiteral("annotation"),
                                 annotation_group_spec());
                         } else {
                             ribbon->clear_context_group(
                                 3, QStringLiteral("annotation"));
                         }
                     });
}

}  // namespace pwb::app::m5_compose

#endif  // PWB_WITH_CLOSURE_MAPPING
