#include <pwb/ui_composite/layer_manager_panel.hpp>

#include <pwb/ui_composite/templates.hpp>
#include <pwb/ui_widgets/icon_factory.hpp>
#include <pwb/ui_widgets/ui_context.hpp>

#include <QColor>
#include <QHBoxLayout>
#include <QMenu>
#include <QPainter>
#include <QPixmap>
#include <QScrollBar>
#include <QTreeWidgetItem>
#include <QVariantMap>
#include <QVBoxLayout>

#include <algorithm>
#include <tuple>

namespace pwb::ui_composite {

namespace {

// GEOMETRY_TYPE → GEOMETRY_KIND（_snapshot_geometry_kind 嗅探回退）。
const std::map<std::string, std::string>& geometry_type_kind() {
    static const std::map<std::string, std::string> kinds = {
        {"Point", "point"},           {"MultiPoint", "point"},
        {"LineString", "line"},       {"MultiLineString", "line"},
        {"Polygon", "polygon"},       {"MultiPolygon", "polygon"},
    };
    return kinds;
}

std::string meta_value(const MapLayerSnapshot& layer, const char* key) {
    auto it = layer.metadata.find(key);
    return it == layer.metadata.end() ? "" : it->second;
}

// 图层几何类型：编辑图层取元数据权威，基础图层嗅探首个要素。
std::string snapshot_geometry_kind(const MapLayerSnapshot& layer) {
    const std::string kind = meta_value(layer, "geometry_kind");
    for (const std::string& known : geometry_kinds()) {
        if (kind == known) return kind;
    }
    for (const Json& feature : layer.features) {
        const Json geometry =
            feature.is_object() ? feature.value("geometry", Json()) : Json();
        if (geometry.is_object()) {
            const std::string type =
                geometry.value("type", std::string());
            auto it = geometry_type_kind().find(type);
            if (it != geometry_type_kind().end()) return it->second;
        }
    }
    return "";
}

// 状态 tone → tokens palette 键（V7 §7 状态列前景色；随主题重取）。
const char* tone_palette_key(const std::string& tone) {
    static const std::map<std::string, const char*> keys = {
        {"ok", "SUCCESS"},     {"warn", "WARNING"},
        {"error", "ERROR_RED"}, {"info", "PRIMARY"},
        {"muted", "TEXT_SECONDARY"}, {"locked", "TEXT_SECONDARY"},
    };
    auto it = keys.find(tone);
    return it == keys.end() ? nullptr : it->second;
}

QColor decoration_color(const std::string& tone) {
    const char* key = tone_palette_key(tone);
    if (key == nullptr) return {};
    const QString token = pwb::ui_widgets::palette_token(key);
    const QColor color(token);
    return color.isValid() ? color : QColor();
}

const std::vector<std::pair<QString, QString>>& workarea_legend_items() {
    // WORKAREA_LEGEND_ITEMS parity — 与工区定位图同一份配色词汇。
    static const std::vector<std::pair<QString, QString>> items = {
        {QStringLiteral("工区边界"), QStringLiteral("#64748b")},
        {QStringLiteral("地震工区"), QStringLiteral("#0d9488")},
        {QStringLiteral("井位"), QStringLiteral("#409cff")},
        {QStringLiteral("井位（坐标待处理）"),
         QStringLiteral("#f59e0b")},
    };
    return items;
}

}  // namespace

QIcon layer_kind_icon(const std::string& kind, const Json& style) {
    std::string color_name;
    if (style.is_object()) {
        color_name = style.value("stroke", std::string());
        if (color_name.empty() || color_name == "transparent") {
            color_name = style.value("fill", std::string("#868e96"));
        }
    }
    if (color_name.empty()) color_name = "#868e96";
    QColor color(QString::fromStdString(color_name));
    if (!color.isValid()) color = QColor("#868e96");
    QPixmap pixmap(16, 16);
    pixmap.fill(Qt::transparent);
    QPainter painter(&pixmap);
    painter.setRenderHint(QPainter::Antialiasing);
    if (kind == "point") {
        painter.setPen(Qt::NoPen);
        painter.setBrush(color);
        painter.drawEllipse(3, 3, 10, 10);
    } else if (kind == "polygon") {
        QColor fill = color;
        fill.setAlpha(110);
        painter.setBrush(fill);
        painter.setPen(QPen(color, 1.4));
        painter.drawRect(2, 3, 12, 10);
    } else {  // 线（含未知类型的保守回退）
        painter.setPen(QPen(color, 2.0));
        painter.drawLine(1, 13, 7, 8);
        painter.drawLine(7, 8, 15, 3);
    }
    painter.end();
    return QIcon(pixmap);
}

// ---------------------------------------------------------------------------
// LayerManagerPanel
// ---------------------------------------------------------------------------

LayerManagerPanel::LayerManagerPanel(QWidget* parent) : QFrame(parent) {
    setObjectName("PanelCard");

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(6);

    search = new QLineEdit(this);
    search->setPlaceholderText(QStringLiteral("搜索图层名称"));
    search->setClearButtonEnabled(true);
    outer->addWidget(search);

    auto* manage_row = new QHBoxLayout();
    const struct {
        QString label;
        const char* icon;
        QString tip;
    } buttons[] = {
        {QStringLiteral("新建矢量图层"), "map/tree-add-layer.svg",
         QStringLiteral("新建点 / 线 / 面矢量图层")},
        {QStringLiteral("导入参考图层"), "map/tree-add-layer.svg",
         QStringLiteral("导入外部矢量文件作为只读参考（GDAL）")},
        {QStringLiteral("相分类词表"), "map/tree-attribute-table.svg",
         QStringLiteral(
             "查看/导入/恢复 相-亚相-微相三级分类词表")},
        {QStringLiteral("删除图层"), "map/tree-remove.svg",
         QStringLiteral("删除当前矢量图层（编修图层）")},
    };
    for (int i = 0; i < 4; ++i) {
        auto* button = new QToolButton(this);
        button->setObjectName("WorkstationContextButton");
        button->setIcon(
            pwb::ui_widgets::workstation_icon(buttons[i].icon));
        button->setText(buttons[i].label);
        button->setToolTip(buttons[i].tip);
        button->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        // R3 P2-4：紧凑地板，正文交给省略。
        button->setMinimumWidth(0);
        button->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Fixed);
        manage_row->addWidget(button);
        switch (i) {
            case 0:
                connect(button, &QToolButton::clicked, this,
                        &LayerManagerPanel::create_layer_requested);
                break;
            case 1:
                connect(button, &QToolButton::clicked, this,
                        &LayerManagerPanel::import_reference_requested);
                break;
            case 2:
                connect(button, &QToolButton::clicked, this,
                        &LayerManagerPanel::facies_taxonomy_requested);
                break;
            case 3:
                remove_button = button;
                connect(button, &QToolButton::clicked, this, [this]() {
                    QTreeWidgetItem* item = tree->currentItem();
                    if (item == nullptr) return;
                    const std::string layer_id =
                        item->data(0, Qt::UserRole).toString().toStdString();
                    const MapLayerSnapshot* lyr = layer_by_id(layer_id);
                    if (lyr != nullptr && is_editable_layer(*lyr)) {
                        emit remove_layer_requested(
                            QString::fromStdString(layer_id));
                    }
                });
                break;
        }
    }
    remove_button->setEnabled(false);
    manage_row->addStretch(1);
    outer->addLayout(manage_row);

