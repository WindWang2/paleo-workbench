#include "closure_seismic_install.hpp"

#include <array>
#include <cmath>
#include <deque>
#include <filesystem>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <utility>
#include <vector>

#include <QString>

#include <pwb/science/algorithm.hpp>
#include <pwb/science/registry.hpp>
#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>
#include <pwb/seismic_service/volume_service.hpp>
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#include <pwb/seismic_viewer/slice_selection.hpp>
#include <pwb/ui_workers/worker_common.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/qt/seismic_attribute_panel.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_view_panel.hpp>
#include <pwb/ui_wellseis/qt/viz_d_seismic_binding.hpp>
#include <pwb/ui_wellseis/seismic_attributes.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::closure_seismic {
namespace {

using pwb::ui_wellseis::qt::RealSeismicViewBinding;
using pwb::ui_wellseis::qt::SeismicViewHooks;
using pwb::ui_wellseis::qt::SeismicViewSeam;
using pwb::viz::VolumeAxis;
using Viewer = pwb::seismic_viewer::SeismicSliceWidget;

constexpr const char* kRgbFusionLabel = "RGB融合";

// The single-trace (E line) kernels computable on a 2-D section: each trace
// is an independent 1-D chain — envelope/rms/phase/freq PLUS sweetness and
// relative impedance (round-1 review: those two are also per-trace chains
// in the Python panel, attribute_pipeline kind="trace"; refusing them with
// the "needs 3-D neighborhood" text was wrong). The genuinely structural
// kernels (dips, azimuth, curvature, C3) need cross-trace neighborhoods
// and are declined on sections — an honest capability boundary, not a
// stub; they stay reachable through the volume-level 计算属性 dialog.
bool is_section_kernel(const std::string& kernel_id) {
    return kernel_id == "envelope" || kernel_id == "rms_amplitude" ||
           kernel_id == "instantaneous_phase" ||
           kernel_id == "instantaneous_frequency" ||
           kernel_id == "sweetness" || kernel_id == "relative_impedance";
}

// Deterministic section-attribute run: wrap the canonical plane
// (rows = traces, cols = samples on both section views) as a packed
// (n_traces, 1, n_samples) volume — the same contract crossplot_core uses —
// and run one frozen kernel through the science SDK.
bool run_section_kernel(const std::string& kernel_id,
                        std::span<const float> plane, std::int64_t n_traces,
                        std::int64_t n_samples, double sample_interval_s,
                        std::vector<float>& out, std::string& diagnostic) {
    static pwb::science::AlgorithmRegistry registry;
    static const bool registered = [] {
        const auto report = pwb::seismic_attributes::register_seismic_attributes(
            registry, "closure-seismic-07");
        return !report.registered_ids.empty();
    }();
    if (!registered) {
        diagnostic = "seismic attribute kernels failed to register";
        return false;
    }
    pwb::science::IAlgorithm* algorithm = registry.find(kernel_id);
    if (algorithm == nullptr) {
        diagnostic = "algorithm not registered: " + kernel_id;
        return false;
    }
    auto holder = std::make_shared<std::vector<float>>(plane.begin(), plane.end());
    pwb::science::VolumeView view;
    view.data = holder->data();
    view.shape = {n_traces, 1, n_samples};
    view.strides = {0, 0, 0}; // packed C-order (trace-major identity layout)
    view.lifetime = holder;

    pwb::science::AlgorithmRequestV1 request;
    request.algorithm_id = kernel_id;
    request.algorithm_version = algorithm->descriptor().version;
    request.params_json = {{"sample_interval", std::to_string(sample_interval_s)}};
    request.input_volumes.push_back(view);
    pwb::science::Result<pwb::science::AlgorithmResultV1> result =
        algorithm->run(request, nullptr, {});
    if (!result.has_value()) {
        diagnostic = "kernel failed: " + kernel_id;
        if (result.is_error() && !result.error().diagnostics.empty()) {
            diagnostic += " (" + result.error().diagnostics.front().code + ")";
        }
        return false;
    }
    const auto& produced = result.value().outputs;
    if (produced.size() != 1 ||
        produced.front().volume.size() != static_cast<std::int64_t>(plane.size())) {
        diagnostic = "kernel output shape mismatch: " + kernel_id;
        return false;
    }
    out.assign(produced.front().volume.data,
               produced.front().volume.data + plane.size());
    return true;
}

} // namespace

struct SeismicPageBinding::Impl {
    SeismicPageInstall install;
    std::unique_ptr<RealSeismicViewBinding> binding;
    std::string volume_path;
    pwb::viz::VolumeGeometryV1 geometry;
    std::string display_mode_token = pwb::ui_wellseis::kDisplayModeVd;
    std::string unavailable_reason;
    // Last computed attribute planes (most recent last) — the RGB fusion
    // channel source: R = third-last, G = second-last, B = last. Each entry
    // carries the (volume, slice) identity it was computed for; fusion
    // refuses to mix channels that are not registered to the CURRENT
    // displayed plane (a stale channel is never painted over a new body).
    struct AttributePlane {
        std::string label;
        std::string volume_id;
        VolumeAxis axis{VolumeAxis::inline_};
        std::int64_t index{0};
        std::uint64_t revision{0};
        std::vector<float> values;
    };
    std::deque<AttributePlane> attribute_history;

