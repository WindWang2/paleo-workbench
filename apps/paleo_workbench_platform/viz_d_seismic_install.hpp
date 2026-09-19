#pragma once

// VIZ-D app install — the D-line's only footprint in the platform app
// (besides the guarded call): advanced-seismic-display affordances for the
// existing 地震 dock. The SeismicSliceWidget owns the actual display,
// horizon pick model and persistence (libs/seismic_viewer); this header
// only adds menu entries so the capabilities are discoverable from the
// 地震 menu, plus a shutdown hook the close path can call.
//
// No preview/data-page assembly happens here (P-A: the global preview
// dispatcher belongs to the E line; D provides the tested presenters at
// lib level — see libs/ui_pages_preview/qt/seismic_preview_presenter.hpp).

class QMenu;

namespace pwb::seismic_viewer {
class SeismicSliceWidget;
}

namespace pwb::viz_d {

// Adds 地平线拾取 toggle / 清空 / 导出… / 导入… actions for `widget` to
// `menu` (mirrors the widget's own toolbar for menu discoverability; every
// action forwards to the widget API — no duplicated state).
void add_seismic_horizon_menu_actions(QMenu& menu,
                                      pwb::seismic_viewer::SeismicSliceWidget& widget);

} // namespace pwb::viz_d