    tree = new QTreeWidget(this);
    tree->setHeaderHidden(true);
    tree->setRootIsDecorated(false);
    // V7 §7：第 2 列 = 状态装饰（glyph+label；hover 摘要看 tooltip）。
    tree->setColumnCount(2);
    tree->setColumnWidth(0, 320);
    tree->setColumnWidth(1, 96);
    tree->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(tree, &QTreeWidget::customContextMenuRequested, this,
            &LayerManagerPanel::on_context_menu);
    connect(tree, &QTreeWidget::itemDoubleClicked, this,
            [this](QTreeWidgetItem* item, int) {
                emit zoom_to_layer_requested(
                    item->data(0, Qt::UserRole).toString());
            });
    outer->addWidget(tree, 1);

    auto* opacity_row = new QHBoxLayout();
    auto* opacity_label = new QLabel(QStringLiteral("不透明度"), this);
    opacity_label->setObjectName("WorkstationPanelFootnote");
    opacity_row->addWidget(opacity_label);
    opacity = new QSlider(Qt::Horizontal, this);
    opacity->setRange(10, 100);
    opacity->setValue(100);
    opacity_row->addWidget(opacity, 1);
    outer->addLayout(opacity_row);

    auto* order_row = new QHBoxLayout();
    for (const auto& [label, icon, direction] :
         {std::tuple{QStringLiteral("上移"), "map/tree-move-up.svg", +1},
          {QStringLiteral("下移"), "map/tree-move-down.svg", -1}}) {
        auto* button = new QToolButton(this);
        button->setObjectName("WorkstationContextButton");
        button->setIcon(pwb::ui_widgets::workstation_icon(icon));
        button->setText(label);
        button->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        connect(button, &QToolButton::clicked, this,
                [this, direction]() {
                    QTreeWidgetItem* item = tree->currentItem();
                    if (item != nullptr) {
                        move_layer(item->data(0, Qt::UserRole)
                                       .toString()
                                       .toStdString(),
                                   direction);
                    }
                });
        order_row->addWidget(button);
    }
    order_row->addStretch(1);
    outer->addLayout(order_row);

