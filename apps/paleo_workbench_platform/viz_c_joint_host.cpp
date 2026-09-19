// viz_c_joint_host.cpp — real joint host over the V4 scene core.
// 06 closure: every cold-tile read (fence strips + the active time
// plane) runs on the JobCenter worker; the GUI applies finished payloads
// behind generation guards, so rapid slice scrubbing, window teardown,
// cancellation and project switches can never block or cross the wire.
#ifdef PWB_WITH_UI_WELLSEIS

#include "viz_c_joint_host.hpp"

#include <QSettings>
#include <QWidget>

#include <pwb/seismic_service/tiled_volume.hpp>
#include <pwb/geo3d_viz/joint/color_scales.hpp>
#include <pwb/geo3d_viz/joint/segy_survey.hpp>

#include "viz_c_joint_volume.hpp"
#include "viz_c_time_map.hpp"


namespace pwb::app::viz_c {

using pwb::geo3d_viz::joint::OrthogonalSliceState;
using pwb::geo3d_viz::joint::TimeSliceState;
using pwb::geo3d_viz::joint::VerticalDomain;
using pwb::geo3d_viz::joint::WellSeismicScene;
using pwb::seismic_service::SeismicVolumeService;
using pwb::ui_wellseis::qt::JointHostController;
using pwb::ui_wellseis::qt::JointSceneSnapshot;

namespace {
constexpr const char* kLegacyStateKey = "viz_c/joint_state";
constexpr const char* kStateGroup = "viz_c/joint_states";

struct VolumeOpenOutcome {
    std::string error;
    // Copyable/light pieces cross the queued hop; the heavy volume is
    // re-referenced through the shared service cache on the GUI side.
    std::string storage;
    std::int64_t ni = 0;
    std::int64_t nc = 0;
    std::int64_t ns = 0;
};

// QSettings keys must not carry arbitrary project paths verbatim ( '/'
// would silently nest groups); hex-escape every non-safe byte so the
// mapping stays injective and stable.
QString identity_key_suffix(const std::string& identity) {
    static const char* kHex = "0123456789ABCDEF";
    QString out;
    for (const char c : identity) {
        const unsigned char b = static_cast<unsigned char>(c);
        if ((b >= 'a' && b <= 'z') || (b >= 'A' && b <= 'Z') ||
            (b >= '0' && b <= '9') || b == '_' || b == '-') {
            out.append(QLatin1Char(static_cast<char>(b)));
        } else {
            out.append(QLatin1Char('%'));
            out.append(QLatin1Char(kHex[b >> 4]));
            out.append(QLatin1Char(kHex[b & 0xF]));
        }
    }
    return out;
}

QString scoped_state_key(const std::string& identity) {
    if (identity.empty()) return QString::fromLatin1(kLegacyStateKey);
    return QString::fromLatin1(kStateGroup) + QLatin1Char('/') +
           identity_key_suffix(identity);
}

// Equality of the load-bearing prep inputs (lifetime pointers excluded —
// they are identity, not behaviour).
bool prep_requests_equal(const JointPrepRequest& a, const JointPrepRequest& b) {
    if (a.generation != b.generation || a.access.get() != b.access.get() ||
        a.slice_native_sample != b.slice_native_sample ||
        a.color_scale != b.color_scale || a.n_along != b.n_along ||
        a.sample_axis != b.sample_axis ||
        a.registration.has_value() != b.registration.has_value() ||
        a.fences.size() != b.fences.size()) {
        return false;
    }
    if (a.registration.has_value()) {
        const auto& ra = *a.registration;
        const auto& rb = *b.registration;
        if (ra.strides() != rb.strides() ||
            ra.n_inline() != rb.n_inline() ||
            ra.n_crossline() != rb.n_crossline() ||
            ra.n_sample() != rb.n_sample()) {
            return false;
        }
    }
    for (std::size_t i = 0; i < a.fences.size(); ++i) {
        const auto& fa = a.fences[i];
        const auto& fb = b.fences[i];
        if (fa.id != fb.id || fa.vertices_xy != fb.vertices_xy) {
            return false;
        }
    }
    return true;
}
}  // namespace

VizCJointHost::VizCJointHost(
    JobCenter& job_center,
    pwb::geo3d_viz::Geo3DWorkspaceController* dock_controller,
    pwb::geo3d_viz::Geo3DViewportWidget* viewport, QObject* parent)
    : JointHostController(parent),
      job_center_(job_center),
      dock_controller_(dock_controller),
      viewport_(viewport) {}

VizCJointHost::~VizCJointHost() {
    // The time map can be reparented into a consuming page (different
    // parent tree); it must never keep a dangling scene pointer.
    if (time_map_ != nullptr) {
        time_map_->set_scene(nullptr);
    }
}

bool VizCJointHost::open_volume(
    const std::shared_ptr<SeismicVolumeService>& service,
    const std::filesystem::path& path, QString* error) {
    if (service == nullptr) {
        if (error != nullptr) {
            *error = tr("seismic service unavailable");
        }
        return false;
    }
    ++volume_generation_;
    const std::uint64_t generation = volume_generation_;
    auto& owner = job_center_.make_owner(this);
    volume_owner_ = &owner;

    struct StagedOpen {
        std::shared_ptr<pwb::viz::ISeismicVolume> volume;
        std::shared_ptr<const void> lifetime;
        pwb::seismic_io::VolumeDescriptor descriptor;
        std::string error;
    };

    pwb::job::JobSpec spec;
    spec.kind = "background.io";
    spec.title = "井震联合体打开";
    // compute(worker): metadata-only inspect through the tiled service
    // (O(1) open, no sample reads). All sample reads for this volume —
    // open and every later slice/fence prep — run on the job worker.
    spec.run = [service, path](pwb::job::JobContext& ctx) -> std::any {
        auto staged = std::make_shared<StagedOpen>();
        ctx.check_cancelled();
        std::string open_error;
        auto opened = service->open_pwbvol(path, &open_error);
        if (opened.volume == nullptr) {
            opened = service->open_segy(path, &open_error);
        }
        if (opened.volume == nullptr) {
            staged->error = open_error;
            return staged;
        }
        staged->volume = opened.volume;
        staged->lifetime = opened.volume->lifetime();
        staged->descriptor = opened.descriptor;
        return staged;
    };
    owner.start(
        job_center_.scheduler(), std::move(spec),
        [this, generation, path](const pwb::job::qtbridge::JobOutcome& outcome) {
            // Only the owner this callback belongs to may clear the slot
            // (a superseded open may already have installed a new one).
            if (volume_owner_ != nullptr && generation == volume_generation_) {
                volume_owner_ = nullptr;
            }
            if (outcome.state == pwb::job::JobState::cancelled ||
                generation != volume_generation_) {
                // Superseded or cancelled: nothing was wired into the
                // scene; the late/cancelled result is dropped honestly.
                return;
            }
            // Pointer form: a failed outcome carries an empty any (a
            // value-form cast would throw on the GUI thread).
            const auto staged =
                std::any_cast<std::shared_ptr<StagedOpen>>(
                    &outcome.result);
            if (staged == nullptr || *staged == nullptr ||
                (*staged)->volume == nullptr) {
                engine_error_ =
                    staged != nullptr && *staged != nullptr
                        ? (*staged)->error
                        : outcome.error;
                emit_status(tr("联合体打开失败：%1")
                                .arg(QString::fromStdString(engine_error_)));
                return;
            }
            try {
                namespace joint = pwb::geo3d_viz::joint;
                // Fail-closed: no bin grid / non-TWT axis refuses the
                // survey (never metres-as-milliseconds).
                joint::SurveySpec survey =
                    joint::survey_from_volume_descriptor(
                        (*staged)->descriptor);
                scene_.set_survey(std::move(survey));
                scene_.set_volume_access(
                    std::make_shared<TiledVolumeAccess>((*staged)->volume,
                                                        (*staged)->lifetime));
            } catch (const std::exception& ex) {
                engine_error_ = ex.what();
                emit_status(tr("联合体标定失败：%1").arg(
                    QString::fromStdString(engine_error_)));
                return;
            }
            engine_error_.clear();
            loaded_paths_.clear();
            loaded_paths_.push_back(path.generic_string());
            install_scene_transform();
            assemble_joint_objects();
            push_scene_to_widget();
            save_state();
            emit scene_updated();
            emit_status(tr("联合体已加载：%1").arg(
                QString::fromStdString(path.filename().generic_string())));
        });
    return true;
}

void VizCJointHost::set_wells(
    std::vector<pwb::geo3d_viz::joint::WellHead> wells,
    std::map<std::string, pwb::geo3d_viz::joint::TimeDepthTable> td_tables) {
    scene_.set_wells(std::move(wells), std::move(td_tables));
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

// ---- project identity / persistence --------------------------------------

void VizCJointHost::set_project_identity(const std::string& identity) {
    if (project_identity_ == identity) return;
    // The previous project's scene state is persisted under its own key
    // before the switch (best-effort: a failing save must not block the
    // rebind), then the new project's state becomes authoritative.
    save_state();
    project_identity_ = identity;
    // Invalidate the async pipeline for the old project FIRST: the
    // generation bump makes any in-flight or queued prep payload drop on
    // arrival (a finished job can never re-apply the old project's
    // plane/strips), and the applied/applied-key state is cleared so
    // request_prep() re-reads for the new project from scratch.
    ++volume_generation_;
    prepared_ = JointPrepData{};
    prep_applied_.reset();
    if (time_map_ != nullptr) {
        time_map_->set_prepared_slice({}, 0, 0, -1);
    }
    // The persisted joint state carries fences/slices/domain only —
    // wells, the volume access and the loaded-path hints belong to the
    // old project and are dropped in BOTH branches (Python set_project
    // parity: the binder re-populates the new project's assets right
    // after the switch).
    scene_.clear_fences();
    try {
        scene_.restore_orthogonal_slice_state(OrthogonalSliceState{});
    } catch (const std::invalid_argument&) {
        // Degraded slice state: leave the cleared fences in place.
    }
    scene_.set_wells({}, {});
    scene_.set_volume_access(nullptr);
    loaded_paths_.clear();
    QSettings settings;
    if (!settings.value(scoped_state_key(identity)).toString().isEmpty()) {
        restore_state();
        return;
    }
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::save_state() {
    QSettings settings;
    settings.setValue(scoped_state_key(project_identity_),
                      QString::fromStdString(scene_.joint_state_to_json()));
}

void VizCJointHost::restore_state() {
    QSettings settings;
    const QString raw =
        settings.value(scoped_state_key(project_identity_)).toString();
    if (raw.isEmpty()) return;
    std::vector<std::string> fences;
    if (scene_.restore_joint_state(raw.toStdString(), &fences)) {
        assemble_joint_objects();
        push_scene_to_widget();
        emit scene_updated();
    }
}

// ---- multi-fence management ------------------------------------------------

void VizCJointHost::activate_fence(const std::string& fence_id) {
    scene_.set_active_fence(fence_id);
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::set_fence_visible(const std::string& fence_id,
                                      bool visible) {
    scene_.set_fence_visible(fence_id, visible);
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::add_fence_vertices(
    const std::vector<std::array<double, 2>>& vertices_xy,
    const std::string& name) {
    try {
        pwb::geo3d_viz::joint::FenceSection fence(name, vertices_xy);
        scene_.add_fence(std::move(fence), true);
    } catch (const std::exception& ex) {
        emit_status(tr("无法建立手绘 fence：%1").arg(
            QString::fromStdString(ex.what())));
        return;
    }
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

// ---- JointHostController -------------------------------------------------

bool VizCJointHost::shutdown(int wait_ms) {
    bool drained = true;
    shutdown_done_ = true;
    if (volume_owner_ != nullptr) {
        drained = volume_owner_->shutdown(wait_ms) && drained;
        volume_owner_ = nullptr;
    }
    if (prep_owner_ != nullptr) {
        drained = prep_owner_->shutdown(wait_ms) && drained;
        prep_owner_ = nullptr;
        prep_running_ = false;
    }
    return drained;
}

void VizCJointHost::reload() {
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

JointSceneSnapshot VizCJointHost::scene_snapshot() const {
    JointSceneSnapshot snapshot;
    snapshot.has_scene = true;
    snapshot.depth_domain = scene_.vertical_domain() == VerticalDomain::Depth;
    snapshot.depth_available = scene_.depth_available();
    snapshot.slice_state_warning = scene_.slice_state_warning();
    for (const auto& id : scene_.fence_well_ids()) {
        snapshot.fence_well_ids.push_back(id);
    }
    if (const std::string* id = scene_.active_fence_id()) {
        snapshot.active_fence_id = *id;
    }
    for (const auto& fence : scene_.fences()) {
        snapshot.fences.push_back({fence.id, fence.name, fence.visible});
    }
    for (const auto& presentation : scene_.well_presentations()) {
        snapshot.well_presentations.push_back(
            {presentation.id, presentation.display_name,
             presentation.visible});
    }
    const auto& state = scene_.orthogonal_slice_state();
    snapshot.inline_index = state.inline_index.has_value()
                                ? std::optional<int>(
                                      static_cast<int>(*state.inline_index))
                                : std::nullopt;
    snapshot.crossline_index =
        state.crossline_index.has_value()
            ? std::optional<int>(static_cast<int>(*state.crossline_index))
            : std::nullopt;
    if (const auto* registration = scene_.registration()) {
        if (state.inline_index.has_value()) {
            snapshot.inline_number =
                registration->volume_idx_to_il_xl(
                    static_cast<double>(*state.inline_index), 0.0)
                    .first;
        }
        if (state.crossline_index.has_value()) {
            snapshot.crossline_number =
                registration->volume_idx_to_il_xl(
                    0.0, static_cast<double>(*state.crossline_index))
                    .second;
        }
        snapshot.n_inline =
            static_cast<int>(registration->n_inline());
        snapshot.n_crossline =
            static_cast<int>(registration->n_crossline());
        snapshot.time_min_ms = registration->survey().t0_ms;
        snapshot.time_max_ms =
            registration->survey().t0_ms +
            static_cast<double>(registration->survey().n_samples - 1) *
                registration->survey().dt_ms;
    }
    for (const auto& slice : state.time_slices) {
        snapshot.time_slices.push_back({slice.time_ms, slice.visible});
    }
    snapshot.active_time_ms = state.active_time_ms;
    snapshot.time_opacity = state.time_opacity;
    return snapshot;
}

bool VizCJointHost::has_scene() const { return true; }

std::string VizCJointHost::engine_error() const { return engine_error_; }

std::vector<std::pair<std::string, std::string>>
VizCJointHost::well_options() const {
    std::vector<std::pair<std::string, std::string>> options;
    for (const auto& presentation : scene_.well_presentations()) {
        options.emplace_back(presentation.id, presentation.display_name);
    }
    return options;
}

bool VizCJointHost::set_vertical_domain(const std::string& domain) {
    try {
        scene_.set_vertical_domain(domain == "depth" ||
                                   domain.rfind("depth", 0) == 0
                                       ? VerticalDomain::Depth
                                       : VerticalDomain::Time);
    } catch (const std::invalid_argument&) {
        return false;  // refused: no time-depth transform (fail-closed)
    }
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
    return true;
}

void VizCJointHost::add_well_to_well_fence(const std::string& well_a,
                                           const std::string& well_b,
                                           const std::string& name) {
    try {
        scene_.add_well_to_well_fence({well_a, well_b},
                                      name.empty() ? "Wells" : name);
    } catch (const std::exception& ex) {
        emit_status(tr("无法建立井间 fence：%1").arg(
            QString::fromStdString(ex.what())));
        return;
    }
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::delete_active_fence() {
    scene_.remove_active_fence();
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::set_orthogonal_slice_indices(
    std::optional<int> inline_index, std::optional<int> crossline_index) {
    scene_.set_orthogonal_slice_indices(
        inline_index.has_value()
            ? std::optional<std::int64_t>(static_cast<std::int64_t>(
                  *inline_index))
            : std::nullopt,
        crossline_index.has_value()
            ? std::optional<std::int64_t>(static_cast<std::int64_t>(
                  *crossline_index))
            : std::nullopt);
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::restore_orthogonal_slice_state(
    std::optional<int> inline_index, std::optional<int> crossline_index,
    const std::vector<pwb::ui_wellseis::qt::JointTimeSliceEntry>& time_slices,
    std::optional<double> active_time_ms, double time_opacity) {
    std::vector<TimeSliceState> slices;
    slices.reserve(time_slices.size());
    for (const auto& entry : time_slices) {
        try {
            slices.emplace_back(entry.time_ms, entry.visible);
        } catch (const std::invalid_argument&) {
            // Per-entry degradation: a bad stored slice is skipped.
        }
    }
    try {
        scene_.restore_orthogonal_slice_state(OrthogonalSliceState(
            inline_index.has_value()
                ? std::optional<std::int64_t>(
                      static_cast<std::int64_t>(*inline_index))
                : std::nullopt,
            crossline_index.has_value()
                ? std::optional<std::int64_t>(
                      static_cast<std::int64_t>(*crossline_index))
                : std::nullopt,
            std::move(slices), active_time_ms, time_opacity));
    } catch (const std::invalid_argument&) {
        return;
    }
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

bool VizCJointHost::apply_slice_line_numbers(double inline_number,
                                             double crossline_number) {
    const auto* registration = scene_.registration();
    if (registration == nullptr) return false;
    const auto [vi, vx] =
        registration->il_xl_to_volume_idx(inline_number, crossline_number);
    set_orthogonal_slice_indices(
        static_cast<int>(std::llround(std::max(0.0, vi))),
        static_cast<int>(std::llround(std::max(0.0, vx))));
    return true;
}

void VizCJointHost::add_time_slice(double time_ms) {
    try {
        scene_.add_time_slice(time_ms);
    } catch (const std::invalid_argument& ex) {
        emit_status(QString::fromStdString(ex.what()));
        return;
    }
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::remove_time_slice(double time_ms) {
    scene_.remove_time_slice(time_ms);
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::set_time_slice_visible(double time_ms, bool visible) {
    try {
        scene_.set_time_slice_visible(time_ms, visible);
    } catch (const std::out_of_range&) {
        return;
    }
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::set_active_time_slice(double time_ms) {
    try {
        scene_.set_active_time_slice(time_ms);
    } catch (const std::out_of_range&) {
        return;
    }
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::set_time_opacity(double fraction) {
    scene_.set_time_slice_opacity(fraction);
    assemble_joint_objects();
    push_scene_to_widget();
    emit scene_updated();
}

void VizCJointHost::set_3d_mode(const std::string& mode) {
    // planes|volume: the assembly always builds slices + curtains; the
    // mode toggles the curtain visibility (honest no-op names recorded).
    if (viewport_ == nullptr) return;
    auto& manager = viewport_->scene_manager();
    const bool planes_only = mode == "planes";
    for (const std::string& name : manager.names()) {
        if (name.rfind("joint:fence:", 0) == 0) {
            manager.set_visibility(name, !planes_only);
        }
    }
    emit scene_updated();
}

void VizCJointHost::set_color_scales(const std::string& seismic_scale,
                                     const std::string& gr_scale) {
    try {
        scene_.set_display_settings(
            pwb::geo3d_viz::joint::JointDisplaySettings(
                seismic_scale, gr_scale,
                scene_.display_settings().well_width_px));
    } catch (const std::invalid_argument&) {
        return;
    }
    assemble_joint_objects();
    push_scene_to_widget();
    // No scene_updated here (Python parity: display settings are applied
    // straight onto the scene/widgets). The page's scene_updated handler
    // calls this setter — re-emitting would recurse forever.
}

void VizCJointHost::set_well_width(int px) {
    try {
        scene_.set_display_settings(
            pwb::geo3d_viz::joint::JointDisplaySettings(
                scene_.display_settings().seismic_color_scale,
                scene_.display_settings().gr_color_scale, px));
    } catch (const std::invalid_argument&) {
        return;
    }
    assemble_joint_objects();
    // No scene_updated (see set_color_scales).
}

void VizCJointHost::set_well_visibility(const std::string& well_id,
                                        bool visible) {
    try {
        scene_.set_well_visibility(well_id, visible);
    } catch (const std::out_of_range&) {
        return;
    }
    assemble_joint_objects();
    // No scene_updated (Python parity: visibility pushes come FROM the
    // page's scene_updated handler — re-emitting would recurse forever).
}

void VizCJointHost::set_layer_visibility(const std::string& layer_name,
                                         bool visible) {
    if (viewport_ == nullptr) return;
    auto& manager = viewport_->scene_manager();
    const std::string object =
        layer_name.rfind("joint:", 0) == 0 ? layer_name : "joint:" + layer_name;
    try {
        manager.set_visibility(object, visible);
    } catch (const std::exception&) {
        // Unknown layer names degrade honestly (no scene change).
    }
}

void VizCJointHost::apply_camera_preset(const std::string& preset) {
    if (viewport_ == nullptr) return;
    const pwb::geo3d_viz::CameraPose pose =
        preset == "top_down"
            ? pwb::geo3d_viz::OrbitCamera::top_down_preset()
        : preset == "perspective"
            ? pwb::geo3d_viz::OrbitCamera::perspective_preset()
            : pwb::geo3d_viz::OrbitCamera::default_pose();
    viewport_->camera().set_pose(pose);
    viewport_->update();
}

std::string VizCJointHost::well_identity_asset_id() const { return {}; }

std::map<std::string, std::string> VizCJointHost::well_identity_map() const {
    return {};
}

std::map<std::string, std::string> VizCJointHost::path_hints() const {
    std::map<std::string, std::string> hints;
    if (!loaded_paths_.empty()) {
        std::string joined;
        for (const std::string& path : loaded_paths_) {
            if (!joined.empty()) joined.push_back('|');
            joined += path;
        }
        hints["segy"] = joined;
    }
    return hints;
}

std::vector<std::string> VizCJointHost::loaded_data_paths() const {
    return loaded_paths_;
}

bool VizCJointHost::highlight_well(const std::string& well_name) {
    // Highlight the matching joint well trajectory (by presentation
    // display name or id); reports the pick through well_picked.
    for (const auto& presentation : scene_.well_presentations()) {
        if (presentation.display_name == well_name || presentation.id == well_name) {
            if (viewport_ != nullptr) {
                auto& manager = viewport_->scene_manager();
                try {
                    manager.set_color("joint:well:" + presentation.id,
                                      {1.0f, 0.98f, 0.0f, 1.0f});
                } catch (const std::exception&) {
                    // Well not assembled (no TD table) — still report.
                }
            }
            emit well_picked(QString::fromStdString(well_name));
            return true;
        }
    }
    return false;
}

bool VizCJointHost::focus_position(int il, int xl,
                                   std::optional<double> twt) {
    const auto* registration = scene_.registration();
    if (registration == nullptr) return false;
    const auto [vi, vx] = registration->il_xl_to_volume_idx(
        static_cast<double>(il), static_cast<double>(xl));
    double vt = 0.0;
    if (twt.has_value()) {
        vt = registration->time_ms_to_sample_idx(*twt);
    }
    if (viewport_ == nullptr) return false;
    viewport_->camera().set_center({vi, vx, vt});
    viewport_->update();
    return true;
}

QWidget* VizCJointHost::joint_widget(QWidget* parent) {
    // Real engine surface: the 2D time map bound to the joint scene.
    // The 3D viewport lives in the geo3d dock (shared render root).
    if (time_map_ == nullptr) {
        time_map_ = new VizCTimeSliceMap(parent);
        time_map_->set_scene(&scene_);
    }
    return time_map_;
}

void VizCJointHost::push_scene_to_widget() {
    if (time_map_ != nullptr) {
        time_map_->refresh();
    }
    request_prep();
}

// ---- async prep pipeline ----------------------------------------------------

JointPrepRequest VizCJointHost::current_prep_request() const {
    JointPrepRequest request;
    request.generation = volume_generation_;
    // Refcount-safe shared view; the worker only reads through it.
    request.access = scene_.volume_access_shared();
    const auto* registration = scene_.registration();
    if (registration != nullptr) {
        request.registration = *registration;
    }
    const auto* survey = scene_.survey();
    if (survey != nullptr) request.survey = *survey;
    for (const auto& fence : scene_.fences()) {
        if (fence.visible) request.fences.push_back(fence);
    }
    request.n_along = 128;
    // The extraction saxis (active-domain units), mirroring the scene's
    // own extract path (full survey range, stride-aware spacing).
    const std::int64_t nt =
        scene_.volume_access() != nullptr ? scene_.volume_access()->shape()[2] : 0;
    request.sample_axis.reserve(static_cast<std::size_t>(std::max<std::int64_t>(nt, 0)));
    const std::int64_t stride_t =
        registration != nullptr ? registration->strides()[2] : 1;
    for (std::int64_t t = 0; t < nt; ++t) {
        request.sample_axis.push_back(
            request.survey.t0_ms +
            static_cast<double>(t) *
                (request.survey.dt_ms * static_cast<double>(stride_t)));
    }
    if (scene_.vertical_domain() == VerticalDomain::Depth) {
        request.sample_axis =
            scene_.depth_transform().time_ms_to_depth_m(request.sample_axis);
    }
    request.color_scale = scene_.display_settings().seismic_color_scale;
    if (scene_.vertical_domain() == VerticalDomain::Time) {
        if (const auto render_state = scene_.orthogonal_slice_render_state();
            render_state.has_value()) {
            request.slice_native_sample = std::get<3>(*render_state);
        }
    }
    return request;
}

void VizCJointHost::request_prep() {
    if (shutdown_done_) return;  // no post-shutdown resurrection
    if (scene_.volume_access() == nullptr) return;  // nothing to read yet
    JointPrepRequest current = current_prep_request();
    if (prep_running_ && prep_in_flight_.has_value()) {
        if (prep_requests_equal(*prep_in_flight_, current)) return;
        // Cooperative cancel: the body stops at its next safe point; the
        // finished callback drops the stale payload and re-issues.
        prep_owner_->cancel();
        return;
    }
    if (prep_applied_ && prep_requests_equal(*prep_applied_, current)) {
        return;  // up to date
    }
    // One owner per host is reused once its job reaches terminal; each
    // make_owner() registers a process-lifetime entry in the JobCenter,
    // so per-request owners would leak it on every slice scrub.
    if (prep_owner_ == nullptr) {
        prep_owner_ = &job_center_.make_owner(this);
    }
    const std::uint64_t generation = current.generation;
    auto request = std::make_shared<JointPrepRequest>(std::move(current));
    prep_in_flight_ = *request;
    prep_running_ = true;

    pwb::job::JobSpec spec;
    spec.kind = "background.io";
    spec.title = "联合切片/帘幕读取";
    spec.run = [request](pwb::job::JobContext& ctx) -> std::any {
        auto data = std::make_shared<JointPrepData>();
        try {
            const auto& volume = *request->access;
            for (const auto& fence : request->fences) {
                ctx.check_cancelled();
                data->strips.push_back(
                    {fence.id,
                     pwb::geo3d_viz::joint::extract_fence_strip(
                         volume, fence, request->survey, request->n_along,
                         request->sample_axis,
                         request->registration ? &*request->registration
                                               : nullptr)});
            }
            if (request->slice_native_sample >= 0) {
                ctx.check_cancelled();
                const auto shape = volume.shape();
                const std::vector<float> plane =
                    volume.slice_time(request->slice_native_sample);
                data->slice_rgba = pwb::geo3d_viz::joint::colorize_amplitude(
                    plane, request->color_scale);
                data->n_inline = shape[0];
                data->n_crossline = shape[1];
                data->active_sample = request->slice_native_sample;
            }
        } catch (const pwb::job::JobCancelled&) {
            throw;  // honest cancellation path (owner drops the payload)
        } catch (const std::exception& ex) {
            data->error = ex.what();
        }
        return data;
    };
    prep_owner_->start(
        job_center_.scheduler(), std::move(spec),
        [this, generation, request](
            const pwb::job::qtbridge::JobOutcome& outcome) {
            prep_running_ = false;
            prep_in_flight_.reset();
            if (outcome.state == pwb::job::JobState::cancelled ||
                generation != volume_generation_) {
                // Superseded: the re-issue below recomputes the current
                // state — a stale payload is never applied.
                request_prep();
                return;
            }
            const auto data =
                std::any_cast<std::shared_ptr<JointPrepData>>(&outcome.result);
            if (data == nullptr || *data == nullptr) {
                // Framework-level failure (empty any): record the
                // request as served so a deterministic failure cannot
                // resubmit in a tight loop; the next scene change
                // re-issues normally.
                prep_applied_ = *request;
                request_prep();
                return;
            }
            if (!(*data)->error.empty()) {
                emit_status(tr("联合切片读取失败：%1").arg(
                    QString::fromStdString((*data)->error)));
            }
            prep_finished(*request, **data);
        });
}

void VizCJointHost::prep_finished(const JointPrepRequest& request,
                                  JointPrepData data) {
    prepared_ = std::move(data);
    // The applied key is the request the job actually ran for — never
    // the current one (a cooperatively-cancelled job can still finish
    // "successfully" with stale payloads; recording the true key keeps
    // the converge loop honest and re-issuing).
    prep_applied_ = request;
    if (time_map_ != nullptr && prepared_.active_sample >= 0 &&
        !prepared_.slice_rgba.empty()) {
        time_map_->set_prepared_slice(prepared_.slice_rgba, prepared_.n_inline,
                                      prepared_.n_crossline,
                                      prepared_.active_sample);
    }
    assemble_joint_objects();
    if (time_map_ != nullptr) {
        time_map_->refresh();
    }
    emit prep_applied();
    emit scene_updated();
    // Converge: the scene may have moved on while the worker ran.
    request_prep();
}

// ---- assembly ----------------------------------------------------------------

void VizCJointHost::assemble_joint_objects() {
    if (viewport_ == nullptr) return;
    auto& manager = viewport_->scene_manager();
    namespace joint = pwb::geo3d_viz::joint;

    // Joint objects own the "joint:" name prefix; stale ones (older
    // fences/wells) are removed first so identity stays stable across
    // updates.
    std::vector<std::string> existing = manager.names();
    for (const std::string& name : existing) {
        if (name.rfind("joint:", 0) == 0) {
            manager.remove(name);
        }
    }

    // Wells: render-space polylines through the scene transform (no
    // volume read — safe on the GUI thread).
    const auto width = static_cast<float>(
        scene_.display_settings().well_width_px);
    for (const auto& [id, traj] : scene_.well_trajectories()) {
        if (traj.points.empty()) continue;
        pwb::geo3d_viz::SceneObject object;
        object.name = "joint:well:" + id;
        object.kind = pwb::geo3d_viz::ObjectKind::Well;
        object.mode = pwb::geo3d_viz::ObjectMode::Lines;
        object.line_strip = true;
        object.pickable = true;
        object.pick_radius = 2.0f;
        object.width = width;
        object.color = {0.95f, 0.80f, 0.08f, 1.0f};
        object.verts = build_well_polyline(scene_, traj.points);
        if (!object.verts.empty()) {
            manager.add(std::move(object));
        }
    }

    // Fence curtains: one per VISIBLE fence, from the applied worker
    // payload (never a synchronous volume read here). Missing strips
    // arrive when the in-flight prep applies.
    // One by-value copy of the fence list: fences() returns a temporary,
    // so a pointer into it would dangle (caught as garbage curtain verts
    // in the closure verification — the real crash behind the
    // "non-finite coordinates" flake).
    const std::vector<joint::FenceSection> scene_fences = scene_.fences();
    for (const auto& strip : prepared_.strips) {
        const joint::FenceSection* fence = nullptr;
        for (const auto& candidate : scene_fences) {
            if (candidate.id == strip.fence_id &&
                candidate.visible) {
                fence = &candidate;
                break;
            }
        }
        if (fence == nullptr) continue;
        const CurtainMesh mesh = build_fence_curtain(
            scene_, *fence, strip.extraction,
            scene_.display_settings().seismic_color_scale);
        if (mesh.empty()) continue;
        pwb::geo3d_viz::SceneObject object;
        object.name = "joint:fence:" + strip.fence_id;
        object.kind = pwb::geo3d_viz::ObjectKind::Volume;
        object.mode = pwb::geo3d_viz::ObjectMode::Mesh;
        object.verts = mesh.vertices;
        object.faces = mesh.faces;
        object.face_colors = mesh.face_colors;
        object.smooth = false;
        object.pickable = false;
        manager.add(std::move(object));
    }

    // Active time slice from the prepared (worker-colorized) plane.
    if (scene_.vertical_domain() == VerticalDomain::Time &&
        prepared_.active_sample >= 0 && !prepared_.slice_rgba.empty()) {
        const SliceMesh mesh = build_active_time_slice_prepared(
            scene_, prepared_.slice_rgba, prepared_.n_inline,
            prepared_.n_crossline, prepared_.active_sample);
        if (!mesh.empty()) {
            pwb::geo3d_viz::SceneObject object;
            object.name = "joint:slice:active";
            object.kind = pwb::geo3d_viz::ObjectKind::Volume;
            object.mode = pwb::geo3d_viz::ObjectMode::Mesh;
            object.verts = mesh.vertices;
            object.faces = mesh.faces;
            object.face_colors = mesh.face_colors;
            object.smooth = false;
            object.pickable = false;
            manager.add(std::move(object));
        }
    }
}

void VizCJointHost::install_scene_transform() {
    if (dock_controller_ == nullptr) return;
    pwb::geo3d_viz::SceneTransform transform;
    // The joint scene owns the world↔render maps; geomodel-domain objects
    // (well:/horizon: from the workspace assembly) join the same render
    // space through the CONV-GEO3D seam.
    transform.to_render =
        [this](const std::vector<std::array<double, 3>>& world) {
            return scene_.world_to_render_xyz_array(world);
        };
    transform.to_domain =
        [this](const std::vector<std::array<double, 3>>& render) {
            return scene_.render_to_world_xyz_array(render);
        };
    dock_controller_->adapter().set_scene_transform(std::move(transform));
}

void VizCJointHost::emit_status(const QString& text) {
    emit status_changed(text);
}

}  // namespace pwb::app::viz_c

#endif  // PWB_WITH_UI_WELLSEIS
