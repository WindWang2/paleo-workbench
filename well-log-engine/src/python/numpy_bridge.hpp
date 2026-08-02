#pragma once

#include <QString>

struct _object;
using PyObject = _object;

namespace welllog {

class WellLogView;

namespace python {

[[nodiscard]] PyObject *
submit_curve(WellLogView *view, PyObject *depth, PyObject *values,
             const QString &document_id, const QString &axis_id,
             const QString &curve_id, const QString &mnemonic,
             const QString &depth_unit, const QString &value_unit) noexcept;

// Multi-well section (#170): payload is a dict with wells/gap/shared
// viewport/overlays (see workbench welllog_multi_well_adapter.plan_to_submit_payload).
[[nodiscard]] PyObject *
submit_multi_well_section(WellLogView *view, PyObject *payload) noexcept;

[[nodiscard]] PyObject *clear_multi_well_section(WellLogView *view) noexcept;

[[nodiscard]] PyObject *sample_value(WellLogView *view, const QString &curve_id,
                                     unsigned long long sample_index) noexcept;

} // namespace python
} // namespace welllog
