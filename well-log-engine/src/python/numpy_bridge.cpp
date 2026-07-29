#ifdef Py_LIMITED_API
#undef Py_LIMITED_API
#endif
#define Py_LIMITED_API 0x030b0000
#include <Python.h>

#include "numpy_bridge.hpp"

#include <welllog/core/document.hpp>
#include <welllog/qtwidgets/well_log_view.hpp>

#include <QByteArray>
#include <QThread>
#include <QUuid>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <initializer_list>
#include <limits>
#include <memory>
#include <new>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace welllog::python {
namespace {

class PythonBufferOwner final {
public:
  PythonBufferOwner() = default;
  PythonBufferOwner(const PythonBufferOwner &) = delete;
  PythonBufferOwner &operator=(const PythonBufferOwner &) = delete;

  ~PythonBufferOwner() {
    if (view_.obj == nullptr || !Py_IsInitialized()) {
      return;
    }
    const auto state = PyGILState_Ensure();
    PyBuffer_Release(&view_);
    PyGILState_Release(state);
  }

  [[nodiscard]] bool acquire(PyObject *object) noexcept {
    return PyObject_GetBuffer(object, &view_, PyBUF_FORMAT | PyBUF_STRIDES) ==
           0;
  }

  [[nodiscard]] const Py_buffer &view() const noexcept { return view_; }

private:
  Py_buffer view_{};
};

struct AdaptedBuffer {
  BufferView buffer;
  std::string dtype;
  std::uint64_t address{};
};

void set_welllog_error(const char *type_name, const char *code,
                       const char *message) {
  auto *module = PyImport_ImportModule("welllog.errors");
  if (module == nullptr) {
    return;
  }
  auto *type = PyObject_GetAttrString(module, type_name);
  Py_DECREF(module);
  if (type == nullptr) {
    return;
  }
  auto *instance = PyObject_CallFunction(type, "ss", message, code);
  if (instance != nullptr) {
    PyErr_SetObject(type, instance);
    Py_DECREF(instance);
  }
  Py_DECREF(type);
}

[[nodiscard]] const char *error_code_name(ErrorCode code) noexcept {
  switch (code) {
  case ErrorCode::missing_owner:
    return "missing_owner";
  case ErrorCode::invalid_buffer:
    return "invalid_buffer";
  case ErrorCode::arithmetic_overflow:
    return "arithmetic_overflow";
  case ErrorCode::invalid_sampling_axis:
    return "invalid_sampling_axis";
  case ErrorCode::length_mismatch:
    return "length_mismatch";
  case ErrorCode::duplicate_entity_id:
    return "duplicate_entity_id";
  case ErrorCode::missing_sampling_axis:
    return "missing_sampling_axis";
  case ErrorCode::invalid_document:
    return "invalid_document";
  case ErrorCode::invalid_presentation:
    return "invalid_presentation";
  case ErrorCode::invalid_viewport:
    return "invalid_viewport";
  case ErrorCode::document_not_found:
    return "document_not_found";
  case ErrorCode::invalid_manifest:
    return "invalid_manifest";
  case ErrorCode::unresolved_buffer:
    return "unresolved_buffer";
  case ErrorCode::resource_exhausted:
    return "resource_exhausted";
  case ErrorCode::internal_error:
    return "internal_error";
  }
  return "internal_error";
}

void set_result_error(const Error &error, const char *operation) {
  const auto *type_name = error.code == ErrorCode::resource_exhausted ||
                                  error.code == ErrorCode::internal_error
                              ? "WellLogError"
                              : "WellLogValidationError";
  const auto *code = error_code_name(error.code);
  const auto message = std::string{operation} + " failed with code " + code;
  set_welllog_error(type_name, code, message.c_str());
}

[[nodiscard]] std::optional<ScalarType>
scalar_type_for_buffer(const Py_buffer &view) noexcept {
  if (view.format == nullptr) {
    return std::nullopt;
  }
  auto format = std::string_view{view.format};
  if (format.size() == 2 && (format.front() == '@' || format.front() == '=' ||
                             format.front() == '<' || format.front() == '>')) {
    if ((format.front() == '<' || format.front() == '>') &&
        (format.front() == '<') !=
#if Q_BYTE_ORDER == Q_LITTLE_ENDIAN
            true
#else
            false
#endif
    ) {
      return std::nullopt;
    }
    format.remove_prefix(1);
  }
  if (format == "f" && view.itemsize == 4) {
    return ScalarType::float32;
  }
  if (format == "d" && view.itemsize == 8) {
    return ScalarType::float64;
  }
  if (format == "h" && view.itemsize == 2) {
    return ScalarType::int16;
  }
  if (format == "i" && view.itemsize == 4) {
    return ScalarType::int32;
  }
  if (format == "q" && view.itemsize == 8) {
    return ScalarType::int64;
  }
  if (format == "B" && view.itemsize == 1) {
    return ScalarType::uint8;
  }
  if (format == "H" && view.itemsize == 2) {
    return ScalarType::uint16;
  }
  if (format == "I" && view.itemsize == 4) {
    return ScalarType::uint32;
  }
  if (format == "Q" && view.itemsize == 8) {
    return ScalarType::uint64;
  }
  return std::nullopt;
}

[[nodiscard]] std::optional<AdaptedBuffer> adapt_buffer(PyObject *object,
                                                        const char *role) {
  auto owner = std::make_shared<PythonBufferOwner>();
  if (!owner->acquire(object)) {
    PyErr_Clear();
    set_welllog_error("WellLogValidationError", "invalid_buffer",
                      "object does not expose a compatible buffer");
    return std::nullopt;
  }
  const auto &view = owner->view();
  if (view.ndim != 1 || view.shape == nullptr || view.shape[0] <= 0 ||
      view.buf == nullptr || view.itemsize <= 0) {
    const auto message =
        std::string{role} + " must be a non-empty one-dimensional buffer";
    set_welllog_error("WellLogValidationError", "invalid_buffer",
                      message.c_str());
    return std::nullopt;
  }
  if (view.readonly == 0) {
    const auto message =
        std::string{role} + " must be marked read-only for zero-copy access";
    set_welllog_error("WellLogValidationError", "writable_buffer",
                      message.c_str());
    return std::nullopt;
  }
  const auto scalar_type = scalar_type_for_buffer(view);
  if (!scalar_type.has_value()) {
    const auto message =
        std::string{role} + " uses an unsupported or non-native scalar dtype";
    set_welllog_error("WellLogValidationError", "invalid_buffer",
                      message.c_str());
    return std::nullopt;
  }
  const auto stride = view.strides == nullptr ? view.itemsize : view.strides[0];
  if (stride < view.itemsize || stride <= 0) {
    const auto message =
        std::string{role} + " must use a positive stride of at least one item";
    set_welllog_error("WellLogValidationError", "invalid_buffer",
                      message.c_str());
    return std::nullopt;
  }
  const auto length = static_cast<std::uint64_t>(view.shape[0]);
  const auto stride_bytes = static_cast<std::uint64_t>(stride);
  const auto item_size = static_cast<std::uint64_t>(view.itemsize);
  if (length - 1 >
      (std::numeric_limits<std::uint64_t>::max() - item_size) / stride_bytes) {
    const auto message = std::string{role} + " buffer extent is too large";
    set_welllog_error("WellLogValidationError", "arithmetic_overflow",
                      message.c_str());
    return std::nullopt;
  }
  const auto capacity = (length - 1) * stride_bytes + item_size;
  const auto address =
      static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(view.buf));
  const auto dtype = std::string{scalar_type_name(*scalar_type)};
  return AdaptedBuffer{
      .buffer = BufferView::from_raw(view.buf, length, stride_bytes,
                                     *scalar_type, capacity, SharedOwner{owner},
                                     {}, BufferAccessMode::zero_copy),
      .dtype = dtype,
      .address = address,
  };
}

