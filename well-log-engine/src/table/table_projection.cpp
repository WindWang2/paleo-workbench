// Virtualized Table Projection implementation (ADR 0022, #154). See header for
// the design. The projection partitions a WellLogDocument's curves by Sampling
// Axis into one CurveTable per axis, reading raw Curve::values straight from
// the document's BufferViews (zero copy — never LOD points). Interval, marker
// and annotation tables are flat per-row projections of their struct fields.

#include <welllog/table/table_projection.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include <welllog/core/document.hpp>
#include <welllog/core/entity_id.hpp>

namespace welllog {
namespace {

// The shared, immutable state of one projected table. Holds only metadata +
// references to the document's spans; cells are read on demand from the
// document buffers the spans point into (the document's SharedOwners keep that
// storage alive — the builder holds the document by value, retaining it).
struct CurveColumn {
  EntityId curve_id{};
  std::string name;
  std::string unit;
  // For a curve column: pointers into the document's spans (the curve + its
  // axis). For the axis (depth) column, curve is nullptr and the axis is set.
  const SamplingAxis *axis{};
  const Curve *curve{};
};

} // namespace

// The PIMPL state of TableProjection. Defined at namespace scope (not anon) so
// the header's forward-declared `struct Impl` resolves to it.
struct TableProjection::Impl {
  TableKind kind{};
  EntityId sampling_axis_id{};
  EntityId document_id{};
  DocumentRevision document_revision{};
  std::uint64_t row_count{};
  std::vector<CurveColumn> columns;
  // Retains the source document for the projection's lifetime; the column
  // pointers reference spans inside it.
  std::shared_ptr<const WellLogDocument> document_holder;
};

namespace {

// Reads a curve/axis cell straight from the raw BufferView (zero copy). Null
// when the index is out of range, the null bitmap is set, or the value is
// non-finite — matching the scene kernel's missing-sample rule
// (src/scene/scene.cpp ~1505). This is the "reads the raw Buffer, not LOD"
// path. Defined here (before cell()) so the accessor can call it.
TableCell read_buffer_cell(const BufferView &values, const NullBitmapView &nulls,
                           std::uint64_t row) noexcept {
  if (!nulls.empty() && nulls.is_null(row)) {
    return TableCell{std::nullopt};
  }
  const auto v = values.value_as_double(row);
  if (!v.has_value() || !std::isfinite(*v)) {
    return TableCell{std::nullopt};
  }
  return TableCell{*v};
}

} // namespace

TableProjection::TableProjection() = default;
TableProjection::~TableProjection() = default;
TableProjection::TableProjection(const TableProjection &) = default;
TableProjection &TableProjection::operator=(const TableProjection &) = default;
TableProjection::TableProjection(TableProjection &&) noexcept = default;
TableProjection &TableProjection::operator=(TableProjection &&) noexcept = default;

TableProjection::TableProjection(std::shared_ptr<const Impl> impl)
    : impl_(std::move(impl)) {}

TableKind TableProjection::kind() const noexcept {
  return impl_ ? impl_->kind : TableKind::curves;
}
EntityId TableProjection::sampling_axis_id() const noexcept {
  return impl_ ? impl_->sampling_axis_id : EntityId{};
}
EntityId TableProjection::document_id() const noexcept {
  return impl_ ? impl_->document_id : EntityId{};
}
DocumentRevision TableProjection::document_revision() const noexcept {
  return impl_ ? impl_->document_revision : DocumentRevision{};
}
std::uint64_t TableProjection::column_count() const noexcept {
  return impl_ ? impl_->columns.size() : 0;
}
TableColumn TableProjection::column(std::uint64_t index) const noexcept {
  if (!impl_ || index >= impl_->columns.size()) {
    return {};
  }
  const auto &c = impl_->columns[index];
  return TableColumn{c.curve_id, c.name, c.unit};
}
std::uint64_t TableProjection::row_count() const noexcept {
  return impl_ ? impl_->row_count : 0;
}

TableCell TableProjection::cell(std::uint64_t row,
                                std::uint64_t col) const noexcept {
  if (!impl_ || row >= impl_->row_count || col >= impl_->columns.size()) {
    return TableCell{std::nullopt};
  }
  const auto &column = impl_->columns[col];
  if (impl_->kind == TableKind::curves) {
    // Raw buffer read: the axis column reads the axis coordinates; a curve
    // column reads that curve's values. Both share the same row index.
    const auto *axis = column.axis;
    if (axis == nullptr) {
      return TableCell{std::nullopt};
    }
    if (column.curve == nullptr) {
      // Depth/axis column.
      return read_buffer_cell(axis->coordinates, NullBitmapView{}, row);
    }
    return read_buffer_cell(column.curve->values, column.curve->nulls, row);
  }
  // Non-curve tables: not implemented as raw-buffer projections in this phase
  // (interval/marker/annotation fields are struct values, not Buffers). They
  // surface no numeric cells here; the Qt model formats them separately.
  return TableCell{std::nullopt};
}

// Builds one curve table for an axis + the curves sharing it. A member of the
// builder (not a free function) so it can reach TableProjection's private
// ctor/Impl via this class's friendship. Column 0 is the axis (depth) column;
// columns 1..n are the curves in document order.
TableProjection TableProjectionBuilder::make_curve_table(
    const std::shared_ptr<const WellLogDocument> &document,
    EntityId document_id, DocumentRevision revision, const SamplingAxis &axis,
    const std::vector<const Curve *> &curves) {
  auto impl = std::make_shared<TableProjection::Impl>();
  impl->kind = TableKind::curves;
  impl->sampling_axis_id = axis.id;
  impl->document_id = document_id;
  impl->document_revision = revision;
  impl->document_holder = document;
  // Row count = axis coordinate count (the alignment unit). Curves whose value
  // buffers differ in length still address by row index; out-of-range reads
  // yield null cells (read_buffer_cell).
  impl->row_count = axis.coordinates.length();
  // Depth/axis column.
  CurveColumn depth_col;
  depth_col.curve_id = EntityId{};
  depth_col.name = "DEPTH";
  depth_col.unit = axis.unit;
  depth_col.axis = &axis;
  depth_col.curve = nullptr;
  impl->columns.push_back(std::move(depth_col));
  // One column per curve sharing this axis.
  for (const Curve *curve : curves) {
    CurveColumn cc;
    cc.curve_id = curve->id;
    cc.name = curve->mnemonic.empty() ? curve->display_name : curve->mnemonic;
    cc.unit = curve->unit;
    cc.axis = &axis;
    cc.curve = curve;
    impl->columns.push_back(std::move(cc));
  }
  return TableProjection{std::move(impl)};
}

std::vector<TableProjection>
TableProjectionBuilder::from_document(const WellLogDocument &document) noexcept {
  // Hold the document alive for the projections' lifetime via a shared copy.
  // WellLogDocument is an immutable PIMPL value type (shared_ptr<const Impl>),
  // so copying is cheap and shares state.
  auto holder = std::make_shared<WellLogDocument>(document);
  const auto doc_id = document.id();
  const auto revision = document.revision();

  // Group curves by sampling_axis_id, preserving per-axis document order, and
  // remember the order axes were first seen (curve tables are emitted in axis
  // order). A curve whose axis is not present on the document is skipped (it
  // cannot be aligned — no implicit join).
  const auto axes = document.sampling_axes();
  const auto curves = document.curves();
  std::unordered_map<EntityId, const SamplingAxis *, EntityIdHash> axis_by_id;
  for (const auto &axis : axes) {
    axis_by_id.emplace(axis.id, &axis);
  }
  std::vector<EntityId> axis_order;
  std::unordered_map<EntityId, std::vector<const Curve *>, EntityIdHash>
      curves_by_axis;
  for (const auto &curve : curves) {
    const auto it = axis_by_id.find(curve.sampling_axis_id);
    if (it == axis_by_id.end()) {
      continue; // unaligned curve — no implicit alignment (ADR 0022 §2.2)
    }
    if (curves_by_axis.find(curve.sampling_axis_id) == curves_by_axis.end()) {
      axis_order.push_back(curve.sampling_axis_id);
    }
    curves_by_axis[curve.sampling_axis_id].push_back(&curve);
  }

  std::vector<TableProjection> tables;
  // Curve tables, in axis order.
  for (const auto &axis_id : axis_order) {
    const auto *axis = axis_by_id.at(axis_id);
    tables.push_back(make_curve_table(holder, doc_id, revision, *axis,
                                      curves_by_axis[axis_id]));
  }
  return tables;
}

} // namespace welllog
