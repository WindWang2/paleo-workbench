#pragma once

// Port of paleo_workbench/ui/pages/json_tree_preview_widget.py (UI-07):
// collapsible QTreeView over parsed JSON/GeoJSON with lazy batched
// materialization — containers larger than the collapse threshold populate
// children only on expansion, in _EXPAND_BATCH chunks behind a sentinel row.

#include <QStandardItemModel>
#include <QTreeView>
#include <deque>
#include <memory>

#include <pwb/ui_pages_preview/json_tree_spec.hpp>

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class JsonTreePreviewWidget : public QTreeView {
    Q_OBJECT
public:
    explicit JsonTreePreviewWidget(QWidget* parent = nullptr);

    void apply_settings(const PreviewSettings& settings);
    void load_payload(const domain::Json& payload, bool truncated = false);

private:
    static constexpr int ROLE_CONTAINER = Qt::UserRole;      // lazy pool index
    static constexpr int ROLE_MORE = Qt::UserRole + 1;       // sentinel pool index

    void append_rows(QStandardItem* parent,
                     const std::vector<JsonNode>& nodes);
    void on_expanded(const QModelIndex& index);
    void expand_initial_depth();

    QStandardItemModel model_;
    // Owning pool for lazy containers/sentinels — std::deque keeps element
    // addresses stable as batches push more nodes in.
    std::deque<std::unique_ptr<JsonNode>> lazy_nodes_;
    domain::Json payload_;
    bool truncated_ = false;
    int array_collapse_threshold_ = 100;
    int expand_depth_ = 2;
};

}  // namespace pwb::ui_pages_preview
