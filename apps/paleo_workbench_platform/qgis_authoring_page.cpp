// qgis_authoring_page — see the header for the composition contract.

#include "qgis_authoring_page.hpp"

#include <QDockWidget>
#include <QVBoxLayout>

#include <qgsmessagebar.h>

namespace pwb::app {

QgisAuthoringPage::QgisAuthoringPage(QWidget* parent) : QMainWindow(parent) {
    setObjectName(QStringLiteral("QgisAuthoringPage"));
    // 内嵌图窗不需要自己的菜单/状态条 —— 菜单与状态条归外层壳。
    setDockNestingEnabled(true);
    setTabPosition(Qt::AllDockWidgetAreas, QTabWidget::North);

    // QgisApp 中央组成：消息条贴画布上缘（qgisapp.cpp 的
    // mInfoBar 做法），画布占满剩余空间。
    auto* central = new QWidget(this);
    auto* layout = new QVBoxLayout(central);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    message_bar_ = new QgsMessageBar(central);
    message_bar_->setSizePolicy(QSizePolicy::Minimum, QSizePolicy::Fixed);
    layout->addWidget(message_bar_);
    canvas_slot_ = new QWidget(central);
    canvas_slot_->setObjectName(QStringLiteral("AuthoringCanvasSlot"));
    auto* slot_layout = new QVBoxLayout(canvas_slot_);
    slot_layout->setContentsMargins(0, 0, 0, 0);
    slot_layout->setSpacing(0);
    layout->addWidget(canvas_slot_, 1);
    setCentralWidget(central);
}

void QgisAuthoringPage::set_canvas(QWidget* canvas) {
    if (canvas == canvas_) return;
    if (canvas_ != nullptr) {
        canvas_->setParent(nullptr);
    }
    canvas_ = canvas;
    if (canvas_ != nullptr) {
        canvas_->setParent(canvas_slot_);
        canvas_slot_->layout()->addWidget(canvas_);
        canvas_->show();
    }
}

void QgisAuthoringPage::adopt_dock(QDockWidget* dock,
                                   Qt::DockWidgetArea area,
                                   QDockWidget* tabify_on) {
    if (dock == nullptr) return;
    addDockWidget(area, dock);  // reparents into this page's dock host
    dock->show();
    if (tabify_on != nullptr) {
        tabifyDockWidget(tabify_on, dock);
        tabify_on->raise();
    }
}

}  // namespace pwb::app