    auto* legend_title = new QLabel(QStringLiteral("图例"), this);
    legend_title->setObjectName("WorkstationPanelFootnote");
    outer->addWidget(legend_title);
    legend = new QListWidget(this);
    legend->setObjectName("WorkstationTaskTree");
    legend->setMaximumHeight(96);
    for (const auto& [label, color] : workarea_legend_items()) {
        auto* item = new QListWidgetItem(
            QStringLiteral("●  %1").arg(label));
        item->setForeground(QColor(color));
        legend->addItem(item);
    }
    outer->addWidget(legend);

    connect(search, &QLineEdit::textChanged, this,
            &LayerManagerPanel::filter);
    connect(tree, &QTreeWidget::currentItemChanged, this,
            &LayerManagerPanel::on_current_changed);
    connect(opacity, &QSlider::valueChanged, this,
            &LayerManagerPanel::apply_opacity);
}

// -- 绑定 -----------------------------------------------------------------------

bool LayerManagerPanel::is_editable_layer(const MapLayerSnapshot& layer) {
    return meta_value(layer, "editable") == "true";
}

bool LayerManagerPanel::is_reference_layer(const MapLayerSnapshot& layer) {
    return meta_value(layer, "reference") == "true";
}

int LayerManagerPanel::tree_row_count() const {
    return tree->topLevelItemCount();
}

void LayerManagerPanel::bind(
    const LayerPanelCanvasHooks& canvas,
    const std::vector<MapLayerSnapshot>& layers) {
    canvas_ = canvas;
    layers_ = layers;
    reload();
}

void LayerManagerPanel::set_project_crs(const std::string& crs) {
    if (!crs.empty() && crs != project_crs_) project_crs_ = crs;
}

void LayerManagerPanel::select_layer(const std::string& layer_id) {
    for (int row = 0; row < tree->topLevelItemCount(); ++row) {
        QTreeWidgetItem* item = tree->topLevelItem(row);
        if (item->data(0, Qt::UserRole).toString().toStdString() ==
            layer_id) {
            tree->setCurrentItem(item);
            return;
        }
    }
}

const MapLayerSnapshot* LayerManagerPanel::layer_by_id(
    const std::string& layer_id) const {
    for (const MapLayerSnapshot& layer : layers_) {
        if (layer.id == layer_id) return &layer;
    }
    return nullptr;
}

void LayerManagerPanel::set_editing_layer(
    const std::optional<std::string>& layer_id) {
    if (layer_id == editing_layer_id_) return;
    editing_layer_id_ = layer_id;
    reload();
}

// -- 快照变更 ------------------------------------------------------------------

void LayerManagerPanel::set_layer_visible(const std::string& layer_id,
                                          bool visible, bool reload_tree) {
    for (auto& layer : layers_) {
        if (layer.id == layer_id) {
            layer.visible = visible;
            publish(reload_tree);
            return;
        }
    }
}

void LayerManagerPanel::set_layer_opacity(const std::string& layer_id,
                                          double opacity_value) {
    for (auto& layer : layers_) {
        if (layer.id == layer_id) {
            layer.opacity = std::max(0.05, opacity_value);
            // 不透明度不影响树呈现；只重发渲染快照（review #5 热点）。
            publish(false);
            return;
        }
    }
}

void LayerManagerPanel::move_layer(const std::string& layer_id,
                                   int direction) {
    for (size_t index = 0; index < layers_.size(); ++index) {
        if (layers_[index].id != layer_id) continue;
        const int target = static_cast<int>(index) - direction;
        if (target < 0 || target >= static_cast<int>(layers_.size())) {
            return;
        }
        std::swap(layers_[index], layers_[static_cast<size_t>(target)]);
        publish();
        return;
    }
}

