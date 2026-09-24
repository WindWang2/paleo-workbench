#pragma once

// 输入与结果树：编修输入（井 / 地震）与成果（图件文档）的真实清单；
// 选中仅发布 payload。（原与 LayerManagerPanel 同文件；后者随 QGIS
// 原生图层树收敛退役后，本面板独立成文件。）

#include <string>
#include <vector>

#include <QFrame>
#include <QVariant>

class QTreeWidget;

namespace pwb::ui_composite {

class InputTreePanel : public QFrame {
    Q_OBJECT
public:
    explicit InputTreePanel(QWidget* parent = nullptr);

    // 工程只读投影（wells/seismic/maps 名称清单）。
    void refresh(const std::vector<std::string>& wells,
                 const std::vector<std::string>& seismic,
                 const std::vector<std::string>& maps);

    QTreeWidget* tree = nullptr;

signals:
    void object_selected(const QVariantMap& payload);
};

}  // namespace pwb::ui_composite
