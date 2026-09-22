#include <pwb/ui/layer_tree_panel.hpp>

#include <algorithm>

#include <QAbstractItemView>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QPainter>
#include <QSignalBlocker>
#include <QSlider>
#include <QToolBar>
#include <QVBoxLayout>

#include <qgslayertree.h>
#include <qgslayertreemodel.h>
#include <qgslayertreeview.h>
#include <qgslayertreeviewdefaultactions.h>
#include <qgslayertreeviewindicator.h>
#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgslayermetadata.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/map_session.hpp>

namespace pwb::ui {
namespace {

QIcon editing_indicator_icon() {
    // Pencil glyph, standard editing marker in mapping UIs.
    QIcon icon;
    QPixmap pixmap(16, 16);
    pixmap.fill(Qt::transparent);
    QPainter painter(&pixmap);
    painter.setPen(QPen(QColor(0x2a, 0x6f, 0xd4), 2));
    painter.drawLine(3, 12, 3, 15);
    painter.drawLine(3, 15, 6, 15);
    painter.drawLine(4, 12, 12, 4);
    painter.drawLine(12, 4, 14, 6);
    painter.drawLine(6, 14, 14, 6);
    painter.end();
    icon.addPixmap(pixmap);
    return icon;
}

}  // namespace

LayerTreePanel::LayerTreePanel(pwb::qgis::MapSession& session,
                               QgsMapCanvas* canvas,
                               const FactsProvider& facts_provider,
                               QWidget* parent)
    : QWidget(parent), session_(session), canvas_(canvas),
      facts_provider_(facts_provider) {
    setObjectName(QStringLiteral("layer-tree-panel"));
    view_ = session_.createLayerTree(this);
    default_actions_ = new QgsLayerTreeViewDefaultActions(view_);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(6);

    auto* header = new QHBoxLayout;
    auto* title = new QLabel(tr("图层"), this);
    title->setObjectName(QStringLiteral("LayerTreeTitle"));
    header->addWidget(title);
    header->addStretch(1);
    toolbar_ = new QToolBar(this);
    toolbar_->setObjectName(QStringLiteral("LayerTreeToolBar"));
    toolbar_->setMovable(false);
    toolbar_->setFloatable(false);
    toolbar_->setIconSize(QSize(16, 16));
    toolbar_->setToolButtonStyle(Qt::ToolButtonIconOnly);
    toolbar_->addAction(default_actions_->actionAddGroup(toolbar_));
    toolbar_->addAction(default_actions_->actionMoveToTop(toolbar_));
    toolbar_->addAction(default_actions_->actionMoveToBottom(toolbar_));
    toolbar_->addSeparator();
    toolbar_->addAction(default_actions_->actionRemoveGroupOrLayer(toolbar_));
    header->addWidget(toolbar_);
    layout->addLayout(header);

    auto* filter = new QLineEdit(this);
    filter->setObjectName(QStringLiteral("LayerTreeFilter"));
    filter->setClearButtonEnabled(true);
    filter->setPlaceholderText(tr("按名称筛选图层"));
    filter->setAccessibleName(tr("筛选图层"));
    connect(filter, &QLineEdit::textChanged, this,
            [this](const QString& text) {
                if (view_->proxyModel() != nullptr) {
                    view_->proxyModel()->setFilterText(text);
                }
            });
    layout->addWidget(filter);

    view_->setObjectName(QStringLiteral("QgisLayerTreeView"));
    view_->setHeaderHidden(true);
    view_->setAlternatingRowColors(true);
    view_->setUniformRowHeights(false);
    view_->setDragEnabled(true);
    view_->setAcceptDrops(true);
    view_->setDropIndicatorShown(true);
    view_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    view_->setAccessibleName(tr("QGIS 图层树"));
    layout->addWidget(view_, 1);

    auto* opacity_row = new QHBoxLayout;
    auto* opacity_label = new QLabel(tr("不透明度"), this);
    opacity_label->setObjectName(QStringLiteral("LayerOpacityLabel"));
    opacity_row->addWidget(opacity_label);
    opacity_ = new QSlider(Qt::Horizontal, this);
    opacity_->setObjectName(QStringLiteral("LayerOpacity"));
    opacity_->setRange(0, 100);
    opacity_->setValue(100);
    opacity_->setEnabled(false);
    opacity_->setAccessibleName(tr("当前图层不透明度"));
    connect(opacity_, &QSlider::valueChanged, this, [this](int value) {
        QgsMapLayer* layer = view_->currentLayer();
        if (layer == nullptr) return;
        layer->setOpacity(static_cast<double>(value) / 100.0);
        layer->triggerRepaint();
        if (canvas_ != nullptr) canvas_->refresh();
    });
    opacity_row->addWidget(opacity_, 1);
    layout->addLayout(opacity_row);

    // Tree selection -> domain active layer (join key authority; groups and
    // reorders cannot desync the mapping).
    connect(view_, &QgsLayerTreeView::currentLayerChanged, this,
            &LayerTreePanel::on_current_layer_changed);

    // Native per-view context menu policy; the menu mixes QGIS default
    // actions with domain actions.
    view_->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(view_, &QgsLayerTreeView::customContextMenuRequested, this,
            [this](const QPoint& pos) {
                build_context_menu(view_->viewport()->mapToGlobal(pos));
            });
}

void LayerTreePanel::on_current_layer_changed(QgsMapLayer* layer) {
    sync_opacity_control(layer);
    if (layer == nullptr) {
        emit active_layer_changed(QString());
        return;
    }
    emit active_layer_changed(QString::fromStdString(
        pwb::qgis::layer_adapter::layer_id_of(layer)));
}

void LayerTreePanel::sync_opacity_control(QgsMapLayer* layer) {
    const QSignalBlocker blocker(opacity_);
    opacity_->setEnabled(layer != nullptr);
    opacity_->setValue(
        layer == nullptr ? 100
                         : qRound(std::clamp(layer->opacity(), 0.0, 1.0) *
                                  100.0));
}

void LayerTreePanel::set_active_layer(const std::string& layer_id) {
    QgsMapLayer* layer = session_.layerById(layer_id);
    if (layer == nullptr) return;
    if (view_->currentLayer() == layer) return;
    view_->setCurrentLayer(layer);
}

void LayerTreePanel::refresh_indicators() {
    // Drop stale indicators first (removed layers, stopped edits).
    for (const auto& [layer_id, indicator] : edit_indicators_) {
        (void)layer_id;
        QgsMapLayer* layer = session_.layerById(layer_id);
        QgsLayerTreeNode* node = layer == nullptr
            ? nullptr
            : session_.project()->layerTreeRoot()->findLayer(layer);
        if (node != nullptr && indicator != nullptr) {
            view_->removeIndicator(node, indicator);
        }
        // Even when the node is gone, deleting the indicator lets the
        // view's bookkeeping release it (no dangling entries accumulate).
        if (indicator != nullptr) {
            indicator->deleteLater();
        }
    }
    edit_indicators_.clear();

    const QMap<QString, QgsMapLayer*> layers =
        session_.project()->mapLayers();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        QgsMapLayer* layer = it.value();
        if (layer == nullptr) continue;
        const std::string layer_id =
            pwb::qgis::layer_adapter::layer_id_of(layer);
        QgsLayerTreeNode* node =
            session_.project()->layerTreeRoot()->findLayer(layer);
        if (node == nullptr) continue;   // not in the tree (yet)

        // Facts display rides the native metadata channel: the tree view's
        // tooltip already renders metadata title/abstract, so the role/
        // maturity/lock facts go there (persisted with the layer, QGIS
        // conventions — no custom model delegate).
        QString facts_abstract;
        if (facts_provider_) {
            const auto facts = facts_provider_(layer_id);
            if (facts.has_value()) {
                QStringList lines;
                if (!facts->artifact_maturity.empty()) {
                    lines.append(QObject::tr("成熟度：%1").arg(
                        QString::fromStdString(facts->artifact_maturity)));
                }
                if (facts->frozen) lines.append(QObject::tr("已冻结（只读）"));
                if (facts->raw_locked) lines.append(QObject::tr("RAW 锁定"));
                if (facts->write_granted) lines.append(QObject::tr("可编辑"));
                // BEGIN V14-QGIS-CONTROL
                // Layer control-plane projection (contracts 03 §9): the
                // stable flag vocabulary rides the same metadata channel.
                if (!facts->status_summary.empty()) {
                    lines.append(QString::fromStdString(facts->status_summary));
                }
                // END V14-QGIS-CONTROL
                facts_abstract = lines.join(QStringLiteral("\n"));
            }
        }
        auto* vector_layer = qobject_cast<QgsVectorLayer*>(layer);
        if (vector_layer != nullptr && vector_layer->isEditable()) {
            auto* indicator = new QgsLayerTreeViewIndicator(this);
            indicator->setIcon(editing_indicator_icon());
            indicator->setToolTip(
                vector_layer->isModified()
                    ? QObject::tr("编辑中（有未提交修改）")
                    : QObject::tr("编辑中"));
            view_->addIndicator(node, indicator);
            edit_indicators_[layer_id] = indicator;
        }
        if (!facts_abstract.isEmpty()
            && layer->metadata().abstract() != facts_abstract) {
            QgsLayerMetadata metadata = layer->metadata();
            metadata.setAbstract(facts_abstract);
            layer->setMetadata(metadata);
        }
    }
}

