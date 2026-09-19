#include "pwb/ui_widgets/object_table.hpp"

#include "pwb/ui_widgets/ui_context.hpp"

#include <QHeaderView>

#include <algorithm>
#include <cmath>
#include <deque>
#include <map>
#include <set>

namespace pwb::ui_widgets {
namespace {

// Python sort_key parity: uniform (tier, value) keys — numeric tier
// sorts before text tier, absent values sort last (review P1-2: mixed
// numeric/「—」 columns never raise). Returns a tagged comparator value.
struct SortKey {
    int tier = 2;  // 0 numeric, 1 text, 2 absent
    double numeric = 0;
    QString text;
};

SortKey sort_key_of(const QVariant& v) {
    SortKey k;
    if (!v.isValid() || v.isNull()) {
        k.tier = 2;
        return k;
    }
    switch (v.typeId()) {
        case QMetaType::Bool:
            k.tier = 0;
            k.numeric = v.toBool() ? 1.0 : 0.0;
            return k;
        case QMetaType::Int:
        case QMetaType::UInt:
        case QMetaType::LongLong:
        case QMetaType::ULongLong:
        case QMetaType::Double:
        case QMetaType::Float:
            // #1390: a NaN key makes sort_key_less always-false against every
            // value — the equivalence relation stops being transitive and
            // std::stable_sort's strict-weak-ordering precondition breaks
            // (UB). NaN cells sort as absent (tier 2); ±inf is a real
            // orderable number in Python and stays numeric.
            if (std::isnan(v.toDouble())) {
                k.tier = 2;
                return k;
            }
            k.tier = 0;
            k.numeric = v.toDouble();
            return k;
        default:
            k.tier = 1;
            k.text = v.toString();
            return k;
    }
}

bool sort_key_less(const SortKey& a, const SortKey& b) {
    if (a.tier != b.tier) return a.tier < b.tier;
    if (a.tier == 0) return a.numeric < b.numeric;
    if (a.tier == 1) return a.text < b.text;
    return false;
}

}  // namespace

// ---------------------------------------------------------------- ColumnSpec

QString ColumnSpec::display(const QVariant& row) const {
    const QVariant v = value ? value(row) : QVariant();
    if (!v.isValid() || v.isNull()) {
        return QString();
    }
    // Python: isinstance(v, float) -> f"{v:g}" (6 significant digits);
    // bool falls through to str(v) -> "True"/"False" (NOT float path —
    // bool is int in Python but the f-string only fires for float).
    if (v.typeId() == QMetaType::Double || v.typeId() == QMetaType::Float) {
        return QString::number(v.toDouble(), 'g', 6);
    }
    if (v.typeId() == QMetaType::Bool) {
        return v.toBool() ? QStringLiteral("True") : QStringLiteral("False");
    }
    return v.toString();
}

// ---------------------------------------------------------- ObjectTableModel

ObjectTableModel::ObjectTableModel(
    std::vector<ColumnSpec> columns,
    std::function<QString(const QVariant& row)> key_of,
    QObject* parent)
    : QAbstractTableModel(parent),
      columns_(std::move(columns)),
      key_of_(std::move(key_of)) {}

int ObjectTableModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : int(rows_.size());
}

int ObjectTableModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : int(columns_.size());
}

QVariant ObjectTableModel::headerData(int section,
                                      Qt::Orientation orientation,
                                      int role) const {
    if (orientation == Qt::Horizontal && section >= 0 &&
        section < int(columns_.size()) && role == Qt::DisplayRole) {
        return columns_[size_t(section)].title;
    }
    return {};
}

QVariant ObjectTableModel::data(const QModelIndex& index, int role) const {
    if (!index.isValid()) return {};
    const int row_idx = index.row();
    if (row_idx < 0 || row_idx >= int(rows_.size())) return {};
    // #1390: column bound — a proxy/delegate may hand in a column beyond
    // columns_.size(); headerData already guards, data() must too.
    if (index.column() < 0 || index.column() >= int(columns_.size())) {
        return {};
    }
    const QVariant& row = rows_[size_t(row_idx)];
    const ColumnSpec& col = columns_[size_t(index.column())];
    if (role == Qt::DisplayRole) {
        return col.display(row);
    }
    if (role == Qt::ToolTipRole && col.tooltip) {
        return col.tooltip(row);
    }
    if (role == Qt::TextAlignmentRole) {
        return int(col.alignment);
    }
    if (role == Qt::ForegroundRole && col.foreground_role) {
        const QString token_name = col.foreground_role(row);
        if (!token_name.isEmpty()) {
            const QString hex = palette_token(token_name.toUtf8().constData());
            if (!hex.isEmpty()) {
                return QColor(hex);
            }
        }
        return {};
    }
    if (role == Qt::FontRole && col.font_role) {
        return col.font_role(row);
    }
    if (role == kRowObjectRole) {
        return row;
    }
    if (role == kRowKeyRole) {
        return key_of_(row);
    }
    return {};
}

