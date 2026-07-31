// Virtualized Qt table model for a Table Projection (ADR 0022, #154 Phase A).
// See header. The model is a thin adapter: rowCount/columnCount/data all read
// on demand from the core TableProjection, which reads the raw Curve buffer —
// no QVariant/row matrix is ever materialized, so a million-row table is
// virtualized.

#include <welllog/qtwidgets/table_model.hpp>

#include <cstdint>
#include <limits>
#include <memory>
#include <utility>

#include <QVariant>

#include <welllog/core/document.hpp>
#include <welllog/core/entity_id.hpp>
#include <welllog/table/table_projection.hpp>

namespace welllog {

namespace {

// Qt's int row/column index is 32-bit; a projection's row_count is 64-bit. A
// well-log table can exceed INT_MAX rows in principle. Cap the reported row
// count at INT_MAX (QAbstractItemModel's limit) — the visible block a view
// requests is always far below this, so virtualization is unaffected; only the
// reported total is capped. (A future ticket would handle >2^31-row paging.)
constexpr std::uint64_t max_qt_rows =
    static_cast<std::uint64_t>(std::numeric_limits<int>::max());

} // namespace

struct TableModel::Impl {
  TableProjection projection;
};

TableModel::TableModel(QObject *parent)
    : QAbstractTableModel(parent), impl_(std::make_unique<Impl>()) {}

TableModel::~TableModel() = default;

void TableModel::set_projection(TableProjection projection) noexcept {
  beginResetModel();
  impl_->projection = std::move(projection);
  endResetModel();
}

EntityId TableModel::document_id() const noexcept {
  return impl_->projection.document_id();
}
DocumentRevision TableModel::document_revision() const noexcept {
  return impl_->projection.document_revision();
}

int TableModel::rowCount(const QModelIndex &parent) const noexcept {
  if (parent.isValid()) {
    return 0; // flat table — no children
  }
  const auto rows = impl_->projection.row_count();
  return rows > max_qt_rows ? static_cast<int>(max_qt_rows)
                            : static_cast<int>(rows);
}

int TableModel::columnCount(const QModelIndex &parent) const noexcept {
  if (parent.isValid()) {
    return 0;
  }
  // Column counts are tiny by construction (depth + N curves per axis); cap at
  // INT_MAX for parity with rowCount() and -Wconversion cleanliness.
  const auto cols = impl_->projection.column_count();
  return cols > max_qt_rows ? static_cast<int>(max_qt_rows)
                            : static_cast<int>(cols);
}

QVariant TableModel::data(const QModelIndex &index, int role) const noexcept {
  if (!index.isValid() || index.row() < 0 || index.column() < 0) {
    return {};
  }
  const auto cell =
      raw_cell(static_cast<std::uint64_t>(index.row()),
               static_cast<std::uint64_t>(index.column()));
  switch (role) {
    case Qt::DisplayRole:
      // Null cells render as an empty cell (no sentinel text); non-null as the
      // raw double (Qt formats per the view's delegate). Keeping it a double
      // preserves numeric type (no pre-formatting to string).
      return cell.null ? QVariant{} : QVariant{cell.value};
    case RawValueRole:
      return cell.null ? QVariant{} : QVariant{cell.value};
    case NullRole:
      return cell.null;
    default:
      return {};
  }
}

QVariant TableModel::headerData(int section, Qt::Orientation orientation,
                                int role) const noexcept {
  if (role != Qt::DisplayRole) {
    return {};
  }
  if (orientation == Qt::Horizontal) {
    // Column header: the column name (mnemonic / "DEPTH"). 0..columnCount-1.
    if (section < 0 ||
        static_cast<std::uint64_t>(section) >= impl_->projection.column_count()) {
      return {};
    }
    const auto col = impl_->projection.column(static_cast<std::uint64_t>(section));
    // Include the unit when present, e.g. "GR (API)".
    if (!col.unit.empty()) {
      return QString::fromStdString(col.name + " (" + col.unit + ")");
    }
    return QString::fromStdString(col.name);
  }
  // Vertical header: the row index (the source sample index into the axis).
  return section;
}

TableRowCell TableModel::raw_cell(std::uint64_t row,
                                  std::uint64_t column) const noexcept {
  const auto cell = impl_->projection.cell(row, column);
  return TableRowCell{cell.value.value_or(0.0), cell.null()};
}

namespace {

// Formats a double with the shortest round-trip representation (mirrors the
// export backends' deterministic number formatting). Returns "" for null.
QString format_cell(const TableModel &model, std::uint64_t row,
                    std::uint64_t column) {
  const auto c = model.raw_cell(row, column);
  if (c.null) {
    return {};
  }
  // QString::number default uses 6 sig figs; use 'g' with max precision for a
  // faithful round-trip of the raw value.
  return QString::number(c.value, 'g', 17);
}

// Strips tab/newline/carriage-return from a TSV field so a mnemonic/unit/header
// containing those characters cannot corrupt the column structure. TSV has no
// quoting convention here, so sanitizing is the robust choice (RFC 4180 quoting
// is reserved for the CSV exporter in a later ticket).
QString sanitize_tsv_field(QString s) {
  s.remove('\t');
  s.remove('\n');
  s.remove('\r');
  return s;
}

// The app-internal MIME type carrying document id/revision/units so an in-app
// paste preserves identity (table-and-export.md §4.2 "可选内部 MIME").
constexpr const char *kWellLogTableMime = "application/x-welllog-table-selection";

} // namespace

SelectionClipboard build_selection_clipboard(const TableModel &model,
                                             RowSelection selection,
                                             std::uint64_t cell_limit) {
  SelectionClipboard result;
  const auto row_count = static_cast<std::uint64_t>(model.rowCount());
  const auto col_count = static_cast<std::uint64_t>(model.columnCount());
  // Clamp to the model's bounds.
  if (selection.first_row >= row_count || col_count == 0) {
    result.mime = std::make_unique<QMimeData>();
    return result;
  }
  const auto last = std::min(selection.last_row, row_count);
  const auto rows = last - selection.first_row;
  // Large-selection guard: do NOT build a giant string on the GUI thread
  // (criterion "超大选择不在 GUI 线程构造巨型字符串"). Signal the host to prompt
  // export instead.
  if (rows * col_count > cell_limit) {
    result.too_large_for_clipboard = true;
    return result;
  }

  // TSV (text/plain): header row + one tab-separated row per selected row.
  // Null cells are empty (no sentinel). Header fields are sanitized so a
  // mnemonic/unit containing tab/newline cannot corrupt the column structure.
  QString tsv;
  for (std::uint64_t c = 0; c < col_count; ++c) {
    if (c != 0) {
      tsv += '\t';
    }
    tsv += sanitize_tsv_field(
        model.headerData(static_cast<int>(c), Qt::Horizontal, Qt::DisplayRole)
            .toString());
  }
  tsv += '\n';
  // HTML (text/html): a <table> with <th> headers and <td> cells.
  QString html = QStringLiteral("<table><tr>");
  for (std::uint64_t c = 0; c < col_count; ++c) {
    html += "<th>";
    html += model.headerData(static_cast<int>(c), Qt::Horizontal, Qt::DisplayRole)
                .toString()
                .toHtmlEscaped();
    html += "</th>";
  }
  html += "</tr>";
  for (std::uint64_t r = selection.first_row; r < last; ++r) {
    // TSV row.
    for (std::uint64_t c = 0; c < col_count; ++c) {
      if (c != 0) {
        tsv += '\t';
      }
      tsv += format_cell(model, r, c);
    }
    tsv += '\n';
    // HTML row.
    html += "<tr>";
    for (std::uint64_t c = 0; c < col_count; ++c) {
      html += "<td>";
      html += format_cell(model, r, c).toHtmlEscaped();
      html += "</td>";
    }
    html += "</tr>";
  }
  html += "</table>";

  // Internal MIME: document id/revision for an in-app paste.
  const QString internal =
      QString::fromStdString(model.document_id().to_string()) + '/' +
      QString::number(model.document_revision().value);

  result.copied_rows = rows;
  result.mime = std::make_unique<QMimeData>();
  result.mime->setData(QStringLiteral("text/plain"), tsv.toUtf8());
  result.mime->setData(QStringLiteral("text/html"), html.toUtf8());
  result.mime->setData(QString::fromLatin1(kWellLogTableMime), internal.toUtf8());
  return result;
}

} // namespace welllog
