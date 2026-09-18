#pragma once

// FactorStatsDock — read-only HUD over pwb::mapping::GridStatistics
// (FactorGrid.statistics). First cluster of the conv-16 UI panel inventory:
// the C++ counterpart of the workstation's factor-grid summary rows
// (inspector.show_factor's grid rows and shell._factor_grid_summary),
// rendered as dock labels: 取值范围 "min ~ max", 均值, 标准差,
// 有效格元 "valid / total". Non-finite summary values render as "—" exactly
// like the Python dash fallback for an all-nodata grid.

#include <QDockWidget>
#include <map>
#include <QString>

#include <pwb/mapping/interpolator.hpp>

class QLabel;

namespace pwb::app {

class FactorStatsDock : public QDockWidget {
    Q_OBJECT
public:
    explicit FactorStatsDock(QWidget* parent = nullptr);

    // Renders one factor grid's statistics. Rows: 因素 / 取值范围 / 均值 /
    // 标准差 / 有效格元. Formatting is "%.6g" (Python's :g).
    void setStatistics(const QString& factor_name,
                       const pwb::mapping::GridStatistics& stats);

    // Readback for tests: the current text of one row ("因素", "取值范围",
    // "均值", "标准差", "有效格元"); "" for an unknown key.
    QString rowValue(const QString& key) const;

private:
    QLabel* factor_label_ = nullptr;
    QLabel* range_label_ = nullptr;
    QLabel* mean_label_ = nullptr;
    QLabel* std_label_ = nullptr;
    QLabel* valid_label_ = nullptr;
    std::map<QString, QLabel*> rows_;
};

}  // namespace pwb::app
