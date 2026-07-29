# WellLogEngine Python bindings

`welllog-engine` embeds the native C++ `WellLogView` in PySide6 applications.
Curve samples are submitted through the Python Buffer Protocol and retained by
the immutable native document without copying when dtype, shape, byte order, and
stride are compatible.
