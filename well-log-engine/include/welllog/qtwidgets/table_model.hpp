#pragma once

// Virtualized Qt table model for a Table Projection (ADR 0022, #154 Phase A).
// A QAbstractTableModel adapter over a core welllog::TableProjection — the
// model reads cells ON DEMAND straight from the projection (which reads the
// raw Curve buffer), never materializing a full QVariant/row matrix. A
// million-row table is virtualized: rowCount() is O(1), and only the visible
// block the view requests is fetched. Mirrors the Qt-widgets-first adapter
// convention (ADR 0009): Qt types live only here, the core stays Qt-agnostic.
//
// Phase A scope: the host drives updates via set_projection() (the document
// id/revision is carried on the projection for invalidation). Phase B adds
// bidirectional graphics↔table selection sync via the ADR 0024 Selection Set.

#include <cstdint>
#include <memory>

#include <QAbstractTableModel>
#include <QMimeData>
#include <QVariant>

#include <welllog/qtwidgets/export.hpp>
#include <welllog/table/table_projection.hpp>

namespace welllog {

// One row of a projected curve table, materialized on demand for clipboard /
// block reads. Carries the raw double value and an explicit null flag (a null
// sample is empty, not a sentinel — table-and-export.md §4.2).
struct TableRowCell {
  double value{};
  bool null{true};
};

class WELLLOG_QTWIDGETS_API TableModel : public QAbstractTableModel {
  Q_OBJECT

public:
  // Custom item-data roles.
  enum Role {
    // The raw double value (invalid QVariant if the cell is null). Use this to
    // read the source value without display formatting.
    RawValueRole = Qt::UserRole,
    // True if the cell is null (null bitmap / out-of-range / non-finite).
    NullRole = Qt::UserRole + 1,
  };

  explicit TableModel(QObject *parent = nullptr);
  ~TableModel() override;
  TableModel(const TableModel &) = delete;
  TableModel &operator=(const TableModel &) = delete;

  // Replaces the projection this model adapts. Resets the model (emits
  // modelReset) so views refetch. An empty/null projection yields a 0×0 model.
  // Thread-safe in the #147 sense: call from the GUI thread; cross-thread
  // callers should marshal via QMetaObject::invokeMethod(QueuedConnection).
  void set_projection(TableProjection projection) noexcept;

  // The document id/revision this model's projection was built from (nil/0
  // when empty) — a host uses these to invalidate on document replacement.
  [[nodiscard]] EntityId document_id() const noexcept;
  [[nodiscard]] DocumentRevision document_revision() const noexcept;

  // --- QAbstractTableModel overrides (on-demand, no matrix copy) -----------
  [[nodiscard]] int rowCount(const QModelIndex &parent = {}) const noexcept
      override;
  [[nodiscard]] int columnCount(const QModelIndex &parent = {}) const noexcept
      override;
  [[nodiscard]] QVariant data(const QModelIndex &index,
                              int role = Qt::DisplayRole) const noexcept
      override;
  [[nodiscard]] QVariant headerData(int section, Qt::Orientation orientation,
                                    int role = Qt::DisplayRole) const noexcept
      override;

  // Reads one cell's raw value + null flag on demand (the zero-copy raw-buffer
  // path through the projection). Used by clipboard copy and exposed for tests.
  [[nodiscard]] TableRowCell raw_cell(std::uint64_t row,
                                      std::uint64_t column) const noexcept;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

// Result of building a clipboard payload from a table selection (ADR 0022,
// #154 Phase A / table-and-export.md §4.2). When the selection exceeds the
// safe per-clipboard limit, `too_large_for_clipboard` is set and no payload is
// built — the host should prompt the user to export instead (the criterion:
// "超大选择不在 GUI 线程构造巨型字符串").
struct SelectionClipboard {
  // True when the selection is too large to build on the GUI thread; the host
  // should offer a file export instead. When true, the QMimeData pointers below
  // are null.
  bool too_large_for_clipboard{false};
  // The number of rows actually copied (0 when too large).
  std::uint64_t copied_rows{};
  // Owning the built payload. Null when too large. The caller takes ownership
  // (parent it to the QApplication clipboard or delete it).
  std::unique_ptr<QMimeData> mime;
};

// A half-open [first_row, last_row) selection range on a table.
struct RowSelection {
  std::uint64_t first_row{};
  std::uint64_t last_row{}; // exclusive
};

// Default ceiling above which a selection is "too large" to build on the GUI
// thread (table-and-export.md §4.2). ~250k cells keeps TSV/HTML well under a
// few MB; above this the host should prompt to export a file.
constexpr std::uint64_t default_clipboard_cell_limit = 250'000;

// Builds a clipboard payload (TSV `text/plain` + HTML `text/html` + an
// app-internal MIME carrying document id/revision/units) for the given
// selection on `model`. Reads the RAW buffer via the model (not LOD). When the
// selection's cell count exceeds `cell_limit`, returns
// `too_large_for_clipboard` without building anything. `first_row`/`last_row`
// are clamped to the model's row count.
[[nodiscard]] WELLLOG_QTWIDGETS_API SelectionClipboard
build_selection_clipboard(const TableModel &model, RowSelection selection,
                          std::uint64_t cell_limit = default_clipboard_cell_limit);

} // namespace welllog
