# Embedded QGIS Runtime

The QGIS source in this directory is an owned, fixed source dependency. Build it
through `native/qgis_render_bridge/CMakeLists.txt`; do not replace it with an
installed `qgis_core` or `qgis_gui` library.

The source is GPL-2.0-or-later. Keep upstream notices intact and update
`UPSTREAM.md` whenever the vendor revision changes.
