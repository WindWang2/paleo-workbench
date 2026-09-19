#include "pwb/ui_review/qt/composite_prototype.hpp"

#include "pwb/ui_map/display_map_canvas.hpp"
#include "pwb/ui_map/map_chrome_core.hpp"
#include "pwb/ui_widgets/icon_factory.hpp"

#include <QFrame>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QResizeEvent>
#include <QSlider>
#include <QSplitter>
#include <QTimer>
#include <QToolButton>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <array>

namespace pwb::ui_review::qt {

namespace {

constexpr std::array<std::pair<const char*, const char*>, 3> kVariants{{
    {"A", "右置图层管理"},
    {"B", "双栏工作台"},
    {"C", "全幅浮动停靠"},
}};

}  // namespace

bool prototype_requested() {
    const QByteArray value =
        qgetenv("PALEO_PROTOTYPE_COMPOSITE").trimmed().toLower();
    return value == "1" || value == "true" || value == "yes" ||
           value == "on";
}

// -- LayerManagerPanel ----------------------------------------------------------

LayerManagerPanel::LayerManagerPanel(CompositeVariantsWidget* owner,
                                     QWidget* parent)
    : QFrame(parent), owner_(owner) {
    setObjectName(QStringLiteral("PanelCard"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(8, 8, 8, 8);
    outer->setSpacing(6);

    auto* title = new QLabel(QStringLiteral("图层管理"), this);
    title->setObjectName(QStringLiteral("WorkstationPanelTitle"));
    outer->addWidget(title);

    search_ = new QLineEdit(this);
    search_->setPlaceholderText(QStringLiteral("搜索图层名称"));
    search_->setClearButtonEnabled(true);
    outer->addWidget(search_);

    tree_ = new QTreeWidget(this);
    tree_->setHeaderHidden(true);
    tree_->setRootIsDecorated(false);
    outer->addWidget(tree_, 1);

    auto* row = new QHBoxLayout();
    row->addWidget(new QLabel(QStringLiteral("不透明度"), this));
    opacity_ = new QSlider(Qt::Horizontal, this);
    opacity_->setRange(10, 100);
    opacity_->setValue(100);
    row->addWidget(opacity_, 1);
    outer->addLayout(row);

    auto* order = new QHBoxLayout();
    for (const auto& [label, icon, direction] :
         std::array{std::tuple{QStringLiteral("上移"),
                               QStringLiteral("map/tree-move-up.svg"), +1},
                    std::tuple{QStringLiteral("下移"),
                               QStringLiteral("map/tree-move-down.svg"),
                               -1}}) {
        auto* button = new QToolButton(this);
        button->setObjectName(
            QStringLiteral("WorkstationContextButton"));
        button->setIcon(ui_widgets::workstation_icon(icon));
        button->setText(label);
        button->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        connect(button, &QToolButton::clicked, this,
                [this, direction]() { move(direction); });
        order->addWidget(button);
    }
    order->addStretch(1);
    outer->addLayout(order);

    auto* legend_title = new QLabel(QStringLiteral("图例"), this);
    legend_title->setObjectName(
        QStringLiteral("WorkstationPanelFootnote"));
    outer->addWidget(legend_title);
    legend_ = new QListWidget(this);
    legend_->setMaximumHeight(96);
    for (const auto& [label, color] :
         ui_map::workarea_legend_items()) {
        auto* item =
            new QListWidgetItem(QStringLiteral("●  ") +
                                QString::fromStdString(label));
        item->setForeground(
            QColor(QString::fromStdString(color)));
        legend_->addItem(item);
    }
    outer->addWidget(legend_);

    connect(search_, &QLineEdit::textChanged, this,
            &LayerManagerPanel::filter);
    connect(tree_, &QTreeWidget::itemChanged, this,
            [this](QTreeWidgetItem* item, int) {
                on_item_changed(item);
            });
    connect(tree_, &QTreeWidget::currentItemChanged, this,
            [this](QTreeWidgetItem*, QTreeWidgetItem*) {
                sync_opacity();
            });
    connect(opacity_, &QSlider::valueChanged, this,
            &LayerManagerPanel::apply_opacity);
    reload();
}

void LayerManagerPanel::reload() {
    reload_guard_ = true;
    tree_->clear();
    for (const auto& layer : owner_->layers()) {
        auto* item = new QTreeWidgetItem(
            {QString::fromStdString(composite_layer_name(layer))});
        item->setData(0, Qt::UserRole,
                      QString::fromStdString(
                          composite_layer_id(layer)));
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(
            0, composite_layer_visible(layer) ? Qt::Checked
                                              : Qt::Unchecked);
        tree_->addTopLevelItem(item);
    }
    reload_guard_ = false;
}

void LayerManagerPanel::refresh_tree() {
    reload();
}

void LayerManagerPanel::filter(const QString& text) {
    const QString needle = text.trimmed().toLower();
    for (int row = 0; row < tree_->topLevelItemCount(); ++row) {
        QTreeWidgetItem* item = tree_->topLevelItem(row);
        item->setHidden(!needle.isEmpty() &&
                        !item->text(0).toLower().contains(needle));
    }
}

void LayerManagerPanel::on_item_changed(QTreeWidgetItem* item) {
    if (reload_guard_ || item == nullptr) {
        return;
    }
    owner_->set_layer_visible(
        item->data(0, Qt::UserRole).toString().toStdString(),
        item->checkState(0) == Qt::Checked);
}

void LayerManagerPanel::sync_opacity() {
    QTreeWidgetItem* item = tree_->currentItem();
    if (item == nullptr) {
        return;
    }
    const domain::Json* layer = owner_->layer_by_id(
        item->data(0, Qt::UserRole).toString().toStdString());
    if (layer != nullptr) {
        opacity_->blockSignals(true);
        opacity_->setValue(int(composite_layer_opacity(*layer) * 100));
        opacity_->blockSignals(false);
    }
}

void LayerManagerPanel::apply_opacity(int value) {
    QTreeWidgetItem* item = tree_->currentItem();
    if (item != nullptr) {
        owner_->set_layer_opacity(
            item->data(0, Qt::UserRole).toString().toStdString(),
            value / 100.0);
    }
}

void LayerManagerPanel::move(int direction) {
    QTreeWidgetItem* item = tree_->currentItem();
    if (item != nullptr) {
        owner_->move_layer(
            item->data(0, Qt::UserRole).toString().toStdString(),
            direction);
    }
}

// -- CompositeVariantsWidget -----------------------------------------------------

CompositeVariantsWidget::CompositeVariantsWidget(
    QWidget* parent, const domain::Json& snapshot,
    const domain::Json& project_json)
    : QWidget(parent), project_json_(project_json) {
    canvas_ = new ui_map::DisplayMapCanvas();
    if (snapshot.is_object()) {
        const auto crs_it = snapshot.find("project_crs");
        if (crs_it != snapshot.end() && crs_it->is_string()) {
            project_crs_ = crs_it->get<std::string>();
        }
        const auto layers_it = snapshot.find("layers");
        if (layers_it != snapshot.end() && layers_it->is_array()) {
            layers_.assign(layers_it->begin(), layers_it->end());
        }
    }
    // Initial publish — direct snapshot set (the layer manager does not
    // exist yet; publish() guards on it).
    canvas_->set_layer_snapshot(
        composite_snapshot_json(project_crs_, layers_));
    const auto extent = ui_map::workarea_view_extent(
        composite_snapshot_json(project_crs_, layers_));
    if (extent) {
        canvas_->set_extent(*extent, /*record_history=*/false);
    }
    layer_manager_ = new LayerManagerPanel(this);
    apply_variant(0);
}

QString CompositeVariantsWidget::variant_key() const {
    return QString::fromLatin1(kVariants[size_t(variant_index_)].first);
}

QString CompositeVariantsWidget::variant_name() const {
    return QString::fromUtf8(kVariants[size_t(variant_index_)].second);
}

const domain::Json*
CompositeVariantsWidget::layer_by_id(const std::string& id) const {
    const int index = composite_layer_index(layers_, id);
    return index >= 0 ? &layers_[size_t(index)] : nullptr;
}

void CompositeVariantsWidget::publish() {
    canvas_->set_layer_snapshot(
        composite_snapshot_json(project_crs_, layers_));
    if (layer_manager_ != nullptr) {
        layer_manager_->refresh_tree();
    }
}

void CompositeVariantsWidget::set_layer_visible(const std::string& id,
                                                bool visible) {
    if (composite_set_visible(layers_, id, visible)) {
        publish();
    }
}

void CompositeVariantsWidget::set_layer_opacity(const std::string& id,
                                                double opacity) {
    if (composite_set_opacity(layers_, id, opacity)) {
        publish();
    }
}

void CompositeVariantsWidget::move_layer(const std::string& id,
                                         int direction) {
    if (composite_move_layer(layers_, id, direction)) {
        publish();
    }
}

// -- variants ------------------------------------------------------------------

void CompositeVariantsWidget::apply_variant(int index) {
    variant_index_ =
        ((index % int(kVariants.size())) + int(kVariants.size())) %
        int(kVariants.size());
    // Detach survivors before the old layout tree is destroyed.
    canvas_->setParent(nullptr);
    layer_manager_->setParent(nullptr);
    c_page_ = nullptr;
    c_relayout_ = nullptr;
    if (QLayout* old = layout()) {
        QWidget().setLayout(old);
    }
    QWidget* page = nullptr;
    switch (variant_index_) {
    case 0:
        page = build_a();
        break;
    case 1:
        page = build_b();
        break;
    default:
        page = build_c();
        break;
    }
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);
    outer->addWidget(page, 1);
    mount_switcher();
    emit variant_changed();
}

void CompositeVariantsWidget::keyPressEvent(QKeyEvent* event) {
    // Direction keys cycle variants unless a text field owns focus.
    if (qobject_cast<QLineEdit*>(focusWidget()) != nullptr) {
        QWidget::keyPressEvent(event);
        return;
    }
    if (event->key() == Qt::Key_Left) {
        previous_variant();
    } else if (event->key() == Qt::Key_Right) {
        next_variant();
    } else {
        QWidget::keyPressEvent(event);
    }
}

void CompositeVariantsWidget::mount_switcher() {
    if (switcher_ != nullptr) {
        switcher_->deleteLater();
    }
    auto* bar = new QFrame(this);
    bar->setObjectName(QStringLiteral("PrototypeSwitcher"));
    bar->setStyleSheet(QStringLiteral(
        "QFrame#PrototypeSwitcher { background: #18232d;"
        " border-radius: 16px; }"
        "QFrame#PrototypeSwitcher QLabel { color: #ffffff;"
        " font-size: 12px; }"
        "QFrame#PrototypeSwitcher QToolButton { color: #ffffff;"
        " border: none; background: transparent; padding: 4px 10px;"
        " font-size: 14px; }"));
    auto* layout = new QHBoxLayout(bar);
    layout->setContentsMargins(6, 2, 6, 2);
    layout->setSpacing(4);
    auto* prev_button = new QToolButton(bar);
    prev_button->setText(QStringLiteral("◀"));
    auto* next_button = new QToolButton(bar);
    next_button->setText(QStringLiteral("▶"));
    auto* label = new QLabel(
        variant_key() + " — " + variant_name(), bar);
    connect(prev_button, &QToolButton::clicked, this,
            &CompositeVariantsWidget::previous_variant);
    connect(next_button, &QToolButton::clicked, this,
            &CompositeVariantsWidget::next_variant);
    layout->addWidget(prev_button);
    layout->addWidget(label);
    layout->addWidget(next_button);
    bar->adjustSize();
    switcher_ = bar;
    reposition_switcher();
}

void CompositeVariantsWidget::reposition_switcher() {
    if (switcher_ == nullptr) {
        return;
    }
    switcher_->move((width() - switcher_->width()) / 2,
                    height() - switcher_->height() - 10);
    switcher_->raise();
}

void CompositeVariantsWidget::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    reposition_switcher();
}

bool CompositeVariantsWidget::eventFilter(QObject* watched,
                                          QEvent* event) {
    // Variant-C relayout (Python monkey-patches page.resizeEvent).
    if (watched == c_page_ && event->type() == QEvent::Resize &&
        c_relayout_) {
        c_relayout_();
    }
    return QWidget::eventFilter(watched, event);
}

// -- variant builders ----------------------------------------------------------

QWidget* CompositeVariantsWidget::map_toolbar() {
    auto* bar = new QFrame();
    bar->setObjectName(QStringLiteral("WorkstationContextBar"));
    auto* layout = new QHBoxLayout(bar);
    layout->setContentsMargins(6, 3, 6, 3);
    layout->setSpacing(3);
    bool checked_seen = false;
    for (const auto& [label, icon, tip, checkable] : std::array{
             std::tuple{QStringLiteral("选择"),
                        QStringLiteral("map/select.svg"),
                        QStringLiteral("选择要素"), true},
             std::tuple{QStringLiteral("平移"),
                        QStringLiteral("map/pan.svg"),
                        QStringLiteral("平移"), true},
             std::tuple{QStringLiteral("缩放+"),
                        QStringLiteral("map/zoom_in.svg"),
                        QStringLiteral("放大"), false},
             std::tuple{QStringLiteral("缩放-"),
                        QStringLiteral("map/zoom_out.svg"),
                        QStringLiteral("缩小"), false},
             std::tuple{QStringLiteral("全图"),
                        QStringLiteral("map/full_extent.svg"),
                        QStringLiteral("全图"), false},
             std::tuple{QStringLiteral("测距"),
                        QStringLiteral("map/measure_distance.svg"),
                        QStringLiteral("测距"), false},
             std::tuple{QStringLiteral("查询"),
                        QStringLiteral("map/identify.svg"),
                        QStringLiteral("查询"), false},
             std::tuple{QStringLiteral("清除"),
                        QStringLiteral("map/clear_selection.svg"),
                        QStringLiteral("清除选择"), false}}) {
        auto* button = new QToolButton(bar);
        button->setObjectName(
            QStringLiteral("WorkstationContextButton"));
        button->setIcon(ui_widgets::workstation_icon(icon));
        button->setText(label);
        button->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        button->setToolTip(tip);
        button->setCheckable(checkable);
        if (checkable && !checked_seen) {
            button->setChecked(true);
            checked_seen = true;
        }
        layout->addWidget(button);
    }
    layout->addStretch(1);
    return bar;
}

QWidget* CompositeVariantsWidget::input_tree() {
    // B-variant「输入与结果」tree mock: real well names + fixed groups.
    auto* tree = new QTreeWidget();
    tree->setHeaderHidden(true);
    QStringList wells;
    const auto wells_it = project_json_.find("wells");
    if (wells_it != project_json_.end() && wells_it->is_array()) {
        for (const auto& well : *wells_it) {
            const auto name_it = well.find("name");
            if (name_it != well.end() && name_it->is_string()) {
                wells << QString::fromStdString(
                    name_it->get<std::string>());
            }
        }
    }
    auto group = [tree](const QString& title,
                        const QStringList& children) {
        auto* node = new QTreeWidgetItem({title});
        node->setFlags(node->flags() | Qt::ItemIsUserCheckable);
        node->setCheckState(0, Qt::Checked);
        for (const QString& child : children) {
            auto* leaf = new QTreeWidgetItem({child});
            leaf->setFlags(leaf->flags() | Qt::ItemIsUserCheckable);
            leaf->setCheckState(0, Qt::Checked);
            node->addChild(leaf);
        }
        return node;
    };
    QStringList well_children = wells.mid(0, 8);
    if (wells.size() > 8) {
        well_children << QStringLiteral("…");
    }
    tree->addTopLevelItem(
        group(QStringLiteral("井数据 (%1)").arg(wells.size()),
              well_children));
    tree->addTopLevelItem(
        group(QStringLiteral("地震数据"),
              {QStringLiteral("200P_seismic"),
               QStringLiteral("振幅属性"),
               QStringLiteral("频率属性")}));
    tree->addTopLevelItem(
        group(QStringLiteral("结果"),
              {QStringLiteral("工区边界"),
               QStringLiteral("测线标注"),
               QStringLiteral("不确定图")}));
    return tree;
}

QWidget* CompositeVariantsWidget::build_a() {
    // A「右置图层管理」：工具条 + 地图主体 + 右侧图层管理。
    auto* page = new QWidget();
    auto* split = new QSplitter(Qt::Horizontal);
    auto* map_column = new QWidget();
    auto* map_layout = new QVBoxLayout(map_column);
    map_layout->setContentsMargins(0, 0, 0, 0);
    map_layout->setSpacing(0);
    map_layout->addWidget(map_toolbar());
    map_layout->addWidget(canvas_, 1);
    split->addWidget(map_column);
    split->addWidget(layer_manager_);
    split->setSizes({1050, 300});
    auto* page_layout = new QVBoxLayout(page);
    page_layout->setContentsMargins(0, 0, 0, 0);
    page_layout->addWidget(split);
    return page;
}

QWidget* CompositeVariantsWidget::build_b() {
    // B「双栏工作台」：左输入树 + 地图 + 右侧图层管理/检查器。
    auto* page = new QWidget();
    auto* page_layout = new QVBoxLayout(page);
    page_layout->setContentsMargins(0, 0, 0, 0);
    page_layout->setSpacing(0);
    page_layout->addWidget(map_toolbar());

    auto* split = new QSplitter(Qt::Horizontal);
    auto* left = new QFrame();
    left->setObjectName(QStringLiteral("PanelCard"));
    auto* left_layout = new QVBoxLayout(left);
    left_layout->setContentsMargins(8, 8, 8, 8);
    auto* title = new QLabel(QStringLiteral("输入与结果"), left);
    title->setObjectName(QStringLiteral("WorkstationPanelTitle"));
    left_layout->addWidget(title);
    left_layout->addWidget(input_tree(), 1);

    auto* map_column = new QWidget();
    auto* map_layout = new QVBoxLayout(map_column);
    map_layout->setContentsMargins(0, 0, 0, 0);
    map_layout->addWidget(canvas_, 1);

    auto* right = new QSplitter(Qt::Vertical);
    right->addWidget(layer_manager_);
    auto* inspector = new QFrame();
    inspector->setObjectName(QStringLiteral("PanelCard"));
    auto* inspector_layout = new QVBoxLayout(inspector);
    auto* inspector_title =
        new QLabel(QStringLiteral("检查器"), inspector);
    inspector_title->setObjectName(
        QStringLiteral("WorkstationPanelTitle"));
    inspector_layout->addWidget(inspector_title);
    inspector_layout->addWidget(
        new QLabel(QStringLiteral(
            "选中图层/要素的属性将在这里显示（mock）"),
            inspector));
    inspector_layout->addStretch(1);
    right->addWidget(inspector);
    right->setSizes({320, 220});

    split->addWidget(left);
    split->addWidget(map_column);
    split->addWidget(right);
    split->setSizes({240, 860, 300});
    page_layout->addWidget(split, 1);
    return page;
}

QWidget* CompositeVariantsWidget::build_c() {
    // C「全幅浮动停靠」：地图全幅 + 浮动图层管理 + 悬浮工具条。
    auto* page = new QWidget();
    page->setStyleSheet(QStringLiteral("background: #101418;"));
    auto* page_layout = new QVBoxLayout(page);
    page_layout->setContentsMargins(0, 0, 0, 0);
    page_layout->addWidget(canvas_, 1);

    QWidget* toolbar = map_toolbar();
    toolbar->setParent(page);
    toolbar->adjustSize();

    layer_manager_->setParent(page);
    layer_manager_->adjustSize();
    auto* toggle = new QToolButton(page);
    toggle->setText(QStringLiteral("◀ 图层"));
    toggle->setStyleSheet(QStringLiteral(
        "QToolButton { background: rgba(24,35,45,0.85);"
        " color: white; border-radius: 4px; padding: 4px 8px; }"));

    auto* toggle_ptr = toggle;
    auto* page_ptr = page;
    auto* toolbar_ptr = toolbar;
    auto relayout = [this, page_ptr, toolbar_ptr, toggle_ptr]() {
        const int w = page_ptr->width();
        toolbar_ptr->move((w - toolbar_ptr->width()) / 2, 8);
        // Qualified: the panel's own move(int direction) hides QWidget::move.
        layer_manager_->QWidget::move(
            w - layer_manager_->width() - 10, 48);
        toggle_ptr->move(w - layer_manager_->width() - 10, 12);
    };
    page->installEventFilter(this);  // resize → relayout (see eventFilter)
    c_page_ = page;
    c_relayout_ = relayout;

    connect(toggle_ptr, &QToolButton::clicked, this,
            [this, toggle_ptr]() {
                const bool hidden = layer_manager_->isHidden();
                layer_manager_->setVisible(hidden);
                toggle_ptr->setText(hidden ? QStringLiteral("◀ 图层")
                                           : QStringLiteral("▶ 图层"));
            });
    QTimer::singleShot(0, page, relayout);
    return page;
}

}  // namespace pwb::ui_review::qt
