#pragma once

// 联动视图面板：与图件选择联动的测井/地震视图（诚实空态）。（原与
// LayerManagerPanel 同文件；后者随 QGIS 原生图层树收敛退役后，本面板
// 独立成文件。）

#include <QFrame>

namespace pwb::ui_composite {

class LinkedViewsPanel : public QFrame {
    Q_OBJECT
public:
    explicit LinkedViewsPanel(QWidget* parent = nullptr);
};

}  // namespace pwb::ui_composite