    [[nodiscard]] Viewer* viewer() const {
        if (binding == nullptr) {
            return nullptr;
        }
        return static_cast<Viewer*>(binding->widget());
    }

    void note_unavailable(const std::string& reason) {
        unavailable_reason = reason;
        if (install.page != nullptr && install.page->view_panel() != nullptr) {
            install.page->view_panel()->set_unavailable_reason(reason);
        }
    }

    void open_resource(const pwb::ui_workers::ResourceSlice& resource) {
        if (binding != nullptr) {
            binding->shutdown();
            binding.reset();
        }
        volume_path.clear();
        attribute_history.clear(); // channels of the old body never carry over
        if (install.page == nullptr || install.page->view_panel() == nullptr) {
            return;
        }
        auto* panel = install.page->view_panel();
        if (install.volumes == nullptr) {
            panel->set_view(SeismicViewSeam{nullptr, "no seismic volume service bound"});
            panel->set_volume_shape(std::nullopt);
            return;
        }
        const std::filesystem::path path(resource.path);
        std::string error;
        pwb::seismic_service::OpenedVolume opened;
        if (path.extension().string() == ".pwbvol") {
            opened = install.volumes->open_pwbvol(path, &error);
        } else {
            // .sgy / .segy and unknown suffixes: SEG-Y is the survey default.
            opened = install.volumes->open_segy(path, &error);
        }
        if (opened.volume == nullptr || !error.empty()) {
            const std::string reason =
                error.empty() ? "volume open failed" : error;
            note_unavailable(reason);
            panel->set_view(SeismicViewSeam{nullptr, reason});
            panel->set_volume_shape(std::nullopt);
            return;
        }
        geometry = opened.volume->geometry();
        volume_path = resource.path;
        const pwb::seismic_viewer::VolumeIdentity identity{resource.path, 0};
        binding = std::make_unique<RealSeismicViewBinding>();
        static_cast<Viewer*>(binding->widget())
            ->set_volume(opened.volume, identity, 0);
        // The requested mode rides across the source swap (a fresh viewer
        // never silently drifts back to VD while the toolbar says wiggle).
        if (display_mode_token != pwb::ui_wellseis::kDisplayModeVd) {
            binding->apply_display_mode(display_mode_token);
        }
        panel->set_view(SeismicViewSeam{binding->widget(), ""});
        panel->set_volume_shape(std::optional<std::array<std::int64_t, 3>>{
            geometry.shape});
    }

