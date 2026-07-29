# WellLogEngine Python bindings

`welllog-engine` embeds the native C++ `WellLogView` in PySide6 applications.
Curve samples are submitted through the Python Buffer Protocol and retained by
the immutable native document without copying when dtype, shape, byte order, and
stride are compatible.

Arrays passed to `WellLogView.submit_curve()` must be marked read-only before
submission and must not be mutated through another alias until the
document-owning view is released. Writable buffers are rejected instead of
being silently copied. The returned report records `access_mode`, dtype,
stride, length, and the retained source address for each buffer.
