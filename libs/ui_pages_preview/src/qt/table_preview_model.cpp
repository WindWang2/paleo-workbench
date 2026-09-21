#include <pwb/ui_pages_preview/qt/table_preview_model.hpp>

#include <QBrush>
#include <QColor>

#include <pwb/ui_pages_preview/preview_table.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

namespace {

// Python: QFont("Cascadia Code", 9) / bold variant.
QFont make_mono(bool bold) {
    QFont f("Cascadia Code", 9);
    f.setBold(bold);
    return f;
}

}  // namespace

TablePreviewModel::TablePreviewModel(QObject* parent)
    : QAbstractTableModel(parent),
      mono_(make_mono(false)),
      mono_bold_(make_mono(true)) {}

void TablePreviewModel::set_table(std::vector<std::string> headers,
                                  std::vector<std::vector<std::string>> rows) {
    beginResetModel();
    headers_ = std::move(headers);
    rows_ = std::move(rows);
    depth_col_ = depth_column(headers_);
    curve_def_ = is_curve_definition(headers_);
    // Precompute text + kind once (#1388): delegates request 4-6 roles
    // per visible cell and the same trim/kind was redone each time.
    cell_texts_.resize(rows_.size());
    cell_kinds_.resize(rows_.size());
    for (std::size_t r = 0; r < rows_.size(); ++r) {
        cell_texts_[r].resize(headers_.size());
        cell_kinds_[r].resize(headers_.size());
        for (std::size_t c = 0; c < headers_.size(); ++c) {
            const std::string text =
                c < rows_[r].size() ? table_cell_text(rows_[r][c]) : "";
            cell_kinds_[r][c] =
                cell_kind(text, static_cast<int>(c), depth_col_, curve_def_);
            cell_texts_[r][c] = text;
        }
    }
    endResetModel();
}

int TablePreviewModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(rows_.size());
}

int TablePreviewModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(headers_.size());
}

QVariant TablePreviewModel::headerData(int section, Qt::Orientation orientation,
                                       int role) const {
    if (role != Qt::DisplayRole) return {};
    if (orientation == Qt::Horizontal &&
        section >= 0 && section < static_cast<int>(headers_.size())) {
        return QString::fromStdString(headers_[section]);
    }
    if (orientation == Qt::Vertical &&
        section >= 0 && section < static_cast<int>(rows_.size())) {
        return QString::number(section + 1);
    }
    return {};
}

QVariant TablePreviewModel::data(const QModelIndex& index, int role) const {
    if (!index.isValid()) return {};
    const int row = index.row();
    const int column = index.column();
    if (row < 0 || row >= static_cast<int>(rows_.size()) ||
        column < 0 || column >= static_cast<int>(headers_.size())) {
        return {};
    }
    // Python: val_str = str(raw).strip() — cells render stripped.
    const std::string& text = cell_texts_[size_t(row)][size_t(column)];

    if (role == Qt::DisplayRole) {
        return QString::fromStdString(text);
    }

    const CellKind kind = cell_kinds_[size_t(row)][size_t(column)];
    switch (kind) {
    case CellKind::depth:
        if (role == Qt::FontRole) return mono_bold_;
        if (role == Qt::ForegroundRole)
            return QBrush(QColor(qt_internal::token("PRIMARY")));
        if (role == Qt::BackgroundRole)
            return QBrush(QColor(qt_internal::token("BG_SELECTION")));
        if (role == Qt::TextAlignmentRole)
            return int(Qt::AlignRight | Qt::AlignVCenter);
        return {};
    case CellKind::curve_tag:
        if (role == Qt::FontRole) return mono_bold_;
        if (role == Qt::ForegroundRole)
            return QBrush(QColor(qt_internal::token("TEAL")));
        if (role == Qt::BackgroundRole)
            return QBrush(QColor(qt_internal::token("BG_SEARCH")));
        if (role == Qt::TextAlignmentRole)
            return int(Qt::AlignCenter | Qt::AlignVCenter);
        return {};
    case CellKind::curve_unit:
        if (role == Qt::FontRole) return mono_;
        if (role == Qt::ForegroundRole)
            return QBrush(QColor(qt_internal::token("TEXT_SECONDARY")));
        if (role == Qt::TextAlignmentRole)
            return int(Qt::AlignCenter | Qt::AlignVCenter);
        return {};
    case CellKind::nan_number:
        if (role == Qt::FontRole) return mono_;
        if (role == Qt::ForegroundRole)
            return QBrush(QColor(qt_internal::token("PRIMARY_DISABLED")));
        if (role == Qt::TextAlignmentRole)
            return int(Qt::AlignRight | Qt::AlignVCenter);
        return {};
    case CellKind::number:
        if (role == Qt::FontRole) return mono_;
        if (role == Qt::TextAlignmentRole)
            return int(Qt::AlignRight | Qt::AlignVCenter);
        return {};
    case CellKind::plain:
        return {};
    }
    return {};
}

std::vector<std::string> TablePreviewModel::row_text(int row) const {
    std::vector<std::string> out;
    if (row < 0 || row >= static_cast<int>(rows_.size())) return out;
    out.reserve(headers_.size());
    const auto& source = rows_[row];
    for (std::size_t c = 0; c < headers_.size(); ++c) {
        out.push_back(c < source.size() ? table_cell_text(source[c]) : "");
    }
    return out;
}

}  // namespace pwb::ui_pages_preview
