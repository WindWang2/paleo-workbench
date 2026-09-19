#pragma once

// VIZ-D — 地震视图真实引擎绑定 (real seismic engine binding).
//
// #1394 froze SeismicViewPanel behind the SeismicViewSeam / QWidget*
// factory (engine_seams.hpp) so this library never depends on the
// engine. The D-line now ships the real viewer —
// pwb::seismic_viewer::SeismicSliceWidget: 变密度/波形 (VD / wiggle),
// SEG polarity flip, percentile clip, wiggle gain, 层位拾取 with JSON
// persistence, colorbar, and lifecycle-controlled volumes
// (set_volume(volume, identity, revision)). This file is the glue and
// nothing else: a factory that wraps the widget into an honest seam,
// and a thin adapter forwarding the #1394 control-surface vocabulary
// onto it. NO viewer logic is reimplemented here — every method is a
// one-line forward.
//
// Honesty rule (engine_seams.hpp): a null volume yields
// {nullptr, "no seismic volume available"} — the panel then swaps its
// honest unavailable page in, never a silent empty widget.
//
// update_state(task/project) stays OUT of scope: task/page state is the
// panel's hooks' business, not the viewer's.
//
// No Q_OBJECT on purpose (the viewer itself is moc-free; mirrors the
// #1394 shells — callbacks stay std::function, connects stay lambdas).

#include <cstdint>
#include <memory>
#include <string>
#include <utility>

#include <QWidget>

#include <pwb/seismic_viewer/horizon_core.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/seismic_viewer/slice_selection.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::ui_wellseis::qt {

// 工厂 (engine seam) — returns a factory whose seam wraps a real
// SeismicSliceWidget parented to the panel parent and bound to the
// volume via set_volume. `volume` is captured shared: the factory may
// be copied and deferred by the host. A null volume reports
// "no seismic volume available" at call time (honest seam, never a
// silent empty widget).
[[nodiscard]] SeismicViewFactory make_real_seismic_view_factory(
    std::shared_ptr<pwb::viz::ISeismicVolume> volume,
    pwb::seismic_viewer::VolumeIdentity identity, std::uint64_t revision);

// 控制面适配器 — owns one SeismicSliceWidget and adapts the #1394
// control surface onto it so the merged panel drives the real viewer.
// The host keeps this handle next to the seam: the panel's generic
// hooks (task state, resources, attribute labels) stay host-side,
// while the viewer-shaped controls below forward verbatim.
class RealSeismicViewBinding {
public:
    explicit RealSeismicViewBinding(QWidget* parent = nullptr);
    // Qt owns the widget once it has a parent (the panel stack reparents
    // it via SeismicViewSeam); a never-embedded binding deletes its own.
    ~RealSeismicViewBinding();

    RealSeismicViewBinding(const RealSeismicViewBinding&) = delete;
    RealSeismicViewBinding& operator=(const RealSeismicViewBinding&) = delete;

    // The engine widget (never null) — the seam's QWidget* handle.
    [[nodiscard]] QWidget* widget() const;

    // 1. 显示模式 — "vd"|"variable_density" -> set_display_mode(
    // variable_density); "wiggle" -> set_display_mode(wiggle). Wiggle is
    // section-view only: on the sample (map) view the widget no-ops by
    // contract and the return is false (status read back from the
    // widget, never re-derived here). Unknown token: no call, false.
    bool apply_display_mode(const std::string& mode);

    // 2. 极性与增益 — set_polarity (display-only SEG flip; raw readouts
    // and picks keep the survey sign); set_wiggle_gain (one trace slot
    // at 1.0, default 2.0 lets adjacent traces overlap; non-positive is
    // a widget no-op).
    void apply_polarity(bool normal);
    void apply_wiggle_gain(double gain);

    // 3. 切片 — set_axis clamps the current index into the new axis'
    // range and resubmits; set_slice_index clamps and resubmits.
    void set_slice(pwb::viz::VolumeAxis axis, std::int64_t index);

    // 4. 层位拾取 — enable_picking toggles click-add / drag-move /
    // right-click-delete; save/load_picks are passthroughs returning the
    // widget statuses verbatim (a volume mismatch still loads and is
    // reported as mismatched_volume). picks() exposes the live set for
    // the panel's interpretation-draft signals.
    void enable_picking(bool enabled);
    [[nodiscard]] bool save_picks(const std::string& path, std::string& error);
    [[nodiscard]] pwb::seismic_viewer::PicksLoadStatus load_picks(
        const std::string& path, std::string& error);
    [[nodiscard]] const pwb::seismic_viewer::horizon::HorizonPickSet&
    picks() const;

    // 5. 生命周期 — shutdown() forwards to clear_volume() (source drop +
    // controller epoch bump; queued old-volume work can never reappear).
    // Idempotent and safe to call from closeEvent paths (the widget's own
    // teardown clears again — SliceController shutdown is idempotent).
    void shutdown();

    // 读数 passthrough — the applied VD value range of the displayed
    // image ({0, 0} when nothing is displayed); the colorbar and status
    // strips consume this.
    [[nodiscard]] std::pair<double, double> displayed_range() const;

private:
    pwb::seismic_viewer::SeismicSliceWidget* widget_ = nullptr;  // Qt-owned
};

}  // namespace pwb::ui_wellseis::qt