[[nodiscard]] std::optional<EntityId> parse_id(const QString &text,
                                               const char *role) {
  const auto encoded = text.toUtf8();
  const auto result = EntityId::parse(std::string_view{
      encoded.constData(), static_cast<std::size_t>(encoded.size())});
  if (!result.has_value() || result->is_nil()) {
    const auto message = std::string{role} + " must be a non-nil UUID";
    set_welllog_error("WellLogValidationError", "invalid_document",
                      message.c_str());
  }
  return result;
}

[[nodiscard]] EntityId
derive_presentation_id(EntityId document_id, std::string_view role,
                       std::initializer_list<EntityId> forbidden) {
  const auto namespace_uuid =
      QUuid{QString::fromStdString(document_id.to_string())};
  const auto base_name =
      QByteArray{role.data(), static_cast<qsizetype>(role.size())};
  for (auto suffix = 0; suffix <= static_cast<int>(forbidden.size());
       ++suffix) {
    auto name = base_name;
    if (suffix != 0) {
      name.append('/');
      name.append(QByteArray::number(suffix));
    }
    const auto derived = QUuid::createUuidV5(namespace_uuid, name);
    const auto encoded = derived.toString(QUuid::WithoutBraces).toStdString();
    const auto candidate = EntityId::parse(encoded).value();
    if (std::find(forbidden.begin(), forbidden.end(), candidate) ==
        forbidden.end()) {
      return candidate;
    }
  }
  throw std::runtime_error{"could not derive a unique presentation entity ID"};
}