void LayerManagerPanel::publish(bool reload_tree) {
    if (!canvas_.set_layer_snapshot) return;
    MapRenderSnapshot snapshot;
    // panel_publish_crs：未声明返回 ""（宿主只注入已声明 CRS）。
    snapshot.project_crs = project_crs_;
    snapshot.layers = layers_;
    canvas_.set_layer_snapshot(snapshot);
    if (reload_tree) reload();
}

// -- 树 ---------------------------------------------------------------------------

void LayerManagerPanel::reload() {
    if (tree_connected_) {
        disconnect(tree, &QTreeWidget::itemChanged, this,
                   &LayerManagerPanel::on_item_changed);
        tree_connected_ = false;
    }
    // 保持当前图层选中，避免编辑态在每次内容变更后被误重置。
    QTreeWidgetItem* current = tree->currentItem();
    const QString current_id =
        current != nullptr ? current->data(0, Qt::UserRole).toString()
                           : QString();
    // V7 §12：差分重载——结构未变只更新单元格，不清树。
    std::vector<std::string> existing_ids;
    for (int row = 0; row < tree->topLevelItemCount(); ++row) {
        existing_ids.push_back(tree->topLevelItem(row)
                                   ->data(0, Qt::UserRole)
                                   .toString()
                                   .toStdString());
    }
    std::vector<std::string> desired_ids;
    for (const MapLayerSnapshot& layer : layers_) {
        desired_ids.push_back(layer.id);
    }
    const bool differential =
        !desired_ids.empty() && existing_ids == desired_ids;
    const int scroll = tree->verticalScrollBar()->value();
    reloading_ = true;
    if (differential) {
        for (size_t row = 0; row < layers_.size(); ++row) {
            update_tree_item(tree->topLevelItem(static_cast<int>(row)),
                             layers_[row]);
        }
    } else {
        tree->clear();
        QTreeWidgetItem* restored = nullptr;
        for (const MapLayerSnapshot& layer : layers_) {
            auto* item = new QTreeWidgetItem({QString(), QString()});
            update_tree_item(item, layer);
            item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
            tree->addTopLevelItem(item);
            if (!current_id.isEmpty() &&
                layer.id == current_id.toStdString()) {
                restored = item;
            }
        }
        if (restored != nullptr) tree->setCurrentItem(restored);
    }
    // 重载只刷新按钮态（不 emit active_layer_changed）。
    on_current_changed(tree->currentItem(), nullptr);
    reloading_ = false;
    if (differential) tree->verticalScrollBar()->setValue(scroll);
    connect(tree, &QTreeWidget::itemChanged, this,
            &LayerManagerPanel::on_item_changed);
    tree_connected_ = true;
}

void LayerManagerPanel::update_tree_item(
    QTreeWidgetItem* item, const MapLayerSnapshot& layer) {
    QString label = QString::fromStdString(layer.name);
    if (is_editable_layer(layer)) {
        label = QStringLiteral("%1（矢量）").arg(label);
    }
    if (editing_layer_id_.has_value() && layer.id == *editing_layer_id_) {
        label = QStringLiteral("✏ ") + label;
    }
    item->setText(0, label);
    item->setData(0, Qt::UserRole, QString::fromStdString(layer.id));
    item->setIcon(
        0, layer_kind_icon(snapshot_geometry_kind(layer), layer.style));
    item->setCheckState(0, layer.visible ? Qt::Checked : Qt::Unchecked);
    apply_item_decoration(item, layer.id, label);
}

void LayerManagerPanel::apply_item_decoration(QTreeWidgetItem* item,
                                              const std::string& layer_id,
                                              const QString& label) {
    auto it = decorations_.find(layer_id);
    const std::optional<StateToken> token =
        it == decorations_.end() ? std::nullopt
                                 : decoration_token(it->second);
    if (!token.has_value()) {
        item->setText(1, QString());
        item->setToolTip(0, label);
        item->setToolTip(1, QString());
        item->setData(1, Qt::ForegroundRole, QVariant());
        return;
    }
    item->setText(1, QStringLiteral("%1 %2")
                         .arg(QString::fromStdString(token->glyph),
                              QString::fromStdString(token->label)));
    const std::string summary =
        it == decorations_.end() ? "" : decoration_summary_text(it->second);
    const QString tooltip =
        summary.empty()
            ? label
            : label + QStringLiteral("\n") +
                  QString::fromStdString(summary);
    item->setToolTip(0, tooltip);
    item->setToolTip(1, tooltip);
    const QColor color = decoration_color(token->tone);
    if (color.isValid()) {
        item->setData(1, Qt::ForegroundRole, color);
    }
}