void ObjectTableModel::sort(int column, Qt::SortOrder order) {
    if (column < -1 || column >= int(columns_.size())) {
        return;
    }
    sort_column_ = column;
    sort_order_ = order;
    if (column < 0) {
        return;
    }
    const ColumnSpec& col = columns_[size_t(column)];
    const auto sort_value = col.sort_value ? col.sort_value : col.value;

    // Row identity -> sorted row index map, to remap persistent indexes
    // (Qt does not remap them on layoutChanged — review P1-1: selection/
    // current-row corruption). QVariant rows have no pointer identity;
    // the stable business key is the identity (keys are the contract).
    const std::vector<QVariant> old_rows = rows_;
    // persistentIndexList() returns QModelIndex copies in Qt6; wrap each
    // as QPersistentModelIndex for changePersistentIndex.
    const QList<QModelIndex> persistent = persistentIndexList();
    std::vector<int> old_positions;
    old_positions.reserve(size_t(persistent.size()));
    for (const auto& index : persistent) {
        old_positions.push_back(index.row());
    }

    // Python list.sort(key, reverse=...) is a single STABLE pass: equal
    // keys keep their original relative order in both directions.
    emit layoutAboutToBeChanged();
    const bool descending = order == Qt::DescendingOrder;
    std::stable_sort(rows_.begin(), rows_.end(),
                     [&](const QVariant& a, const QVariant& b) {
                         const SortKey ka = sort_key_of(sort_value(a));
                         const SortKey kb = sort_key_of(sort_value(b));
                         return descending ? sort_key_less(kb, ka)
                                           : sort_key_less(ka, kb);
                     });
    reindex();

    // key -> queue of new positions (duplicate keys disambiguate in
    // sorted order, matching Python's id()-ordered dict build).
    std::map<QString, std::deque<int>> positions_by_key;
    for (int i = 0; i < int(rows_.size()); ++i) {
        positions_by_key[key_of_(rows_[size_t(i)])].push_back(i);
    }
    for (size_t i = 0; i < persistent.size(); ++i) {
        const int old_pos = old_positions[i];
        if (old_pos < 0 || old_pos >= int(old_rows.size())) continue;
        const QString key = key_of_(old_rows[size_t(old_pos)]);
        auto it = positions_by_key.find(key);
        if (it == positions_by_key.end() || it->second.empty()) continue;
        const int new_pos = it->second.front();
        it->second.pop_front();
        changePersistentIndex(
            persistent[int(i)],
            this->index(new_pos, persistent[int(i)].column()));
    }
    emit layoutChanged();
}

void ObjectTableModel::set_rows(const std::vector<QVariant>& rows) {
    std::vector<QString> old_keys;
    old_keys.reserve(rows_.size());
    for (const auto& r : rows_) old_keys.push_back(key_of_(r));
    std::vector<QString> new_keys;
    new_keys.reserve(rows.size());
    for (const auto& r : rows) new_keys.push_back(key_of_(r));
    if (old_keys == new_keys) {
        if (new_keys.empty()) return;
        const QModelIndex top = index(0, 0);
        const QModelIndex bottom =
            index(int(rows.size()) - 1, int(columns_.size()) - 1);
        rows_ = rows;
        reindex();
        emit dataChanged(top, bottom);
        return;
    }
    beginResetModel();
    rows_ = rows;
    reindex();
    endResetModel();
}

void ObjectTableModel::append_rows(const std::vector<QVariant>& rows) {
    std::vector<QVariant> add;
    for (const auto& r : rows) {
        if (row_by_key_.find(key_of_(r)) == row_by_key_.end()) {
            add.push_back(r);
        }
    }
    if (add.empty()) return;
    const int start = int(rows_.size());
    beginInsertRows(QModelIndex(), start, start + int(add.size()) - 1);
    rows_.insert(rows_.end(), add.begin(), add.end());
    reindex();
    endInsertRows();
}

void ObjectTableModel::remove_keys(const std::vector<QString>& keys) {
    if (keys.empty()) return;
    std::set<QString> key_set(keys.begin(), keys.end());
    std::vector<QVariant> keep;
    keep.reserve(rows_.size());
    for (const auto& r : rows_) {
        if (key_set.find(key_of_(r)) == key_set.end()) {
            keep.push_back(r);
        }
    }
    // Simplified implementation: whole-table reset preserving row order
    // (Python parity).
    set_rows(keep);
}

