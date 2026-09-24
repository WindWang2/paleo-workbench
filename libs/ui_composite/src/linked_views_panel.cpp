#include <pwb/ui_composite/linked_views_panel.hpp>

#include <QLabel>
#include <QVBoxLayout>

namespace pwb::ui_composite {

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
