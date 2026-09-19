// UI-08 — paleo_workbench/ui/pages/map_attribute_table.py port: the bottom
// property grid for the selected map feature — bounded feature selector
// (search + pin + _MAX_VISIBLE window), field filter/sort, and the
// two-column property table (name/text editable → property_changed).
//
// Feature records are domain::Json dicts (the Python dict contract).
#pragma once

#include "pwb/domain/json.hpp"

#include <QFrame>
#include <QListWidget>

#include <QString>
#include <QStringList>
#include <map>
#include <vector>

class QLabel;
class QLineEdit;
class QTableWidget;
class QTableWidgetItem;
class QTimer;

namespace pwb::ui_pages_mapedit {

// _DISPLAY_KEYS — property grid display order (geometry summarized).
inline const std::vector<QString>& display_keys() {
    static const std::vector<QString> keys = {
        QStringLiteral("id"), QStringLiteral("kind"), QStringLiteral("name"),
        QStringLiteral("text"), QStringLiteral("topology_status"),
    };
    return keys;
}

// 占位行 key（"— 未选择 —"）：与业务要素 id 空间不冲突。
inline const QString kPlaceholderKey;

// 可见窗口上限（V11 01-ui-audit D2 ②）: ≤ _MAX_VISIBLE items materialized.
inline constexpr int kMaxVisible = 500;
// 选择器列表高度：约 7 行。
inline constexpr int kSelectorListMaxHeight = 168;

// _FeatureSelectorList — bounded QListWidget keeping the old QComboBox
// access surface (currentData/findData/itemText/setCurrentIndex).
class FeatureSelectorList : public QListWidget {
    Q_OBJECT
public:
    explicit FeatureSelectorList(QWidget* parent = nullptr);

    QVariant currentData(int role = Qt::UserRole) const;
    int findData(const QVariant& data, int role = Qt::UserRole) const;
    QString itemText(int row) const;
    void setCurrentIndex(int row) { setCurrentRow(row); }
};

class MapAttributeTable : public QFrame {
    Q_OBJECT
public:
    explicit MapAttributeTable(QWidget* parent = nullptr);

    // Apply a field-substring filter ("" clears). Returns the visible ids.
    QStringList apply_filter(const QString& field = QString(),
                             const QString& needle = QString());
    QStringList sort_features(const QString& field = QString());

    void set_feature(const domain::Json* feature);
    void set_feature(const domain::Json& feature) { set_feature(&feature); }
    void clear_feature() { set_feature(nullptr); }

    // Bind the grid to one active vector layer (features = record dicts).
    void set_layer_features(const std::vector<domain::Json>& features,
                            const QStringList& selected_ids = {});
    // Diff-update bound records (id set unchanged; C-P0-3).
    void update_layer_features(const std::vector<domain::Json>& features,
                               const QStringList& selected_ids = {});
    void set_selected_ids(const QStringList& selected_ids);

    // Widget handles (Python attribute parity for tests/hosts).
    QLineEdit* feature_search = nullptr;
    FeatureSelectorList* feature_combo = nullptr;
    QTableWidget* table = nullptr;

signals:
    void property_changed(const QString& feature_id, const QString& key,
                          const QString& value);
    // authoritative feature id, or "" to clear.
    void feature_selection_requested(const QString& feature_id);

private:
    QStringList visible_feature_ids() const;
    QStringList selector_keys(const QStringList& visible,
                              const QString& pin_id) const;
    QListWidgetItem* make_feature_item(const QString& key);
    void update_feature_item(QListWidgetItem* item, const QString& key);
    void refresh_selector(const QString* pin_id = nullptr);
    void on_search_changed(const QString& text);
    void apply_search_now();
    void on_feature_selected(QListWidgetItem* current,
                             QListWidgetItem* previous);
    void rebuild();
    void on_item_changed(QTableWidgetItem* item);
    static QString combo_label(const domain::Json& feature,
                               const QString& feature_id);
    static QString geometry_summary(const domain::Json& coords);

    domain::Json feature_;           // null when no feature bound
    bool has_feature_ = false;
    QString feature_id_;
    std::vector<QString> layer_order_;  // bind (Python dict) order
    std::map<QString, domain::Json> layer_features_;
    bool suppress_item_changed_ = false;
    bool suppress_feature_selection_ = false;
    QString filter_field_;
    QString filter_needle_;
    QString sort_field_;
    QString search_needle_;
    QTimer* search_debounce_ = nullptr;
    QLabel* feature_count_label_ = nullptr;
};

}  // namespace pwb::ui_pages_mapedit
