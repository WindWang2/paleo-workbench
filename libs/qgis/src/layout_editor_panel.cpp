// LayoutEditorPanel — implementation. Everything interactive below is a
// QGIS public GUI class (QgsLayoutView + view tools + rulers + the item
// property widgets registered by QgsLayoutGuiUtils::registerGuiForKnownItemTypes);
// the panel is deliberately the thinnest possible host.

#include <pwb/qgis/layout_editor_panel.hpp>

#include <pwb/mapping_document/composer_templates.hpp>
#include <pwb/qgis/layout_export_service.hpp>
#include <pwb/qgis/layout_slots.hpp>
#include <pwb/qgis/layout_slot_item.hpp>

#include <qgsgui.h>
#include <qgslayout.h>
#include <qgslayoutguiutils.h>
#include <qgslayoutitem.h>
#include <qgslayoutitemguiregistry.h>
#include <qgslayoutitemwidget.h>
#include <qgslayoutundostack.h>
#include <qgslayoutview.h>
#include <qgslayoutviewtoolselect.h>
#include <qgslayoutruler.h>
#include <qgsmapcanvas.h>
#include <qgsprintlayout.h>

#include <QAction>
#include <QApplication>
#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QPushButton>
#include <QSplitter>
#include <QStackedWidget>
#include <QToolBar>
#include <QToolTip>
#include <QVBoxLayout>

#include <set>

