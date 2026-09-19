#pragma once

// UI-05 — MapDocumentPanel (map_document_panel.py): the left-hand read-only
// summary of available paleogeographic map documents (current map name,
// target horizon, facies polygon count, well overlay count, document list
// with keyed reconciliation).

#include <string>
#include <vector>

#include <QFrame>

#include <pwb/ui_map/map_chrome_core.hpp>

class QLabel;
class QListWidget;

namespace pwb::ui_map {

class MapDocumentPanel : public QFrame {
    Q_OBJECT
public:
    explicit MapDocumentPanel(QWidget* parent = nullptr);

    void update_state(const std::vector<Json>& map_documents);

    // Test readback.
    QListWidget* document_list() const { return document_list_; }
    std::string name_text() const;
    std::string horizon_text() const;
    std::string polygon_count_text() const;
    std::string well_count_text() const;

private:
    std::vector<Json> documents_;
    QLabel* name_value_ = nullptr;
    QLabel* horizon_value_ = nullptr;
    QLabel* polygon_count_value_ = nullptr;
    QLabel* well_count_value_ = nullptr;
    QListWidget* document_list_ = nullptr;
};

}  // namespace pwb::ui_map