void LayerManagerPanel::set_layer_decorations(
    const std::map<std::string, LayerPresentationState>& decorations) {
    decorations_ = decorations;
    if (reloading_) return;
    if (tree_connected_) {
        disconnect(tree, &QTreeWidget::itemChanged, this,
                   &LayerManagerPanel::on_item_changed);
        tree_connected_ = false;
    }
    for (int row = 0; row < tree->topLevelItemCount(); ++row) {
        QTreeWidgetItem* item = tree->topLevelItem(row);
        apply_item_decoration(
            item, item->data(0, Qt::UserRole).toString().toStdString(),
            item->text(0));
    }
    connect(tree, &QTreeWidget::itemChanged, this,
            &LayerManagerPanel::on_item_changed);
    tree_connected_ = true;
}

void LayerManagerPanel::filter(const QString& text) {
    const QString needle = text.trimmed().toLower();
    for (int row = 0; row < tree->topLevelItemCount(); ++row) {
        QTreeWidgetItem* item = tree->topLevelItem(row);
        item->setHidden(!needle.isEmpty() &&
                        !item->text(0).toLower().contains(needle));
    }
}

void LayerManagerPanel::on_item_changed(QTreeWidgetItem* item) {
    // 勾选回调绝不能同步重建树（delegate use-after-free 先例）；勾选态
    // 本就是树写的，跳过重载只重发渲染快照。
    set_layer_visible(
        item->data(0, Qt::UserRole).toString().toStdString(),
        item->checkState(0) == Qt::Checked, false);
}

void LayerManagerPanel::on_current_changed(QTreeWidgetItem* current,
                                           QTreeWidgetItem* /*previous*/) {
    sync_opacity();
    bool editable = false;
    if (current != nullptr) {
        const MapLayerSnapshot* lyr = layer_by_id(
            current->data(0, Qt::UserRole).toString().toStdString());
        editable = lyr != nullptr && is_editable_layer(*lyr);
    }
    remove_button->setEnabled(editable);
    if (!reloading_) {
        emit active_layer_changed(
            current != nullptr ? current->data(0, Qt::UserRole)
                               : QVariant());
    }
}

void LayerManagerPanel::sync_opacity() {
    QTreeWidgetItem* item = tree->currentItem();
    if (item == nullptr) return;
    const MapLayerSnapshot* lyr =
        layer_by_id(item->data(0, Qt::UserRole).toString().toStdString());
    if (lyr != nullptr) {
        opacity->blockSignals(true);
        opacity->setValue(static_cast<int>(lyr->opacity * 100));
        opacity->blockSignals(false);
    }
}

void LayerManagerPanel::apply_opacity(int value) {
    QTreeWidgetItem* item = tree->currentItem();
    if (item != nullptr) {
        set_layer_opacity(
            item->data(0, Qt::UserRole).toString().toStdString(),
            value / 100.0);
    }
}

void LayerManagerPanel::move_up() {
    QTreeWidgetItem* item = tree->currentItem();
    if (item != nullptr) {
        move_layer(item->data(0, Qt::UserRole).toString().toStdString(), +1);
    }
}

void LayerManagerPanel::move_down() {
    QTreeWidgetItem* item = tree->currentItem();
    if (item != nullptr) {
        move_layer(item->data(0, Qt::UserRole).toString().toStdString(), -1);
    }
}

// -- 上下文菜单 -----------------------------------------------------------------