namespace pwb::qgis {

namespace {

// One-shot process-wide registration of the standard item property widgets
// (QgisApp::initLayouts calls the same util; here from the Paleo host).
void ensure_item_gui_registered(QgsMapCanvas* canvas) {
    static bool registered = false;
    if (registered) return;
    QgsLayoutGuiUtils::registerGuiForKnownItemTypes(canvas);
    PwbLayoutSlotItem::ensure_registered();
    registered = true;
}

}  // namespace

class LayoutEditorPanel::ToolActions {
public:
    QAction* undo = nullptr;
    QAction* redo = nullptr;
};

LayoutEditorPanel::LayoutEditorPanel(LayoutAuthority& authority,
                                     QgsMapCanvas* canvas, QWidget* parent)
    : QWidget(parent), authority_(authority), tools_(new ToolActions) {
    ensure_item_gui_registered(canvas);
    build_ui(canvas);
}

LayoutEditorPanel::~LayoutEditorPanel() = default;

void LayoutEditorPanel::build_ui(QgsMapCanvas* canvas) {
    (void)canvas;
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(4, 4, 4, 4);
    outer->setSpacing(4);

    // ---- toolbar ----------------------------------------------------------
    toolbar_ = new QToolBar(this);
    toolbar_->setIconSize(QSize(16, 16));

    tools_->undo = toolbar_->addAction(QStringLiteral("↶"), tr("撤销"),
                                       this, [this] {
                                           if (active_ != nullptr && active_->undoStack()->stack() != nullptr) {
                                               active_->undoStack()->stack()->undo();
                                           }
                                       });
    tools_->redo = toolbar_->addAction(QStringLiteral("↷"), tr("重做"),
                                       this, [this] {
                                           if (active_ != nullptr && active_->undoStack()->stack() != nullptr) {
                                               active_->undoStack()->stack()->redo();
                                           }
                                       });
    toolbar_->addSeparator();
    toolbar_->addAction(tr("放大"), this, [this] { view_->zoomIn(); });
    toolbar_->addAction(tr("缩小"), this, [this] { view_->zoomOut(); });
    toolbar_->addAction(tr("全幅"), this, [this] { view_->zoomFull(); });
    toolbar_->addSeparator();
    toolbar_->addAction(tr("复制"), this, [this] {
        if (active_ == nullptr) return;
        const QList<QgsLayoutItem*> selected = active_->selectedLayoutItems();
        view_->copyItems(selected, QgsLayoutView::ClipboardCopy);
    });
    toolbar_->addAction(tr("粘贴"), this,
                        [this] { view_->pasteItems(QgsLayoutView::PasteModeCenter); });
    toolbar_->addAction(tr("删除"), this, [this] { view_->deleteSelectedItems(); });
    toolbar_->addSeparator();
    toolbar_->addAction(tr("锁定/解锁"), this, [this] {
        if (active_ == nullptr) return;
        for (QgsLayoutItem* item : active_->selectedLayoutItems()) {
            item->setLocked(!item->isLocked());
        }
    });
    toolbar_->addAction(tr("导出…"), this, &LayoutEditorPanel::on_export);

    // ---- body: [layout list | view+rulers | properties] -------------------
    auto* splitter = new QSplitter(Qt::Horizontal, this);

    auto* left = new QWidget(splitter);
    auto* left_box = new QVBoxLayout(left);
    left_box->setContentsMargins(0, 0, 0, 0);
    template_button_ = new QPushButton(tr("从模板新建"), left);
    connect(template_button_, &QPushButton::clicked, this,
            &LayoutEditorPanel::on_new_from_template);
    layout_list_ = new QListWidget(left);
    layout_list_->setMinimumWidth(150);
    auto* row = new QHBoxLayout();
    auto* duplicate_button = new QPushButton(tr("复制布局"), left);
    auto* remove_button = new QPushButton(tr("删除布局"), left);
    connect(duplicate_button, &QPushButton::clicked, this,
            &LayoutEditorPanel::on_duplicate);
    connect(remove_button, &QPushButton::clicked, this,
            &LayoutEditorPanel::on_remove);
    row->addWidget(duplicate_button);
    row->addWidget(remove_button);
    left_box->addWidget(template_button_);
    left_box->addWidget(layout_list_, /*stretch=*/1);
    left_box->addLayout(row);

    auto* center = new QWidget(splitter);
    auto* center_grid = new QGridLayout(center);
    center_grid->setContentsMargins(0, 0, 0, 0);
    center_grid->setSpacing(0);
    h_ruler_ = new QgsLayoutRuler(center, Qt::Horizontal);
    v_ruler_ = new QgsLayoutRuler(center, Qt::Vertical);
    view_ = new QgsLayoutView(center);
    view_->setHorizontalRuler(h_ruler_);
    view_->setVerticalRuler(v_ruler_);
    // Corner filler where the two rulers meet.
    auto* corner = new QLabel(center);
    corner->setFixedSize(h_ruler_->sizeHint().height(),
                         v_ruler_->sizeHint().width());
    corner->setFrameShape(QFrame::NoFrame);
    center_grid->addWidget(corner, 0, 0);
    center_grid->addWidget(h_ruler_, 0, 1);
    center_grid->addWidget(v_ruler_, 1, 0);
    center_grid->addWidget(view_, 1, 1);

    // ---- right: properties host ------------------------------------------
    properties_host_ = new QWidget(splitter);
    properties_box_ = new QVBoxLayout(properties_host_);
    properties_box_->setContentsMargins(0, 0, 0, 0);
    empty_label_ = new QLabel(tr("选择元素后在此编辑属性"), properties_host_);
    empty_label_->setAlignment(Qt::AlignCenter);
    empty_label_->setEnabled(false);
    properties_box_->addWidget(empty_label_);

    splitter->addWidget(left);
    splitter->addWidget(center);
    splitter->addWidget(properties_host_);
    splitter->setStretchFactor(1, 1);
    splitter->setSizes({200, 800, 300});
    outer->addWidget(toolbar_);
    outer->addWidget(splitter, /*stretch=*/1);

    connect(layout_list_, &QListWidget::currentRowChanged, this,
            &LayoutEditorPanel::on_layout_selected);
    connect(view_, &QgsLayoutView::itemFocused, this,
            [this](QgsLayoutItem* /*item*/) { refresh_selection(); });
    refresh_layout_list();
}

void LayoutEditorPanel::set_active_layout(QgsPrintLayout* layout) {
    detach_active_layout();
    attach_layout(layout);
    // QgsLayoutView::setCurrentLayout(nullptr) dereferences the scene —
    // clearing is done through the QGraphicsView scene setter instead.
    if (layout != nullptr) {
        view_->setCurrentLayout(layout);
    } else {
        view_->setScene(nullptr);
    }
    if (select_tool_ == nullptr) {
        select_tool_ = new QgsLayoutViewToolSelect(view_);
    }
    view_->setTool(select_tool_);
    if (layout != nullptr) view_->zoomFull();
    refresh_selection();
    refresh_undo_actions();
    refresh_layout_list();
    emit active_layout_changed(layout);
}

void LayoutEditorPanel::detach_active_layout() {
    if (active_ == nullptr) return;
    // Both directions: the layout's scene signals (attached via
    // attach_layout) and the undo stack's indexChanged — otherwise the
    // old stack keeps driving refresh/modified after a switch.
    active_->disconnect(this);
    if (QUndoStack* stack = active_->undoStack()->stack()) {
        QObject::disconnect(stack, nullptr, this, nullptr);
    }
    active_ = nullptr;
}

void LayoutEditorPanel::attach_layout(QgsPrintLayout* layout) {
    active_ = layout;
    if (layout == nullptr) return;
    // Scene selection drives the item list + property host (QGraphicsScene
    // signal via the layout object).
    connect(layout, &QGraphicsScene::selectionChanged, this,
            &LayoutEditorPanel::refresh_selection);
    if (QUndoStack* stack = layout->undoStack()->stack()) {
        connect(stack, &QUndoStack::indexChanged, this,
                &LayoutEditorPanel::refresh_undo_actions);
        connect(stack, &QUndoStack::indexChanged, this,
                &LayoutEditorPanel::emit_modified);
    }
    connect(layout, &QObject::destroyed, this, [this]() {
        active_ = nullptr;
        refresh_selection();
        refresh_undo_actions();
    });
}

void LayoutEditorPanel::refresh() {
    refresh_layout_list();
    if (active_ == nullptr) {
        // Pick the first layout so a freshly restored project shows its
        // document instead of an empty view.
        const std::vector<LayoutInfo> infos = authority_.layouts();
        if (!infos.empty()) {
            if (QgsPrintLayout* first =
                    authority_.layout_by_name(infos.front().name)) {
                set_active_layout(first);
            }
        }
    }
}

void LayoutEditorPanel::refresh_layout_list() {
    if (layout_list_->signalsBlocked()) return;
    layout_list_->blockSignals(true);
    layout_list_->clear();
    const std::vector<LayoutInfo> infos = authority_.layouts();
    int active_row = -1;
    for (std::size_t i = 0; i < infos.size(); ++i) {
        const LayoutInfo& info = infos[i];
        QString label = QString::fromStdString(info.name);
        if (info.dirty) label += QStringLiteral(" *");
        if (!info.template_id.empty()) {
            label += QStringLiteral("  [") +
                     QString::fromStdString(info.template_id) +
                     QStringLiteral("]");
        }
        layout_list_->addItem(label);
        if (active_ != nullptr && info.name == active_->name().toStdString()) {
            active_row = static_cast<int>(i);
        }
    }
    layout_list_->blockSignals(false);
    if (active_row >= 0) {
        layout_list_->setCurrentRow(active_row);
    } else if (active_ != nullptr && !infos.empty()) {
        on_layout_selected(0);
    }
}

void LayoutEditorPanel::on_layout_selected(int row) {
    if (row < 0) return;
    const std::vector<LayoutInfo> infos = authority_.layouts();
    if (static_cast<std::size_t>(row) >= infos.size()) return;
    QgsPrintLayout* layout =
        authority_.layout_by_name(infos[static_cast<std::size_t>(row)].name);
    if (layout == nullptr || layout == active_) return;
    set_active_layout(layout);
}

void LayoutEditorPanel::on_new_from_template() {
    QMenu menu(this);
    for (const auto& tpl : mapping_document::composer_template_library()) {
        const QString label =
            QString::fromStdString(tpl.label) + QStringLiteral(" (") +
            QString::fromStdString(tpl.template_id) + QStringLiteral(")");
        menu.addAction(label, this, [this, id = tpl.template_id]() {
            const LayoutAuthority::InstantiateReport report =
                authority_.instantiate_template(id);
            if (report.layout != nullptr) {
                set_active_layout(report.layout);
                emit layouts_modified();
            } else {
                QToolTip::showText(
                    QCursor::pos(),
                    tr("模板实例化失败：%1")
                        .arg(report.warnings.empty()
                                 ? tr("未知错误")
                                 : QString::fromStdString(report.warnings.front())),
                    this);
            }
        });
    }
    menu.exec(QCursor::pos());
}

void LayoutEditorPanel::on_duplicate() {
    if (active_ == nullptr) return;
    const std::string base = active_->name().toStdString() + " " + tr("副本").toStdString();
    QgsPrintLayout* duplicated =
        authority_.duplicate_layout(active_->name().toStdString(),
                                    authority_.unique_layout_name(base));
    if (duplicated != nullptr) {
        set_active_layout(duplicated);
        emit layouts_modified();
    }
}

void LayoutEditorPanel::on_remove() {
    if (active_ == nullptr) return;
    // Pick the neighbor before removal: the view must never sit on a
    // scene the manager is about to destroy.
    const std::string doomed_name = active_->name().toStdString();
    QgsPrintLayout* next = nullptr;
    bool past_doomed = false;
    for (const LayoutInfo& info : authority_.layouts()) {
        if (info.name == doomed_name) {
            past_doomed = true;
            continue;
        }
        if (next == nullptr || !past_doomed) {
            next = authority_.layout_by_name(info.name);
            if (past_doomed) break;
        }
    }
    set_active_layout(next);
    if (authority_.remove_layout(doomed_name)) {
        emit layouts_modified();
    }
    refresh_layout_list();
}

void LayoutEditorPanel::on_export() {
    if (active_ == nullptr) return;
    emit export_requested(active_);
}

void LayoutEditorPanel::refresh_selection() {
    // Item list highlights + property host rebuild.
    if (properties_box_ == nullptr) return;
    // Clear the previous property widget (keep the empty label).
    while (properties_box_->count() > 1) {
        QLayoutItem* child = properties_box_->takeAt(1);
        if (child->widget() != nullptr) child->widget()->deleteLater();
        delete child;
    }
    empty_label_->setVisible(true);
    if (active_ == nullptr) return;

    const QList<QgsLayoutItem*> selected = active_->selectedLayoutItems();
    if (selected.size() != 1) {
        empty_label_->setText(selected.isEmpty()
                                  ? tr("选择元素后在此编辑属性")
                                  : tr("已选中 %1 个元素（批量操作用工具栏）")
                                        .arg(selected.size()));
        return;
    }
    QgsLayoutItem* item = selected.first();
    if (QWidget* widget =
            QgsGui::layoutItemGuiRegistry()->createItemWidget(item)) {
        empty_label_->setVisible(false);
        properties_box_->addWidget(widget, /*stretch=*/1);
    }
    const auto slot = item_slot(active_, item);
    if (slot.has_value()) {
        auto* tag = new QLabel(
            tr("槽位: %1%2")
                .arg(QString::fromStdString(slot->slot))
                .arg(slot->binding_id.empty()
                         ? QString()
                         : QStringLiteral("  ← ") +
                               QString::fromStdString(slot->binding_id)),
            properties_host_);
        properties_box_->addWidget(tag);
    }
}

void LayoutEditorPanel::refresh_undo_actions() {
    if (tools_ == nullptr || tools_->undo == nullptr) return;
    const QUndoStack* stack =
        active_ != nullptr ? active_->undoStack()->stack() : nullptr;
    tools_->undo->setEnabled(stack != nullptr && stack->canUndo());
    tools_->redo->setEnabled(stack != nullptr && stack->canRedo());
    // Dirty marker in the list.
    refresh_layout_list();
}

void LayoutEditorPanel::emit_modified() {
    emit layouts_modified();
}

}  // namespace pwb::qgis
