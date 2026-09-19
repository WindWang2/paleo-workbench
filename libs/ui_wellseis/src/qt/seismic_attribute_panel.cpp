#include <pwb/ui_wellseis/qt/seismic_attribute_panel.hpp>

#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVBoxLayout>
#include <QLabel>

#include <pwb/ui_wellseis/seismic_attributes.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

const QString& unimplemented_group_label() {
    static const QString label = QStringLiteral("未实现");
    return label;
}

}  // namespace

SeismicAttributePanel::SeismicAttributePanel(
    QWidget* parent,
    std::function<bool(const std::string& kernel_id)> computable_probe)
    : QFrame(parent),
      computable_probe_(std::move(computable_probe)) {
    setObjectName(QStringLiteral("SeismicAttributePanel"));
    setMinimumWidth(200);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(4);

    auto* title = new QLabel(QStringLiteral("地震属性"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    tree_ = new QTreeWidget(this);
    tree_->setObjectName(QStringLiteral("SeismicAttributeTree"));
    tree_->setHeaderHidden(true);
    populate();
    tree_->expandAll();
    connect(tree_, &QTreeWidget::itemClicked, this,
            [this](QTreeWidgetItem* item, int) {
                if (item == nullptr || !(item->flags() & Qt::ItemIsEnabled) ||
                    item->childCount() > 0) {
                    return;
                }
                if (!suppress_) {
                    emit attribute_changed(item->text(0));
                }
            });
    layout->addWidget(tree_, 1);
}

bool SeismicAttributePanel::enabled_leaf(const QString& label) const {
    const std::string kernel = kernel_for_label(label.toStdString());
    if (kernel.empty()) {
        return false;  // 未实现 leaf (or unknown label) — never selectable.
    }
    if (!computable_probe_) {
        return true;
    }
    return computable_probe_(kernel);
}

void SeismicAttributePanel::populate() {
    tree_->clear();
    for (const SeismicAttributeGroup& group :
         seismic_attribute_panel_groups()) {
        auto* group_item = new QTreeWidgetItem(tree_, {qs(group.group_label)});
        group_item->setFlags(Qt::ItemIsEnabled);
        for (const std::string& label : group.attributes) {
            auto* leaf = new QTreeWidgetItem(group_item, {qs(label)});
            const bool enabled = enabled_leaf(qs(label));
            leaf->setFlags(enabled ? Qt::ItemIsEnabled | Qt::ItemIsSelectable
                                   : Qt::NoItemFlags);
            if (!enabled) {
                leaf->setForeground(
                    0, tree_->palette().color(QPalette::Disabled,
                                              QPalette::Text));
                if (group.group_label == "未实现") {
                    leaf->setToolTip(0, QStringLiteral("尚未实现的参考标签"));
                }
            }
        }
    }
}

void SeismicAttributePanel::set_selected_attribute(const QString& label) {
    suppress_ = true;
    const auto items = tree_->findItems(
        label, Qt::MatchExactly | Qt::MatchRecursive);
    for (QTreeWidgetItem* item : items) {
        // Leaf-only, like the Python child scan.
        if (item != nullptr && item->childCount() == 0) {
            tree_->setCurrentItem(item);
            break;
        }
    }
    suppress_ = false;
}

QString SeismicAttributePanel::selected_attribute() const {
    QTreeWidgetItem* item = tree_->currentItem();
    if (item != nullptr && item->childCount() == 0) {
        return item->text(0);
    }
    // Python default: `return "振幅"` when no leaf is current.
    return QStringLiteral("振幅");
}

}  // namespace pwb::ui_wellseis::qt