    void on_attribute(const QString& label_raw) {
        Viewer* widget = viewer();
        if (widget == nullptr) {
            note_unavailable("未绑定地震数据体，无法计算属性");
            return;
        }
        const std::string label = label_raw.toStdString();
        const Viewer::RetainedPlane plane = widget->retained_plane();
        if (plane.values.empty()) {
            note_unavailable("当前无已显示切片，无法计算属性");
            return;
        }
        // Section views only: rows are traces, cols are samples (both
        // section orientations); the map view has no sample axis to run
        // single-trace chains along.
        if (plane.axis == VolumeAxis::sample) {
            note_unavailable("属性在平面（切片）视图不可用，请切换到剖面视图");
            return;
        }

        const std::string kernel = pwb::ui_wellseis::kernel_for_label(label);
        if (kernel.empty() && label != kRgbFusionLabel) {
            note_unavailable("未知属性：" + label);
            return;
        }
        // 振幅 leaf: restore the raw amplitude display. This is the user
        // reachability path for clear_attribute_view() — without it the
        // export refusal ("请先清除属性视图") pointed at an action no menu
        // or panel entry ever exposed.
        if (kernel == "amplitude") {
            if (widget->attribute_active()) {
                widget->clear_attribute_view();
            }
            note_unavailable("");
            return;
        }

        // Sample interval for the kernels (seconds). Depth volumes decline
        // the one time-based kernel instead of producing nonsense units.
        double sample_interval_s = 1.0; // kernel default; envelope/rms/phase
                                        // never read it
        if (geometry.unit == "ms") {
            sample_interval_s = std::abs(geometry.step[2]) / 1000.0;
        } else if (geometry.unit == "s") {
            sample_interval_s = std::abs(geometry.step[2]);
        } else if (kernel == "instantaneous_frequency" ||
                   kernel == "sweetness") {
            // sweetness = envelope / sqrt(instantaneous frequency): the
            // frequency chain needs a time axis exactly like the freq
            // kernel (round-2 review — it silently produced wrong-unit
            // values on depth volumes before this gate).
            note_unavailable("该属性需要时间轴数据体（ms/s），当前体为深度域");
            return;
        }

        if (label == kRgbFusionLabel) {
            if (attribute_history.size() < 3) {
                note_unavailable("RGB 融合需要先计算至少三个属性平面");
                return;
            }
            // Registration check: every channel must have been computed for
            // exactly the CURRENT (volume, axis, slice, revision) — a fusion
            // of planes from another body or slice is refused, never shown.
            const std::size_t size = attribute_history.size();
            for (std::size_t k = size - 3;
                 k < attribute_history.size(); ++k) {
                const AttributePlane& channel = attribute_history[k];
                if (channel.volume_id != volume_path || channel.axis != plane.axis ||
                    channel.index != plane.index ||
                    channel.revision != plane.revision) {
                    note_unavailable("RGB 融合通道与当前切片不配准，请重新计算属性");
                    return;
                }
            }
            // R/G/B = oldest..newest of the three registered planes; the
            // viewer fuses (attribute_fusion_core::fuse_rgb) and pins the
            // result as the displayed image.
            const AttributePlane& r = attribute_history[size - 3];
            const AttributePlane& g = attribute_history[size - 2];
            const AttributePlane& b = attribute_history[size - 1];
            if (!widget->set_rgb_fusion(r.values, g.values, b.values,
                                        plane.rows, plane.cols,
                                        99.0, kRgbFusionLabel)) {
                note_unavailable("RGB 融合失败：" + widget->last_diagnostic());
            }
            return;
        }

        if (!is_section_kernel(kernel)) {
            note_unavailable("该属性需三维邻域计算，2D 剖面暂不支持，请使用"
                             "「计算属性」进行体级计算：" + label);
            return;
        }
        std::vector<float> attribute;
        std::string diagnostic;
        // The science registry ids carry the "seismic." prefix
        // (attributes.cpp: {"seismic.envelope", ...}).
        if (!run_section_kernel("seismic." + kernel, plane.values, plane.rows,
                                plane.cols, sample_interval_s, attribute,
                                diagnostic)) {
            note_unavailable("属性计算失败：" + diagnostic);
            return;
        }
        if (!widget->set_attribute_plane(attribute, plane.rows, plane.cols,
                                         widget->color_map(), label)) {
            note_unavailable("属性显示失败：" + widget->last_diagnostic());
            return;
        }
        attribute_history.push_back(AttributePlane{
            label, volume_path, plane.axis, plane.index, plane.revision,
            std::move(attribute)});
        while (attribute_history.size() > 3) {
            attribute_history.pop_front();
        }
    }
};

SeismicPageBinding::SeismicPageBinding(const SeismicPageInstall& install,
                                       QObject* parent)
    : QObject(parent), impl_(std::make_unique<Impl>()) {
    impl_->install = install;
    if (install.page == nullptr) {
        return;
    }
    pwb::ui_wellseis::qt::SeismicViewPanel* panel = install.page->view_panel();
    if (panel == nullptr) {
        return;
    }
    SeismicViewHooks hooks;
    hooks.update_state = [](const pwb::ui_wellseis::PredictionTaskSlice*,
                            const pwb::ui_wellseis::ProjectSlice*) {};
    hooks.show_resource =
        [this](const pwb::ui_workers::ResourceSlice& resource,
               const pwb::ui_wellseis::ProjectSlice*) {
            impl_->open_resource(resource);
            return impl_->binding != nullptr;
        };
    hooks.set_display_mode = [this](const QString& mode) {
        impl_->display_mode_token = mode.toStdString();
        if (impl_->binding != nullptr) {
            impl_->binding->apply_display_mode(impl_->display_mode_token);
        }
    };
    hooks.display_mode = [this]() {
        return QString::fromStdString(impl_->display_mode_token);
    };
    hooks.set_attribute_label = [](const QString&) {};
    hooks.attribute_label = []() { return QString(); };
    hooks.set_well_tie_enabled = [](bool) {};
    hooks.set_project_path = [](const QString&) {};
    hooks.shutdown = [this]() {
        if (impl_->binding != nullptr) {
            impl_->binding->shutdown();
        }
    };
    panel->set_hooks(hooks);

    if (install.page->attribute_panel() != nullptr) {
        QObject::connect(
            install.page->attribute_panel(),
            &pwb::ui_wellseis::qt::SeismicAttributePanel::attribute_changed, this,
            [this](const QString& label) { impl_->on_attribute(label); });
    }
}

SeismicPageBinding::~SeismicPageBinding() = default;

std::string SeismicPageBinding::bound_volume_path() const {
    return impl_->volume_path;
}

std::string SeismicPageBinding::last_unavailable_reason() const {
    return impl_->unavailable_reason;
}

void SeismicPageBinding::apply_attribute(const QString& label) {
    impl_->on_attribute(label);
}

SeismicPageBinding* install_seismic_page(const SeismicPageInstall& install) {
    if (install.page == nullptr) {
        return nullptr;
    }
    return new SeismicPageBinding(install, install.page);
}

} // namespace pwb::closure_seismic
