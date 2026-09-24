#include <pwb/ui_composite/input_tree_panel.hpp>

#include <QTreeWidget>
#include <QVBoxLayout>

namespace pwb::ui_composite {

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

}  // namespace pwb::ui_composite
