#include <pwb/ui_wellseis/qt/viz_d_seismic_binding.hpp>

#include <utility>

#include <pwb/ui_wellseis/seismic_attributes.hpp>

namespace pwb::ui_wellseis::qt {

SeismicViewFactory make_real_seismic_view_factory(
    std::shared_ptr<pwb::viz::ISeismicVolume> volume,
    pwb::seismic_viewer::VolumeIdentity identity, std::uint64_t revision) {
    // The seam must be honest about a missing source: a null volume
    // reports unavailability so the panel swaps its honest placeholder
    // page in (never a silent empty widget).
    return [volume = std::move(volume), identity, revision](
               QWidget* parent) -> SeismicViewSeam {
        if (!volume) {
            return {nullptr, "no seismic volume available"};
        }
        auto* viewer = new pwb::seismic_viewer::SeismicSliceWidget(parent);
        viewer->set_volume(volume, identity, revision);
        return {viewer, ""};
    };
}

RealSeismicViewBinding::RealSeismicViewBinding(QWidget* parent)
    : widget_(new pwb::seismic_viewer::SeismicSliceWidget(parent)) {}

RealSeismicViewBinding::~RealSeismicViewBinding() {
    // Qt owns the widget once parented (SeismicViewPanel::set_view
    // reparents it into its stack); a never-embedded binding deletes
    // its own.
    if (widget_ != nullptr && widget_->parent() == nullptr) {
        delete widget_;
    }
}

QWidget* RealSeismicViewBinding::widget() const {
    return widget_;
}

bool RealSeismicViewBinding::apply_display_mode(const std::string& mode) {
    // #1394 词汇 (kDisplayModeVd/kDisplayModeWiggle, seismic_attributes)
    // -> the widget's DisplayMode enum.
    if (mode == kDisplayModeVd || mode == "variable_density") {
        widget_->set_display_mode(
            pwb::seismic_viewer::DisplayMode::variable_density);
        return true;
    }
    if (mode == kDisplayModeWiggle) {
        // 波形仅限剖面视图 — on the sample (map) view set_display_mode
        // no-ops by contract. The status is read back from the widget's
        // own state instead of re-deriving the guard here: the call
        // succeeded exactly when the mode became (or stayed) wiggle.
        widget_->set_display_mode(pwb::seismic_viewer::DisplayMode::wiggle);
        return widget_->display_mode() ==
               pwb::seismic_viewer::DisplayMode::wiggle;
    }
    return false;  // unknown token — no call, no state change
}

void RealSeismicViewBinding::apply_polarity(bool normal) {
    widget_->set_polarity(normal);
}

void RealSeismicViewBinding::apply_wiggle_gain(double gain) {
    widget_->set_wiggle_gain(gain);
}

void RealSeismicViewBinding::set_slice(pwb::viz::VolumeAxis axis,
                                       std::int64_t index) {
    // Order matters: set_axis clamps the current index into the new
    // axis' range first, then the explicit index rides after (both
    // clamp + resubmit through the controller).
    widget_->set_axis(axis);
    widget_->set_slice_index(index);
}

void RealSeismicViewBinding::enable_picking(bool enabled) {
    widget_->enable_picking(enabled);
}

bool RealSeismicViewBinding::save_picks(const std::string& path,
                                        std::string& error) {
    return widget_->save_picks(path, error);
}

pwb::seismic_viewer::PicksLoadStatus RealSeismicViewBinding::load_picks(
    const std::string& path, std::string& error) {
    return widget_->load_picks(path, error);
}

const pwb::seismic_viewer::horizon::HorizonPickSet&
RealSeismicViewBinding::picks() const {
    return widget_->picks();
}

void RealSeismicViewBinding::shutdown() {
    // 幂等 — clear_volume() drops the source and empties the view; the
    // widget's own destructor clears again, so double teardown from
    // closeEvent paths is safe.
    widget_->clear_volume();
}

std::pair<double, double> RealSeismicViewBinding::displayed_range() const {
    return widget_->displayed_range();
}

}  // namespace pwb::ui_wellseis::qt
