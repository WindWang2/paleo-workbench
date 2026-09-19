#pragma once

// UI-02 — ColumnSpec + ObjectTableModel + StableSelection +
// bind_table_defaults, ported from
// paleo_workbench/ui/modelview/object_table.py (goal §8 Model/View
// Foundation).
//
// Structural contract (01-ui-audit D2 / 11-performance):
//  - rows are domain objects; data() resolves on demand — never N×C
//    item objects;
//  - set_rows is a whole-table diff reset (same key set keeps row
//    identity and emits the smallest possible dataChanged);
//  - sorting reorders indexes, never moves objects;
//  - StableSelection preserves selection by stable business key across
//    resets.
//
// C++ row type: QVariant (the Qt-native any — domain rows arrive as
// QVariant/custom types; key_of resolves the stable key).

#include <QAbstractTableModel>
#include <QAbstractItemView>
#include <QColor>
#include <QFont>
#include <QItemSelectionModel>
#include <QModelIndex>
#include <QString>
#include <QTableView>
#include <QVariant>

#include <functional>
#include <map>
#include <vector>

namespace pwb::ui_widgets {

// Row-object roles (same UserRole+N vocabulary as the Python model).
inline constexpr int kRowKeyRole = Qt::UserRole + 1;
inline constexpr int kRowObjectRole = Qt::UserRole + 2;

// Declarative column spec: title + value + sort key + presentation.
// Callbacks run on the row QVariant; no business logic belongs here.
struct ColumnSpec {
    QString key;
    QString title;
    std::function<QVariant(const QVariant& row)> value;
    std::function<QVariant(const QVariant& row)> sort_value;   // optional
    Qt::Alignment alignment = Qt::AlignLeft | Qt::AlignVCenter;
    std::function<QString(const QVariant& row)> tooltip;        // optional
    // Returns a palette token name ("TEXT_SECONDARY") or "" — resolved
    // through the CURRENT theme palette at data() time (theme switches
    // refresh via refresh_display()).
    std::function<QString(const QVariant& row)> foreground_role;
    std::function<QFont(const QVariant& row)> font_role;        // optional
    int width_hint = 0;

    // Python display() parity: None -> "", float -> "{:g}", else str().
    QString display(const QVariant& row) const;
};

class ObjectTableModel : public QAbstractTableModel {
    Q_OBJECT
public:
    ObjectTableModel(std::vector<ColumnSpec> columns,
                     std::function<QString(const QVariant& row)> key_of,
                     QObject* parent = nullptr);

    int rowCount(const QModelIndex& parent = QModelIndex()) const override;
    int columnCount(const QModelIndex& parent = QModelIndex()) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override;
    void sort(int column, Qt::SortOrder order = Qt::AscendingOrder) override;

    // Whole-table diff reset: identical key sequence -> dataChanged only
    // (selection/scroll preserved); else full reset.
    void set_rows(const std::vector<QVariant>& rows);
    void append_rows(const std::vector<QVariant>& rows);
    void remove_keys(const std::vector<QString>& keys);
    void clear_rows() { set_rows({}); }

    QVariant row_at(int index) const;
    QVariant row_for_key(const QString& key) const;
    QModelIndex index_for_key(const QString& key) const;
    QString key_for_index(const QModelIndex& index) const;
    std::vector<QString> all_keys() const;
    int size() const { return int(rows_.size()); }

    // Re-resolve foreground/font tokens after a theme switch (call after
    // the global repolish — Python refresh_display parity).
    void refresh_display();

private:
    void reindex();

    std::vector<ColumnSpec> columns_;
    std::function<QString(const QVariant&)> key_of_;
    std::vector<QVariant> rows_;
    std::map<QString, int> row_by_key_;
    int sort_column_ = -1;
    Qt::SortOrder sort_order_ = Qt::AscendingOrder;
};

// Selection preserved across model resets by stable key.
class StableSelection {
public:
    explicit StableSelection(QAbstractItemView* view) : view_(view) {}

    // Stable keys of currently selected rows (QTableView ->
    // selectedRows; other views -> selectedIndexes column-0... Python
    // uses selectedIndexes for non-QTableView).
    std::vector<QString> capture() const;

    // Re-select rows whose keys survived the reset; optionally make
    // `current_key` the current index.
    void restore(const std::vector<QString>& keys,
                 const QString& current_key = QString()) const;

private:
    QAbstractItemView* view_;  // not owned
};

// Unified table look defaults (behavior only — no stylesheet; the global
// QSS already covers colors/borders/selection, 01-ui-audit E3).
void bind_table_defaults(QTableView* view);

}  // namespace pwb::ui_widgets
