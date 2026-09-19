// UI-06 — filter_chips_bar.py Qt shell.
//
// FilterChipsBar renders the active FilterQuery as removable chips and
// owns the saved-filter combo; chip dimensions/removal/saved-filter JSON
// come from chips.hpp. QSettings is an injected get/set seam (Python
// _settings() parity — user settings, never a data authority).
#pragma once

#include <QLabel>
#include <QWidget>

#include <functional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_pages_data/chips.hpp>
#include <pwb/ui_pages_data/filter_query.hpp>

class QComboBox;
class QHBoxLayout;
class QPushButton;

namespace pwb::ui_pages_data::qt {

// Saved-filter persistence seam: read/write the JSON payload stored under
// kSavedFiltersKey. Default: in-memory store (tests/headless); the app
// wires QSettings.
struct SavedFilterStore {
    std::function<std::string()> get;
    std::function<void(const std::string&)> set;
};

class FilterChip : public QLabel {
    Q_OBJECT
public:
    FilterChip(const QString& key, const QString& text,
               QWidget* parent = nullptr);

    QString key() const { return key_; }

Q_SIGNALS:
    void clicked(const QString& key);

protected:
    void mousePressEvent(QMouseEvent* event) override;

private:
    QString key_;
};

class FilterChipsBar : public QWidget {
    Q_OBJECT
public:
    explicit FilterChipsBar(QWidget* parent = nullptr);

    // Re-render the chips for query (no signals emitted).
    void set_query(const FilterQuery& query);
    const FilterQuery& query() const { return query_; }

    void set_saved_filter_store(SavedFilterStore store);
    void reload_saved();

    QPushButton* clear_button() { return clear_btn_; }
    QPushButton* save_button() { return save_btn_; }
    QPushButton* delete_saved_button() { return delete_saved_btn_; }
    QComboBox* saved_combo() { return saved_combo_; }

Q_SIGNALS:
    void chip_removed(const QString& dimension_key);
    void clear_all();
    void filter_applied(const pwb::ui_pages_data::FilterQuery& query);

private:
    void add_chip(const QString& key, const QString& label);
    // _stored_filters() → ordered (name, query-dict) pairs (Python dict
    // order preserved — first-occurrence position, later dup overwrites).
    std::vector<std::pair<std::string, domain::Json>> stored_filters() const;
    void dump_filters(
        const std::vector<std::pair<std::string, domain::Json>>& filters);
    void apply_saved(int index);
    void save_current();
    void delete_saved();

    FilterQuery query_;
    QHBoxLayout* chips_layout_;
    QPushButton* clear_btn_;
    QComboBox* saved_combo_;
    QPushButton* save_btn_;
    QPushButton* delete_saved_btn_;
    SavedFilterStore store_;
    std::string memory_store_;   // default in-memory payload
};

}  // namespace pwb::ui_pages_data::qt
