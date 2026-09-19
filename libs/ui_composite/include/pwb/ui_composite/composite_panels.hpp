#pragma once

// Port of paleo_workbench/ui/workstation/composite_panels.py (UI-13).
// 综合编修辅助面板：识别结果 + 捕捉设置。
//
// 识别结果面板承载多图层 Identify（QGIS Identify Results 语义）；捕捉
// 设置对话框是 per-layer 配置模型。两者都只是视图——权威状态在
// CompositeEditController 与 SnappingService。

#include <map>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/geometry.hpp>
#include <pwb/ui_composite/snapping_profiles.hpp>

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDoubleSpinBox>
#include <QFrame>
#include <QLabel>
#include <QSpinBox>
#include <QTableWidget>
#include <QTreeWidget>
#include <QVariantMap>

namespace pwb::ui_composite {

using pwb::domain::Json;

class CompositeEditController;

// 多图层识别结果（点击结果 → 宿主定位 / 选中 / 缩放）。
class IdentifyResultsPanel : public QFrame {
    Q_OBJECT
public:
    explicit IdentifyResultsPanel(QWidget* parent = nullptr);

    void set_results(const std::vector<Json>& results);

    QTreeWidget* tree = nullptr;

signals:
    void result_activated(const QVariantMap& result);

private:
    void on_item_double_clicked(QTreeWidgetItem* item, int column);
};

// 捕捉设置：全局开关/容差/模式 + 每图层 enable·vertex·segment·容差·
// 优先级。容差语义为像素；井位参考点捕捉把基础工区井点作为
// reference 候选（只在勾选时生效）。
class SnappingSettingsDialog : public QDialog {
    Q_OBJECT
public:
    SnappingSettingsDialog(
        CompositeEditController* controller, QWidget* parent = nullptr,
        const std::vector<MapPoint>& well_points = {});

    void accept() override;

private:
    // Boolean cell proxy over a checkable QTableWidgetItem (V6 scalability:
    // item-based rows — no per-cell widgets).
    struct CheckCell {
        QTableWidgetItem* item = nullptr;
        void set_checked(bool checked);
        bool is_checked() const;
    };
    // Numeric cell proxy: text parsed on read, invalid reads as 0;
    // zero_label mirrors the spinbox special-value text.
    struct NumericCell {
        QTableWidgetItem* item = nullptr;
        double maximum = 0.0;
        int decimals = 1;
        QString zero_label;
        double value() const;
        void set_value(double value);
    };
    struct LayerRow {
        CheckCell enabled;
        CheckCell vertex;
        CheckCell segment;
        NumericCell tolerance;
        NumericCell priority;
    };

    void populate_layers();
    void show_row_menu(const QPoint& position);
    const SnappingProfile* role_profile(const std::string& layer_id) const;
    void apply_role_profile_to_row(const std::string& layer_id);

    CompositeEditController* controller_ = nullptr;
    std::vector<MapPoint> well_points_;
    // Insertion-ordered rows (Python dict order parity for rowAt lookup).
    std::vector<std::pair<std::string, LayerRow>> layer_rows_;

    QCheckBox* global_enable_ = nullptr;
    QComboBox* units_combo_ = nullptr;
    QSpinBox* scale_spin_ = nullptr;
    QDoubleSpinBox* global_tolerance_ = nullptr;
    std::map<std::string, QCheckBox*> mode_boxes_;
    QComboBox* scope_combo_ = nullptr;
    QTableWidget* table_ = nullptr;
    QLabel* hint_ = nullptr;
    QCheckBox* well_snap_ = nullptr;
};

}  // namespace pwb::ui_composite