void LayerManagerPanel::on_context_menu(const QPoint& position) {
    QTreeWidgetItem* item = tree->itemAt(position);
    if (item == nullptr) return;
    const std::string layer_id =
        item->data(0, Qt::UserRole).toString().toStdString();
    const MapLayerSnapshot* lyr = layer_by_id(layer_id);
    if (lyr == nullptr) return;
    const QString layer_qid = QString::fromStdString(layer_id);
    const bool editable = is_editable_layer(*lyr);
    const bool is_reference = is_reference_layer(*lyr);
    QMenu menu(tree);
    // R2-1：禁用原因直达菜单（Qt 默认不显示菜单项 tooltip）。
    menu.setToolTipsVisible(true);
    QAction* zoom = menu.addAction(
        pwb::ui_widgets::workstation_icon("map/tree-zoom.svg"),
        QStringLiteral("缩放到图层"));
    const MapExtent& extent = lyr->extent;
    const bool has_extent = extent[0] < extent[2] &&
                            extent[1] < extent[3] &&
                            !lyr->features.empty();
    zoom->setEnabled(has_extent);
    QAction* refresh = nullptr;
    QAction* toggle_snap = nullptr;
    QAction* remove_reference = nullptr;
    if (is_reference) {
        menu.addSeparator();
        refresh = menu.addAction(QStringLiteral("刷新引用（重读源文件）"));
        toggle_snap = menu.addAction(QStringLiteral("参与捕捉"));
        toggle_snap->setCheckable(true);
        toggle_snap->setChecked(meta_value(*lyr, "snap") == "true");
        remove_reference = menu.addAction(
            pwb::ui_widgets::workstation_icon("map/tree-remove.svg"),
            QStringLiteral("移除引用…"));
    }
    // V8 M2：查看/导出类动作对任意已注册图层开放；编辑类动作仍要求可
    // 编辑图层（或 RAW 保护的「复制为草稿」入口）。
    QAction* open_table = menu.addAction(
        pwb::ui_widgets::workstation_icon("map/tree-attribute-table.svg"),
        QStringLiteral("打开属性表"));
    QAction* properties = menu.addAction(
        pwb::ui_widgets::workstation_icon("map/tree-properties.svg"),
        QStringLiteral("图层属性…"));
    QAction* symbology = menu.addAction(QStringLiteral("符号系统…"));
    QAction* labeling = menu.addAction(QStringLiteral("标注…"));
    QAction* render_preset =
        menu.addAction(QStringLiteral("应用渲染预设"));
    render_preset->setToolTip(
        QStringLiteral("按图层模板/类型恢复默认符号与标注"));
    QAction* export_action = menu.addAction(QStringLiteral("导出图层…"));
    QAction* rename = nullptr;
    QAction* duplicate = nullptr;
    QAction* remove = nullptr;
    QAction* repair = nullptr;
    QAction* draft = nullptr;
    QAction* toggle_edit = nullptr;
    // V10 M5/R2-6：facts 先取——RAW 工作流入口按 facts.raw_protected 编
    // 排，不受 metadata 旗标限制。
    std::optional<LayerMenuFacts> facts;
    if (menu_probe_) facts = menu_probe_(layer_id);
    if (editable || (facts.has_value() && facts->raw_protected)) {
        menu.addSeparator();
        toggle_edit = menu.addAction(
            editing_layer_id_.has_value() && layer_id == *editing_layer_id_
                ? QStringLiteral("停止编辑（保存编辑）")
                : QStringLiteral("开始编辑"));
        if (facts.has_value() && facts->toggle_editing.has_value()) {
            const auto& verdict = *facts->toggle_editing;
            toggle_edit->setEnabled(verdict.enabled);
            if (!verdict.enabled) {
                toggle_edit->setToolTip(
                    QStringLiteral("不可用：%1")
                        .arg(QString::fromStdString(
                            verdict.disabled_reason)));
            }
        }
        menu.addSeparator();
        if (facts.has_value() && facts->raw_protected) {
            draft = menu.addAction(
                pwb::ui_widgets::workstation_icon("map/tree-add-layer.svg"),
                QStringLiteral("复制为草稿…"));
            draft->setToolTip(QStringLiteral(
                "复制本图层为可编辑草稿（RAW/模型结果不可直接编辑）"));
        }
        rename = menu.addAction(
            pwb::ui_widgets::workstation_icon("map/tree-properties.svg"),
            QStringLiteral("重命名图层…"));
        duplicate = menu.addAction(QStringLiteral("复制图层"));
        remove = menu.addAction(
            pwb::ui_widgets::workstation_icon("map/tree-remove.svg"),
            QStringLiteral("删除图层"));
        menu.addSeparator();
        repair = menu.addAction(QStringLiteral("修复无效几何…"));
        std::optional<pwb::tool_policy::ToolAvailability> repair_avail;
        if (facts.has_value() && facts->repair_geometry.has_value()) {
            repair_avail = *facts->repair_geometry;
        } else if (repair_probe_) {
            repair_avail = repair_probe_(layer_id);
        }
        repair->setEnabled(repair_avail.has_value() && repair_avail->enabled);
        if (repair_avail.has_value() && !repair_avail->enabled) {
            repair->setToolTip(QStringLiteral("不可用：%1")
                                   .arg(QString::fromStdString(
                                       repair_avail->disabled_reason)));
        }
    }
    QAction* chosen =
        menu.exec(tree->viewport()->mapToGlobal(position));
    if (chosen == nullptr) return;
    if (chosen == zoom) {
        if (canvas_.set_extent && has_extent) canvas_.set_extent(extent);
    } else if (chosen == refresh) {
        emit refresh_reference_requested(layer_qid);
    } else if (chosen == toggle_snap) {
        emit toggle_reference_snap_requested(layer_qid);
    } else if (chosen == remove_reference) {
        emit remove_reference_requested(layer_qid);
    } else if (chosen == open_table) {
        emit attribute_table_requested(layer_qid);
    } else if (chosen == toggle_edit) {
        emit toggle_editing_requested(layer_qid);
    } else if (chosen == draft) {
        emit duplicate_layer_requested(layer_qid);
    } else if (chosen == properties) {
        emit properties_requested(layer_qid);
    } else if (chosen == symbology) {
        emit symbology_requested(layer_qid);
    } else if (chosen == labeling) {
        emit labeling_requested(layer_qid);
    } else if (chosen == rename) {
        emit rename_layer_requested(layer_qid);
    } else if (chosen == duplicate) {
        emit duplicate_layer_requested(layer_qid);
    } else if (chosen == remove) {
        emit remove_layer_requested(layer_qid);
    } else if (chosen == repair) {
        emit repair_layer_requested(layer_qid);
    } else if (chosen == export_action) {
        emit export_layer_requested(layer_qid);
    } else if (chosen == render_preset) {
        emit render_preset_requested(layer_qid);
    }
}