std::vector<std::string> LayerTreePanel::editing_indicated_layer_ids() const {
    // Tree order (header contract), not map-key order.
    std::vector<std::string> ids;
    for (const std::string& layer_id : session_.layerIdsTopFirst()) {
        if (edit_indicators_.count(layer_id) > 0) ids.push_back(layer_id);
    }
    return ids;
}

void LayerTreePanel::build_context_menu(const QPoint& global_pos) {
    QMenu menu;
    QgsLayerTreeNode* node = view_->currentNode();
    QgsMapLayer* layer = view_->currentLayer();
    const bool has_node = node != nullptr;

    if (layer != nullptr) {
        menu.addAction(QObject::tr("图层属性…"), this, [this, layer]() {
            emit layer_properties_requested(QString::fromStdString(
                pwb::qgis::layer_adapter::layer_id_of(layer)));
        });
        menu.addSeparator();
    }
    // QGIS 4 exposes the default tree operations as action factories; the
    // menu parents them so they die with the menu.
    if (has_node && canvas_ != nullptr) {
        menu.addAction(default_actions_->actionZoomToLayers(canvas_, &menu));
    }
    menu.addAction(default_actions_->actionAddGroup(&menu));
    if (has_node) {
        menu.addAction(default_actions_->actionRenameGroupOrLayer(&menu));
        menu.addSeparator();
        menu.addAction(default_actions_->actionMoveToTop(&menu));
        menu.addAction(default_actions_->actionMoveToBottom(&menu));
        menu.addSeparator();
        menu.addAction(default_actions_->actionRemoveGroupOrLayer(&menu));
    }
    menu.exec(global_pos);
}

}  // namespace pwb::ui
