#pragma once

// Port of paleo_workbench/ui/pages/summary_table_preview_widget.py (UI-07):
// two tabs — "曲线定义与元数据" (stat chips + metadata/detail tables split
// by a draggable splitter) and "数据内容" (optional data table). Chips
// derive from the summary rows via the Qt-free summary_chip_values.

#include <QString>
#include <QWidget>
#include <utility>
#include <vector>

class QHBoxLayout;
class QLabel;
class QSplitter;
class QTabWidget;
class QVBoxLayout;

#include <pwb/ui_pages_preview/qt/table_preview_widget.hpp>

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class SummaryTablePreviewWidget : public QWidget {
    Q_OBJECT
public:
    explicit SummaryTablePreviewWidget(QWidget* parent = nullptr);

    // load_summary(summary_rows, detail_headers, detail_rows, message,
    //              data_headers, data_rows)
    void load_summary(
        const std::vector<std::pair<std::string, std::string>>& summary_rows,
        const std::vector<std::string>& detail_headers,
        const std::vector<std::vector<std::string>>& detail_rows,
        const QString& message = QString(),
        const std::vector<std::string>& data_headers = {},
        const std::vector<std::vector<std::string>>& data_rows = {});

    void apply_settings(const PreviewSettings& settings);

    QLabel* message_label() const { return message_label_; }
    QTabWidget* tabs() const { return tabs_; }
    TablePreviewWidget* summary_table() const { return summary_table_; }
    TablePreviewWidget* detail_table() const { return detail_table_; }
    TablePreviewWidget* data_table() const { return data_table_; }

private:
    // _create_stat_chip: bordered box with title + value label
    // ("chip_val" object name preserved for findChild parity).
    QWidget* create_stat_chip(const QString& title, const QString& default_val,
                              const QString& fg_token, const QString& bg_token);
    void update_chip_val(QWidget* chip, const QString& text);
    void adjust_summary_height();

    QLabel* message_label_ = nullptr;
    QTabWidget* tabs_ = nullptr;
    QWidget* info_tab_ = nullptr;
    QWidget* stat_bar_ = nullptr;
    QWidget* chip_well_ = nullptr;
    QWidget* chip_curves_ = nullptr;
    QWidget* chip_samples_ = nullptr;
    TablePreviewWidget* summary_table_ = nullptr;
    TablePreviewWidget* detail_table_ = nullptr;
    QSplitter* info_splitter_ = nullptr;
    QWidget* data_tab_ = nullptr;
    TablePreviewWidget* data_table_ = nullptr;
};

}  // namespace pwb::ui_pages_preview