// ---------------------------------------------------------------------------
// InputTreePanel
// ---------------------------------------------------------------------------

InputTreePanel::InputTreePanel(QWidget* parent) : QFrame(parent) {
    setObjectName("PanelCard");
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(6);
    tree = new QTreeWidget(this);
    tree->setHeaderHidden(true);
    connect(tree, &QTreeWidget::currentItemChanged, this,
            [this](QTreeWidgetItem* current, QTreeWidgetItem*) {
                if (current == nullptr) return;
                const QVariant payload = current->data(0, Qt::UserRole);
                if (payload.isValid()) {
                    emit object_selected(payload.toMap());
                }
            });
    outer->addWidget(tree, 1);
}

void InputTreePanel::refresh(const std::vector<std::string>& wells,
                             const std::vector<std::string>& seismic,
                             const std::vector<std::string>& maps) {
    tree->clear();
    const struct {
        QString kind;
        const std::vector<std::string>* names;
    } groups[] = {
        {QStringLiteral("well"), &wells},
        {QStringLiteral("seismic"), &seismic},
        {QStringLiteral("map"), &maps},
    };
    const QString titles[] = {QStringLiteral("井数据 (%1)"),
                              QStringLiteral("地震数据 (%1)"),
                              QStringLiteral("图件成果 (%1)")};
    for (int i = 0; i < 3; ++i) {
        auto* group = new QTreeWidgetItem(
            {titles[i].arg(groups[i].names->size())});
        tree->addTopLevelItem(group);
        for (const std::string& name : *groups[i].names) {
            auto* leaf =
                new QTreeWidgetItem({QString::fromStdString(name)});
            leaf->setData(
                0, Qt::UserRole,
                QVariantMap{{"kind", groups[i].kind},
                            {"name", QString::fromStdString(name)}});
            group->addChild(leaf);
        }
        group->setExpanded(true);
    }
}

// ---------------------------------------------------------------------------
// LinkedViewsPanel
// ---------------------------------------------------------------------------

LinkedViewsPanel::LinkedViewsPanel(QWidget* parent) : QFrame(parent) {
    setObjectName("PanelCard");
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    auto* label = new QLabel(
        QStringLiteral(
            "联动视图（测井轨道 / 地震剖面）将在选择井位后于此加载。"),
        this);
    label->setWordWrap(true);
    label->setObjectName("WorkstationPanelFootnote");
    layout->addWidget(label);
    layout->addStretch(1);
}

}  // namespace pwb::ui_composite
