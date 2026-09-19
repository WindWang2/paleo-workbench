#include <pwb/ui_wellseis/qt/object_table_model.hpp>

#include <QItemSelectionModel>

namespace pwb::ui_wellseis::qt {

StringTableModel::StringTableModel(QObject* parent)
    : QAbstractTableModel(parent) {}

void StringTableModel::set_columns(std::vector<Column> columns) {
    beginResetModel();
    columns_ = std::move(columns);
    keys_.clear();
    rows_.clear();
    foregrounds_.clear();
    endResetModel();
}

void StringTableModel::set_rows(std::vector<std::string> keys,
                                std::vector<std::vector<QString>> rows) {
    beginResetModel();
    keys_ = std::move(keys);
    rows_ = std::move(rows);
    foregrounds_.assign(rows_.size(), std::nullopt);
    endResetModel();
}

void StringTableModel::set_row_foreground(int row, const QBrush& brush) {
    if (row < 0 || row >= static_cast<int>(rows_.size())) {
        return;
    }
    if (foregrounds_.size() != rows_.size()) {
        foregrounds_.assign(rows_.size(), std::nullopt);
    }
    foregrounds_[row] = brush;
    const int cols = columnCount();
    if (cols > 0) {
        emit dataChanged(index(row, 0), index(row, cols - 1),
                         {Qt::ForegroundRole});
    }
}

int StringTableModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(rows_.size());
}

int StringTableModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(columns_.size());
}

QVariant StringTableModel::data(const QModelIndex& index, int role) const {
    if (!index.isValid() || index.row() < 0 ||
        index.row() >= static_cast<int>(rows_.size()) ||
        index.column() < 0 ||
        index.column() >= static_cast<int>(columns_.size())) {
        return {};
    }
    if (role == RowKeyRole) {
        return QString::fromStdString(keys_[index.row()]);
    }
    if (role == Qt::DisplayRole || role == Qt::EditRole) {
        const auto& row = rows_[index.row()];
        if (index.column() < static_cast<int>(row.size())) {
            return row[index.column()];
        }
        return {};
    }
    if (role == Qt::ForegroundRole &&
        index.row() < static_cast<int>(foregrounds_.size()) &&
        foregrounds_[index.row()].has_value()) {
        return *foregrounds_[index.row()];
    }
    return {};
}

QVariant StringTableModel::headerData(int section,
                                      Qt::Orientation orientation,
                                      int role) const {
    if (orientation == Qt::Horizontal && role == Qt::DisplayRole &&
        section >= 0 && section < static_cast<int>(columns_.size())) {
        return columns_[section].title;
    }
    return QAbstractTableModel::headerData(section, orientation, role);
}

std::optional<std::string> StringTableModel::key_at(int row) const {
    if (row < 0 || row >= static_cast<int>(keys_.size())) {
        return std::nullopt;
    }
    return keys_[row];
}

int StringTableModel::row_for_key(const std::string& key) const {
    for (std::size_t i = 0; i < keys_.size(); ++i) {
        if (keys_[i] == key) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

std::optional<std::string> StringTableModel::key_for_index(
    const QModelIndex& index) const {
    return key_at(index.isValid() ? index.row() : -1);
}

std::vector<std::string> capture_selected_keys(QItemSelectionModel* selection,
                                               StringTableModel* model) {
    std::vector<std::string> keys;
    if (selection == nullptr || model == nullptr) {
        return keys;
    }
    for (const QModelIndex& index : selection->selectedRows()) {
        if (auto key = model->key_for_index(index)) {
            keys.push_back(std::move(*key));
        }
    }
    return keys;
}

std::optional<std::string> current_key(QItemSelectionModel* selection,
                                       StringTableModel* model) {
    if (selection == nullptr || model == nullptr) {
        return std::nullopt;
    }
    return model->key_for_index(selection->currentIndex());
}

void restore_selected_keys(QItemSelectionModel* selection,
                           StringTableModel* model,
                           const std::vector<std::string>& keys,
                           const std::optional<std::string>& current) {
    if (selection == nullptr || model == nullptr) {
        return;
    }
    const QSignalBlocker blocker(selection);
    selection->clearSelection();
    QModelIndex first_index;
    for (const std::string& key : keys) {
        const int row = model->row_for_key(key);
        if (row < 0) {
            continue;
        }
        const QModelIndex idx = model->index(row, 0);
        selection->select(idx, QItemSelectionModel::Select |
                                   QItemSelectionModel::Rows);
        if (!first_index.isValid()) {
            first_index = idx;
        }
    }
    if (current.has_value()) {
        const int row = model->row_for_key(*current);
        if (row >= 0) {
            selection->setCurrentIndex(
                model->index(row, 0), QItemSelectionModel::NoUpdate);
            return;
        }
    }
    if (first_index.isValid()) {
        selection->setCurrentIndex(first_index, QItemSelectionModel::NoUpdate);
    }
}

}  // namespace pwb::ui_wellseis::qt