[[nodiscard]] Result<CommandReceipt> prepare_default_curve_scene(
    WellLogView &view, EntityId document_id, EntityId axis_id,
    EntityId curve_id, const BufferView &depth, const BufferView &values,
    const std::string &depth_unit, const std::string &value_unit) {
  auto top = depth.value_as_double(0).value();
  auto bottom = depth.value_as_double(depth.length() - 1).value();
  if (top > bottom) {
    std::swap(top, bottom);
  }
  if (top == bottom) {
    bottom = top + 1.0;
  }

  auto minimum = std::numeric_limits<double>::infinity();
  auto maximum = -std::numeric_limits<double>::infinity();
  for (std::uint64_t index = 0; index < values.length(); ++index) {
    const auto value = values.value_as_double(index);
    if (value.has_value() && std::isfinite(*value)) {
      minimum = std::min(minimum, *value);
      maximum = std::max(maximum, *value);
    }
  }
  if (!std::isfinite(minimum) || !std::isfinite(maximum)) {
    minimum = 0.0;
    maximum = 1.0;
  } else if (minimum == maximum) {
    maximum = minimum + 1.0;
  }

  const auto track_id =
      derive_presentation_id(document_id, "welllog-python/default-track",
                             {document_id, axis_id, curve_id});
  const auto scale_id =
      derive_presentation_id(document_id, "welllog-python/default-scale",
                             {document_id, axis_id, curve_id, track_id});
  const auto layer_role =
      std::string{"welllog-python/default-layer/"} + curve_id.to_string();
  const auto layer_id = derive_presentation_id(
      document_id, layer_role,
      {document_id, axis_id, curve_id, track_id, scale_id});
  ScenePresentationBuilder presentation_builder(
      document_id,
      ReferenceDepthRange{
          .domain = DepthDomain::measured_depth,
          .unit = depth_unit,
          .top = top,
          .bottom = bottom,
      },
      Millimetres{100.0}, "welllog-python-default");
  presentation_builder.add_track(
      TrackSpec{.id = track_id, .width = Millimetres{40.0}, .z_order = 0});
  presentation_builder.add_scale(TrackScaleSpec{
      .id = scale_id,
      .track_id = track_id,
      .mode = ScaleMode::linear,
      .minimum = minimum,
      .maximum = maximum,
      .direction = ScaleDirection::left_to_right,
      .unit = value_unit,
  });
  presentation_builder.add_curve_layer(CurveLayerSpec{
      .id = layer_id,
      .track_id = track_id,
      .curve_id = curve_id,
      .scale_id = scale_id,
      .color =
          RgbaColor{.red = 0x19, .green = 0x72, .blue = 0xb8, .alpha = 0xff},
      .line_width = Millimetres{0.35},
      .z_order = 0,
  });
  return view.session().execute(
      SetPresentationCommand{presentation_builder.build()});
}

