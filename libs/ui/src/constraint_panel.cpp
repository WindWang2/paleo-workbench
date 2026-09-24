#include <pwb/ui/constraint_panel.hpp>

#include <QHeaderView>
#include <QTreeWidget>
#include <QTreeWidgetItem>

#include <qgslayertree.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/tool_policy/layer_roles.hpp>

namespace pwb::ui {
namespace {

// stage_profiles.py active_editing_roles of the constraint stage: every
// role a constraint-stage editor may target.
bool is_constraint_role(const std::string& role) {
    using namespace pwb::tool_policy::layer_role;
    return role == kProvenanceLine || role == kProvenanceDirection
        || role == kDistributionLine || role == kPaleoShoreline
        || role == kFaciesBoundary || role == kFaultConstraint
        || role == kMaskBoundary || role == kInterpolationBoundary;
}

// Chinese caption per constraint role (constraint_kinds vocabulary).
QString constraint_role_caption(const std::string& role) {
    using namespace pwb::tool_policy::layer_role;
    if (role == kProvenanceLine) return QObject::tr("物源线");
    if (role == kProvenanceDirection) return QObject::tr("物源方向");
    if (role == kDistributionLine) return QObject::tr("展布线");
    if (role == kPaleoShoreline) return QObject::tr("岸线");
    if (role == kFaciesBoundary) return QObject::tr("相带边界");
    if (role == kFaultConstraint) return QObject::tr("断层约束");
    if (role == kMaskBoundary) return QObject::tr("掩膜边界");
    if (role == kInterpolationBoundary) return QObject::tr("插值边界");
    return QString::fromStdString(role);
}

}  // namespace

ConstraintPanel::ConstraintPanel(const FactsProvider& facts_provider,
                                 QWidget* parent)
    : QDockWidget(parent), facts_provider_(facts_provider) {
    setObjectName(QStringLiteral("constraint-dock"));
    setWindowTitle(QObject::tr("地质约束"));

    tree_ = new QTreeWidget(this);
    tree_->setColumnCount(2);
    tree_->setHeaderLabels({QObject::tr("约束图层"), QObject::tr("要素")});
    tree_->header()->setStretchLastSection(false);
    tree_->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    tree_->setRootIsDecorated(false);
    connect(tree_, &QTreeWidget::itemActivated, this,
            &ConstraintPanel::on_row_activated);
    connect(tree_, &QTreeWidget::itemClicked, this,
            [this](QTreeWidgetItem* item, int column) {
                on_row_activated(item, column);
            });
    connect(tree_, &QTreeWidget::itemChanged, this,
            [this](QTreeWidgetItem* item, int column) {
                if (syncing_checks_ || item == nullptr || column != 0) {
                    return;
                }
                const QString layer_id =
                    item->data(0, Qt::UserRole).toString();
                if (layer_id.isEmpty()) return;
                emit visibility_requested(
                    layer_id, item->checkState(0) == Qt::Checked);
            });
    setWidget(tree_);
}

void ConstraintPanel::refresh(pwb::application::ProjectSession& session) {
    syncing_checks_ = true;
    tree_->clear();
    const auto active = session.active_layer();
    for (const std::string& layer_id : session.map().layerIdsTopFirst()) {
        // Facts come from the host provider (same authority the layer tree
        // tooltips read); the active layer's facts are the fallback so the
        // panel stays useful in minimal hosts.
        std::optional<pwb::application::DomainLayerFacts> facts;
        if (facts_provider_) facts = facts_provider_(layer_id);
        if (!facts.has_value() && active.has_value()
            && active->layer_id == layer_id) {
            facts = active;
        }
        const std::string role =
            facts.has_value() && !facts->role.empty()
                ? facts->role
                : std::string(pwb::tool_policy::layer_role::kFaciesBoundary);
        if (!is_constraint_role(role)) continue;
        QgsVectorLayer* layer = session.map().vectorLayerById(layer_id);
        const long long count =
            layer != nullptr ? static_cast<long long>(layer->featureCount())
                             : 0;
        auto* row = new QTreeWidgetItem(tree_);
        const QString label = facts.has_value() && !facts->role_label.empty()
            ? QString::fromStdString(facts->role_label)
            : constraint_role_caption(role);
        row->setText(0, label);
        row->setText(1, QString::number(count));
        row->setData(0, Qt::UserRole,
                     QString::fromStdString(layer_id));
        row->setToolTip(0, QString::fromStdString(layer_id));
        // 稿式约束要素勾选 = 图层树可见性（读 QgsLayerTree 真状态，
        // 无图层树节点时按可见处理）。
        row->setFlags(row->flags() | Qt::ItemIsUserCheckable);
        bool visible = true;
        if (auto* project = session.map().project()) {
            if (auto* node = project->layerTreeRoot()->findLayer(
                    QString::fromStdString(layer_id))) {
                visible = node->itemVisibilityChecked();
            }
        }
        row->setCheckState(0, visible ? Qt::Checked : Qt::Unchecked);
        if (active.has_value() && active->layer_id == layer_id) {
            row->setSelected(true);
        }
    }
    syncing_checks_ = false;
}

QStringList ConstraintPanel::constraint_rows() const {
    QStringList rows;
    const int count = static_cast<int>(tree_->topLevelItemCount());
    for (int i = 0; i < count; ++i) {
        const QTreeWidgetItem* item = tree_->topLevelItem(i);
        if (item == nullptr) continue;
        rows.append(item->text(0) + QStringLiteral("|")
                    + item->text(1));
    }
    return rows;
}

void ConstraintPanel::on_row_activated(QTreeWidgetItem* item, int column) {
    (void)column;
    if (item == nullptr) return;
    const QString layer_id = item->data(0, Qt::UserRole).toString();
    if (!layer_id.isEmpty()) emit activate_layer_requested(layer_id);
}

}  // namespace pwb::ui