QVariant ObjectTableModel::row_at(int index) const {
    if (index >= 0 && index < int(rows_.size())) {
        return rows_[size_t(index)];
    }
    return {};
}

QVariant ObjectTableModel::row_for_key(const QString& key) const {
    const auto it = row_by_key_.find(key);
    if (it == row_by_key_.end() || it->second >= int(rows_.size())) {
        return {};
    }
    return rows_[size_t(it->second)];
}

QModelIndex ObjectTableModel::index_for_key(const QString& key) const {
    const auto it = row_by_key_.find(key);
    if (it == row_by_key_.end() || it->second >= int(rows_.size())) {
        return {};
    }
    return index(it->second, 0);
}

QString ObjectTableModel::key_for_index(const QModelIndex& index) const {
    if (!index.isValid()) return {};
    const QVariant row = row_at(index.row());
    return row.isValid() ? key_of_(row) : QString();
}

std::vector<QString> ObjectTableModel::all_keys() const {
    std::vector<QString> keys;
    keys.reserve(rows_.size());
    for (const auto& r : rows_) keys.push_back(key_of_(r));
    return keys;
}

void ObjectTableModel::refresh_display() {
    if (rows_.empty()) return;
    emit dataChanged(index(0, 0),
                     index(int(rows_.size()) - 1, int(columns_.size()) - 1));
}

void ObjectTableModel::reindex() {
    row_by_key_.clear();
    for (int i = 0; i < int(rows_.size()); ++i) {
        row_by_key_[key_of_(rows_[size_t(i)])] = i;
    }
}

// -------------------------------------------------------------- StableSelection

namespace {

// _model_key parity: ObjectTableModel provides key_for_index directly;
// other models fall back to the ROW_KEY_ROLE UserRole convention.
QString model_key(QAbstractItemModel* model, const QModelIndex& index) {
    if (auto* otm = qobject_cast<ObjectTableModel*>(model)) {
        return otm->key_for_index(index);
    }
    const QVariant value = model->data(index, kRowKeyRole);
    return value.isValid() && !value.isNull() ? value.toString() : QString();
}

QModelIndex model_index_for_key(QAbstractItemModel* model,
                                const QString& key) {
    if (key.isEmpty()) return {};
    if (auto* otm = qobject_cast<ObjectTableModel*>(model)) {
        return otm->index_for_key(key);
    }
    for (int row = 0; row < model->rowCount(); ++row) {
        const QModelIndex index = model->index(row, 0);
        if (model->data(index, kRowKeyRole).toString() == key) {
            return index;
        }
    }
    return {};
}

}  // namespace

std::vector<QString> StableSelection::capture() const {
    QAbstractItemModel* model = view_->model();
    if (model == nullptr || view_->selectionModel() == nullptr) {
        return {};
    }
    std::vector<QString> keys;
    const auto indexes =
        qobject_cast<QTableView*>(view_) != nullptr
            ? view_->selectionModel()->selectedRows()
            : view_->selectionModel()->selectedIndexes();
    for (const QModelIndex& index : indexes) {
        const QString key = model_key(model, index);
        if (!key.isEmpty() &&
            std::find(keys.begin(), keys.end(), key) == keys.end()) {
            keys.push_back(key);
        }
    }
    return keys;
}

void StableSelection::restore(const std::vector<QString>& keys,
                              const QString& current_key) const {
    QAbstractItemModel* model = view_->model();
    if (model == nullptr) return;
    QItemSelectionModel* selection_model = view_->selectionModel();
    selection_model->clearSelection();
    QModelIndex first_index;
    for (const QString& key : keys) {
        const QModelIndex index = model_index_for_key(model, key);
        if (index.isValid()) {
            selection_model->select(index, QItemSelectionModel::Select |
                                               QItemSelectionModel::Rows);
            if (!first_index.isValid()) {
                first_index = index;
            }
        }
    }
    QModelIndex current = current_key.isEmpty()
                              ? QModelIndex()
                              : model_index_for_key(model, current_key);
    if (!current.isValid()) {
        current = first_index;
    }
    if (current.isValid()) {
        selection_model->setCurrentIndex(current,
                                         QItemSelectionModel::NoUpdate);
    }
}

// ---------------------------------------------------------- bind_table_defaults

void bind_table_defaults(QTableView* view) {
    view->setAlternatingRowColors(true);
    view->setShowGrid(false);
    view->setSelectionBehavior(QTableView::SelectRows);
    view->setEditTriggers(QTableView::NoEditTriggers);
    view->verticalHeader()->setVisible(false);
    view->horizontalHeader()->setStretchLastSection(false);
    view->horizontalHeader()->setHighlightSections(false);
}

}  // namespace pwb::ui_widgets