[[nodiscard]] PyObject *buffer_report(const AdaptedBuffer &buffer) {
  auto *report = PyDict_New();
  if (report == nullptr) {
    return nullptr;
  }
  auto put = [report](const char *key, PyObject *value) {
    if (value == nullptr || PyDict_SetItemString(report, key, value) != 0) {
      Py_XDECREF(value);
      return false;
    }
    Py_DECREF(value);
    return true;
  };
  if (!put("access_mode", PyUnicode_FromString("zero_copy")) ||
      !put("dtype", PyUnicode_FromString(buffer.dtype.c_str())) ||
      !put("length", PyLong_FromUnsignedLongLong(buffer.buffer.length())) ||
      !put("stride_bytes",
           PyLong_FromUnsignedLongLong(buffer.buffer.stride_bytes())) ||
      !put("address", PyLong_FromUnsignedLongLong(buffer.address))) {
    Py_DECREF(report);
    return nullptr;
  }
  return report;
}

} // namespace

namespace {

PyObject *submit_curve_impl(WellLogView *view, PyObject *depth,
                            PyObject *values, const QString &document_id_text,
                            const QString &axis_id_text,
                            const QString &curve_id_text,
                            const QString &mnemonic, const QString &depth_unit,
                            const QString &value_unit) {
  if (view == nullptr) {
    set_welllog_error("WellLogValidationError", "invalid_view",
                      "WellLogView is no longer valid");
    return nullptr;
  }
  if (QThread::currentThread() != view->thread()) {
    set_welllog_error("WellLogThreadError", "thread_violation",
                      "curve submission must run on the Qt GUI thread");
    return nullptr;
  }
  const auto document_id = parse_id(document_id_text, "document_id");
  const auto axis_id = parse_id(axis_id_text, "axis_id");
  const auto curve_id = parse_id(curve_id_text, "curve_id");
  if (!document_id || !axis_id || !curve_id) {
    return nullptr;
  }
  if (depth_unit.isEmpty() || value_unit.isEmpty()) {
    set_welllog_error("WellLogValidationError", "invalid_presentation",
                      "depth_unit and value_unit must be non-empty");
    return nullptr;
  }
  auto depth_buffer = adapt_buffer(depth, "depth");
  if (!depth_buffer) {
    return nullptr;
  }
  auto value_buffer = adapt_buffer(values, "values");
  if (!value_buffer) {
    return nullptr;
  }
  if (depth_buffer->buffer.length() != value_buffer->buffer.length()) {
    set_welllog_error("WellLogValidationError", "length_mismatch",
                      "depth and values must have the same length");
    return nullptr;
  }

  WellLogDocumentBuilder builder(*document_id, DocumentRevision{1});
  const auto depth_unit_utf8 = depth_unit.toUtf8();
  const auto value_unit_utf8 = value_unit.toUtf8();
  const auto mnemonic_utf8 = mnemonic.toUtf8();
  const auto first_depth = depth_buffer->buffer.value_as_double(0).value();
  const auto last_depth =
      depth_buffer->buffer.value_as_double(depth_buffer->buffer.length() - 1)
          .value();
  builder.add_sampling_axis(SamplingAxis{
      .id = *axis_id,
      .coordinates = depth_buffer->buffer,
      .domain = DepthDomain::measured_depth,
      .unit = depth_unit_utf8.constData(),
      .direction = last_depth < first_depth ? AxisDirection::decreasing
                                            : AxisDirection::increasing,
  });
  builder.add_curve(Curve{
      .id = *curve_id,
      .mnemonic = mnemonic_utf8.constData(),
      .display_name = mnemonic_utf8.constData(),
      .unit = value_unit_utf8.constData(),
      .sampling_axis_id = *axis_id,
      .values = value_buffer->buffer,
      .nulls = {},
  });
  const auto result =
      view->session().execute(SetDocumentCommand{builder.build()});
  if (!result.has_value()) {
    set_result_error(result.error(), "document submission");
    return nullptr;
  }
  const auto presentation = prepare_default_curve_scene(
      *view, *document_id, *axis_id, *curve_id, depth_buffer->buffer,
      value_buffer->buffer, depth_unit_utf8.constData(),
      value_unit_utf8.constData());
  if (!presentation.has_value()) {
    set_result_error(presentation.error(), "presentation preparation");
    return nullptr;
  }
  view->set_document_id(*document_id);

  auto *report = PyDict_New();
  auto *depth_report = buffer_report(*depth_buffer);
  auto *curve_report = buffer_report(*value_buffer);
  if (report == nullptr || depth_report == nullptr || curve_report == nullptr ||
      PyDict_SetItemString(report, "depth", depth_report) != 0 ||
      PyDict_SetItemString(report, "curve", curve_report) != 0 ||
      PyDict_SetItemString(report, "render_prepared", Py_True) != 0) {
    Py_XDECREF(report);
    Py_XDECREF(depth_report);
    Py_XDECREF(curve_report);
    return nullptr;
  }
  Py_DECREF(depth_report);
  Py_DECREF(curve_report);
  return report;
}

PyObject *sample_value_impl(WellLogView *view, const QString &curve_id_text,
                            unsigned long long sample_index) {
  if (view == nullptr || !view->document_id().has_value()) {
    Py_RETURN_NONE;
  }
  const auto curve_id = parse_id(curve_id_text, "curve_id");
  if (!curve_id) {
    return nullptr;
  }
  const auto document = view->session().document(*view->document_id());
  if (document == nullptr) {
    Py_RETURN_NONE;
  }
  for (const auto &curve : document->curves()) {
    if (curve.id == *curve_id) {
      const auto value = curve.values.value_as_double(
          static_cast<std::uint64_t>(sample_index));
      return value.has_value() ? PyFloat_FromDouble(*value)
                               : Py_NewRef(Py_None);
    }
  }
  Py_RETURN_NONE;
}

} // namespace

PyObject *submit_curve(WellLogView *view, PyObject *depth, PyObject *values,
                       const QString &document_id_text,
                       const QString &axis_id_text,
                       const QString &curve_id_text, const QString &mnemonic,
                       const QString &depth_unit,
                       const QString &value_unit) noexcept {
  try {
    return submit_curve_impl(view, depth, values, document_id_text,
                             axis_id_text, curve_id_text, mnemonic, depth_unit,
                             value_unit);
  } catch (const std::bad_alloc &) {
    return PyErr_NoMemory();
  } catch (...) {
    set_welllog_error("WellLogError", "internal_error",
                      "unexpected native failure during curve submission");
    return nullptr;
  }
}

PyObject *sample_value(WellLogView *view, const QString &curve_id_text,
                       unsigned long long sample_index) noexcept {
  try {
    return sample_value_impl(view, curve_id_text, sample_index);
  } catch (const std::bad_alloc &) {
    return PyErr_NoMemory();
  } catch (...) {
    set_welllog_error("WellLogError", "internal_error",
                      "unexpected native failure while reading a curve sample");
    return nullptr;
  }
}

} // namespace welllog::python
