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
             const QString &depth_unit, const QString &value_unit);

[[nodiscard]] PyObject *sample_value(WellLogView *view, const QString &curve_id,
                                     unsigned long long sample_index);

} // namespace python
} // namespace welllog
