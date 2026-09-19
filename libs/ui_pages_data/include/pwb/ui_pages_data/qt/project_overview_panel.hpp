// UI-06 — project_overview_panel.py :: ProjectOverviewPanel Qt shell.
//
// Identity header + 8 stat blocks + hint lines; the shared well-map panel
// is installed via set_map_widget. Display math lives in overview.hpp.
#pragma once

#include <QWidget>

#include <map>
#include <string>

#include <pwb/ui_pages_data/filter_query.hpp>
#include <pwb/ui_pages_data/overview.hpp>

class QLabel;

namespace pwb::ui_pages_data::qt {

class ProjectOverviewPanel : public QWidget {
    Q_OBJECT
public:
    explicit ProjectOverviewPanel(QWidget* parent = nullptr);

    // Install the shared well-map panel as the overview main content.
    void set_map_widget(QWidget* widget);
    // Re-render from the document (no IO). project=nullptr → "未打开工程".
    void refresh_from_project(const OverviewProject* project,
                              const CatalogCounts* counts);

    QLabel* title_label() { return title_label_; }
    QLabel* meta_label() { return meta_label_; }
    QLabel* hint_label() { return hint_label_; }

private:
    QLabel* title_label_;
    QLabel* meta_label_;
    QLabel* hint_label_;
    std::map<std::string, QLabel*> values_;
};

}  // namespace pwb::ui_pages_data::qt
