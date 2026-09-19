#pragma once

// UI-09 — shared model/view plumbing for the well/seismic panels.
//
// Port of the Python pages' ObjectTableModel + ColumnSpec + StableSelection
// pattern (correlation_link_editor.py, well_table_panel.py, the task
// panels): rows carry stable string keys so selection survives whole-model
// refreshes. Cells arrive pre-rendered from the Qt-free cores — this model
// is a dumb grid, never a second semantic authority.

#include <optional>
#include <string>
#include <vector>

#include <QAbstractTableModel>
#include <QBrush>
#include <QModelIndex>
#include <QString>
#include <QVariant>

class QItemSelectionModel;

namespace pwb::ui_wellseis::qt {

class StringTableModel : public QAbstractTableModel {
    Q_OBJECT
public:
    // Row key payload role (Python key_of parity — the stable identity).
    static constexpr int RowKeyRole = Qt::UserRole + 42;

    struct Column {
        QString key;
        QString title;
    };

    explicit StringTableModel(QObject* parent = nullptr);

    void set_columns(std::vector<Column> columns);
    // keys.size() must equal rows.size(); each row.size() must equal
    // columns(). Empty string renders like Python "".
    void set_rows(std::vector<std::string> keys,
                  std::vector<std::vector<QString>> rows);
    // Per-row foreground override (QC tokens -> palette color is the
    // shell's job; the model stores whatever brush the caller sets).
    void set_row_foreground(int row, const QBrush& brush);

    int rowCount(const QModelIndex& parent = {}) const override;
    int columnCount(const QModelIndex& parent = {}) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;

    [[nodiscard]] std::optional<std::string> key_at(int row) const;
    [[nodiscard]] int row_for_key(const std::string& key) const;
    [[nodiscard]] std::optional<std::string> key_for_index(
        const QModelIndex& index) const;

private:
    std::vector<Column> columns_;
    std::vector<std::string> keys_;
    std::vector<std::vector<QString>> rows_;
    std::vector<std::optional<QBrush>> foregrounds_;
};

// StableSelection parity: capture the selected row keys + current key
// before a set_rows, restore them after. All helpers are no-throw.
std::vector<std::string> capture_selected_keys(QItemSelectionModel* selection,
                                               StringTableModel* model);
std::optional<std::string> current_key(QItemSelectionModel* selection,
                                       StringTableModel* model);
void restore_selected_keys(QItemSelectionModel* selection,
                           StringTableModel* model,
                           const std::vector<std::string>& keys,
                           const std::optional<std::string>& current);

}  // namespace pwb::ui_wellseis::qt
