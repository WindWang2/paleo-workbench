// joint_scene.cpp — WellSeismicScene (scene.py @ 08851951). Faithful
// port; see joint_scene.hpp for the contract notes.
#include "pwb/geo3d_viz/joint/joint_scene.hpp"
#include "pwb/geo3d_viz/joint/well_geometry.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <set>
#include <stdexcept>

#include <pwb/domain/json.hpp>

namespace pwb::geo3d_viz::joint {

namespace {

using pwb::domain::Json;

// numpy percentile(method="linear") on a copy.
double percentile_of(std::vector<double> samples, double q) {
    if (samples.empty()) return std::numeric_limits<double>::quiet_NaN();
    std::sort(samples.begin(), samples.end());
    const double pos =
        q / 100.0 * static_cast<double>(samples.size() - 1);
    const std::size_t lo = static_cast<std::size_t>(std::floor(pos));
    const std::size_t hi = static_cast<std::size_t>(std::min<double>(
        std::ceil(pos), static_cast<double>(samples.size() - 1)));
    const double frac = pos - static_cast<double>(lo);
    return samples[lo] + frac * (samples[hi] - samples[lo]);
}

// _project_point_to_polyline: (arc_length_s, distance) of the closest
// point on the polyline.
std::pair<double, double> project_point_to_polyline(
    double x, double y, const std::vector<std::array<double, 2>>& verts) {
    double best_d = std::numeric_limits<double>::infinity();
    double best_s = 0.0;
    double cum = 0.0;
    for (std::size_t i = 0; i + 1 < verts.size(); ++i) {
        const auto& a = verts[i];
        const auto& b = verts[i + 1];
        const double ab[2] = {b[0] - a[0], b[1] - a[1]};
        const double lab2 = ab[0] * ab[0] + ab[1] * ab[1];
        const double denom = lab2 != 0.0 ? lab2 : 1e-12;
        double t = ((x - a[0]) * ab[0] + (y - a[1]) * ab[1]) / denom;
        t = std::max(0.0, std::min(1.0, t));
        const double q[2] = {a[0] + t * ab[0], a[1] + t * ab[1]};
        const double d = std::hypot(x - q[0], y - q[1]);
        const double s = cum + t * std::hypot(ab[0], ab[1]);
        if (d < best_d) {
            best_d = d;
            best_s = s;
        }
        cum += std::hypot(ab[0], ab[1]);
    }
    return {best_s, best_d};
}

const WellCurve* find_gr_curve(
    const std::map<std::string, WellCurve>& curves) {
    static const char* kAliases[] = {"GR", "GAMMA", "SGR", "CGR"};
    for (const auto& [name, curve] : curves) {
        std::string upper;
        upper.reserve(name.size());
        for (char c : name) {
            upper.push_back(static_cast<char>(std::toupper(
                static_cast<unsigned char>(c))));
        }
        for (const char* alias : kAliases) {
            if (upper == alias) return &curve;
        }
    }
    return nullptr;
}

std::string fixed1(double v) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.1f", v);
    return buf;
}

}  // namespace

WellSeismicScene::WellSeismicScene()
    : depth_transform_(select_depth_transform()) {}

// ---- Survey ---------------------------------------------------------------

void WellSeismicScene::set_survey(SurveySpec survey) {
    survey_ = std::move(survey);
    invalidate_traj();
    extract_cache_.clear();
    rebuild_registration();
    reconcile_orthogonal_slice_state();
}

SurveySpec WellSeismicScene::set_survey_from_corners(
    const Corner& p1, const Corner& p2, const Corner& p3,
    std::int64_t n_samples, double dt_ms, double t0_ms,
    std::optional<std::int64_t> iline_step,
    std::optional<std::int64_t> xline_step,
    std::optional<std::int64_t> n_inlines,
    std::optional<std::int64_t> n_crosslines) {
    SurveySpec survey = survey_from_corners(
        p1, p2, p3, n_samples, dt_ms, t0_ms, iline_step, xline_step,
        n_inlines, n_crosslines);
    set_survey(std::move(survey));
    return *survey_;
}

std::pair<bool, std::string> WellSeismicScene::validate_against_corners(
    const Corner& p1, const Corner& p2, const Corner& p3, double tol_m,
    double tol_il_xl) const {
    if (!survey_.has_value()) return {false, "No survey set"};
    const Corner* corners[3] = {&p1, &p2, &p3};
    const char* labels[3] = {"P1", "P2", "P3"};
    for (int i = 0; i < 3; ++i) {
        const double il = (*corners[i])[0];
        const double xl = (*corners[i])[1];
        const double x = (*corners[i])[2];
        const double y = (*corners[i])[3];
        const auto [sx, sy] = survey_->il_xl_to_xy(il, xl);
        if (std::fabs(sx - x) > tol_m || std::fabs(sy - y) > tol_m) {
            char buf[256];
            std::snprintf(buf, sizeof(buf), "%.3f", sx);
            std::string sxs(buf);
            std::snprintf(buf, sizeof(buf), "%.3f", sy);
            return {false,
                    "Survey mismatch at " + std::string(labels[i]) +
                        ": expected XY≈(" + std::to_string(x) + ", " +
                        std::to_string(y) + "), survey gives (" + sxs +
                        ", " + buf + ")"};
        }
        const auto [sil, sxl] = survey_->xy_to_il_xl(x, y);
        if (std::fabs(sil - il) > tol_il_xl ||
            std::fabs(sxl - xl) > tol_il_xl) {
            char buf[256];
            std::snprintf(buf, sizeof(buf), "%.3f", sil);
            std::string sils(buf);
            std::snprintf(buf, sizeof(buf), "%.3f", sxl);
            return {false,
                    "Survey mismatch at " + std::string(labels[i]) +
                        ": expected IL/XL≈(" + std::to_string(il) + ", " +
                        std::to_string(xl) + "), survey gives (" + sils +
                        ", " + buf + ")"};
        }
    }
    return {true, ""};
}

// ---- Vertical domain / depth ----------------------------------------------

void WellSeismicScene::set_display_settings(
    JointDisplaySettings settings) {
    display_settings_ = std::move(settings);
}

void WellSeismicScene::restore_orthogonal_slice_state(
    OrthogonalSliceState state) {
    slice_state_ = std::move(state);
    reconcile_orthogonal_slice_state();
}

void WellSeismicScene::set_orthogonal_slice_indices(
    std::optional<std::int64_t> inline_index,
    std::optional<std::int64_t> crossline_index) {
    // An absent argument keeps the current value (which may itself be
    // absent — reconcile() then seeds the middle line, Python parity).
    std::optional<std::int64_t> il =
        inline_index.has_value() ? inline_index
                                 : slice_state_.inline_index;
    std::optional<std::int64_t> xl =
        crossline_index.has_value() ? crossline_index
                                    : slice_state_.crossline_index;
    if (registration_.has_value()) {
        if (il.has_value()) {
            il = std::max<std::int64_t>(0,
                                        std::min(
                                            registration_->n_inline() - 1,
                                            *il));
        }
        if (xl.has_value()) {
            xl = std::max<std::int64_t>(
                0, std::min(registration_->n_crossline() - 1, *xl));
        }
    }
    replace_slice_state(il, xl, std::nullopt, std::nullopt, std::nullopt);
}

double WellSeismicScene::add_time_slice(double time_ms) {
    const double snapped = snap_time_ms(time_ms);
    const TimeSliceState* existing = find_time_slice(snapped);
    if (existing != nullptr) {
        replace_slice_state(std::nullopt, std::nullopt, std::nullopt,
                            existing->time_ms, std::nullopt);
        return existing->time_ms;
    }
    if (slice_state_.time_slices.size() >= kMaxTimeSlices) {
        throw std::invalid_argument("Time slice stack is limited to " +
                                    std::to_string(kMaxTimeSlices) +
                                    " items");
    }
    std::vector<TimeSliceState> slices = slice_state_.time_slices;
    slices.emplace_back(snapped);
    std::sort(slices.begin(), slices.end(),
              [](const TimeSliceState& a, const TimeSliceState& b) {
                  return a.time_ms < b.time_ms;
              });
    replace_slice_state(std::nullopt, std::nullopt, std::move(slices),
                        snapped, std::nullopt);
    return snapped;
}

double WellSeismicScene::update_time_slice(double current_time_ms,
                                           double new_time_ms) {
    const TimeSliceState* current = find_time_slice(current_time_ms);
    if (current == nullptr) {
        throw std::out_of_range("no time slice at " +
                                std::to_string(current_time_ms));
    }
    const double snapped = snap_time_ms(new_time_ms);
    const TimeSliceState* target = find_time_slice(snapped);
    std::vector<TimeSliceState> remaining;
    for (const TimeSliceState& item : slice_state_.time_slices) {
        if (&item == current || &item == target) continue;
        remaining.push_back(item);
    }
    TimeSliceState moved =
        target != nullptr ? *target
                          : TimeSliceState(snapped, current->visible);
    remaining.push_back(moved);
    std::sort(remaining.begin(), remaining.end(),
              [](const TimeSliceState& a, const TimeSliceState& b) {
                  return a.time_ms < b.time_ms;
              });
    replace_slice_state(std::nullopt, std::nullopt, std::move(remaining),
                        moved.time_ms, std::nullopt);
    return moved.time_ms;
}

bool WellSeismicScene::remove_time_slice(double time_ms) {
    const TimeSliceState* current = find_time_slice(time_ms);
    if (current == nullptr || slice_state_.time_slices.size() <= 1) {
        return false;
    }
    std::vector<TimeSliceState> slices;
    for (const TimeSliceState& item : slice_state_.time_slices) {
        if (&item != current) slices.push_back(item);
    }
    std::optional<double> active = slice_state_.active_time_ms;
    if (active.has_value() && same_time(active, current->time_ms)) {
        active = slices.front().time_ms;
    }
    replace_slice_state(std::nullopt, std::nullopt, std::move(slices),
                        active, std::nullopt);
    return true;
}

void WellSeismicScene::set_time_slice_visible(double time_ms, bool visible) {
    const TimeSliceState* current = find_time_slice(time_ms);
    if (current == nullptr) {
        throw std::out_of_range("no time slice at " +
                                std::to_string(time_ms));
    }
    std::vector<TimeSliceState> slices;
    for (const TimeSliceState& item : slice_state_.time_slices) {
        slices.push_back(&item == current
                             ? TimeSliceState(item.time_ms, visible)
                             : item);
    }
    replace_slice_state(std::nullopt, std::nullopt, std::move(slices),
                        std::nullopt, std::nullopt);
}

void WellSeismicScene::set_active_time_slice(double time_ms) {
    const TimeSliceState* current = find_time_slice(time_ms);
    if (current == nullptr) {
        throw std::out_of_range("no time slice at " +
                                std::to_string(time_ms));
    }
    replace_slice_state(std::nullopt, std::nullopt, std::nullopt,
                        current->time_ms, std::nullopt);
}

void WellSeismicScene::set_time_slice_opacity(double opacity) {
    replace_slice_state(std::nullopt, std::nullopt, std::nullopt,
                        std::nullopt,
                        std::max(0.0, std::min(1.0, opacity)));
}

double WellSeismicScene::move_active_time_slice_to_sample(
    std::int64_t sample_index) {
    if (!registration_.has_value() ||
        !slice_state_.active_time_ms.has_value()) {
        throw std::runtime_error("Time slice stack is not ready");
    }
    const std::int64_t sample =
        std::max<std::int64_t>(0,
                               std::min(registration_->n_sample() - 1,
                                        sample_index));
    return update_time_slice(
        *slice_state_.active_time_ms,
        registration_->sample_idx_to_time_ms(
            static_cast<double>(sample)));
}

std::optional<std::tuple<std::int64_t, std::int64_t,
                         std::vector<std::pair<std::int64_t, bool>>,
                         std::int64_t, double>>
WellSeismicScene::orthogonal_slice_render_state() const {
    if (!registration_.has_value() ||
        !slice_state_.inline_index.has_value() ||
        !slice_state_.crossline_index.has_value() ||
        slice_state_.time_slices.empty() ||
        !slice_state_.active_time_ms.has_value()) {
        return std::nullopt;
    }
    const std::int64_t il = *slice_state_.inline_index;
    const std::int64_t xl = *slice_state_.crossline_index;
    std::vector<std::pair<std::int64_t, bool>> times;
    for (const TimeSliceState& item : slice_state_.time_slices) {
        times.emplace_back(
            registration_->clamp_indices(
                static_cast<double>(il), static_cast<double>(xl),
                registration_->time_ms_to_sample_idx(item.time_ms))[2],
            item.visible);
    }
    const std::int64_t active = registration_->clamp_indices(
        static_cast<double>(il), static_cast<double>(xl),
        registration_->time_ms_to_sample_idx(*slice_state_.active_time_ms))[2];
    return std::make_tuple(il, xl, std::move(times), active,
                           slice_state_.time_opacity);
}

void WellSeismicScene::replace_slice_state(
    std::optional<std::int64_t> inline_index,
    std::optional<std::int64_t> crossline_index,
    std::optional<std::vector<TimeSliceState>> time_slices,
    std::optional<double> active_time_ms,
    std::optional<double> time_opacity) {
    slice_state_ = OrthogonalSliceState(
        inline_index.has_value() ? inline_index
                                 : slice_state_.inline_index,
        crossline_index.has_value() ? crossline_index
                                    : slice_state_.crossline_index,
        time_slices.has_value() ? std::move(*time_slices)
                                : slice_state_.time_slices,
        active_time_ms.has_value() ? active_time_ms
                                   : slice_state_.active_time_ms,
        time_opacity.has_value() ? *time_opacity
                                 : slice_state_.time_opacity);
    sync_well_order_fence();
}

const TimeSliceState* WellSeismicScene::find_time_slice(
    double time_ms) const {
    for (const TimeSliceState& item : slice_state_.time_slices) {
        if (same_time(item.time_ms, time_ms)) return &item;
    }
    return nullptr;
}

bool WellSeismicScene::same_time(std::optional<double> left,
                                 std::optional<double> right) {
    if (!left.has_value() || !right.has_value()) return false;
    // np.isclose(atol=1e-7) keeps the default rtol=1e-5 term.
    return std::fabs(*left - *right) <=
           1e-7 + 1e-5 * std::fabs(*right);
}

double WellSeismicScene::snap_time_ms(double time_ms) const {
    if (!registration_.has_value()) {
        if (!std::isfinite(time_ms)) {
            throw std::invalid_argument("time_ms must be finite");
        }
        return time_ms;
    }
    const std::int64_t sample =
        registration_->clamp_indices(0, 0,
                                     registration_->time_ms_to_sample_idx(
                                         time_ms))[2];
    return registration_->sample_idx_to_time_ms(
        static_cast<double>(sample));
}

void WellSeismicScene::reconcile_orthogonal_slice_state() {
    if (!registration_.has_value()) return;
    const VolumeRegistration& registration = *registration_;
    const std::int64_t il =
        !slice_state_.inline_index.has_value()
            ? registration.n_inline() / 2
            : std::max<std::int64_t>(
                  0, std::min(registration.n_inline() - 1,
                              *slice_state_.inline_index));
    const std::int64_t xl =
        !slice_state_.crossline_index.has_value()
            ? registration.n_crossline() / 2
            : std::max<std::int64_t>(
                  0, std::min(registration.n_crossline() - 1,
                              *slice_state_.crossline_index));
    const SurveySpec& survey = registration.survey();
    const double lower = survey.t0_ms;
    const double upper =
        survey.t0_ms +
        static_cast<double>(std::max<std::int64_t>(survey.n_samples - 1, 0)) *
            survey.dt_ms;
    int dropped = 0;
    std::map<std::int64_t, TimeSliceState> by_sample;
    for (const TimeSliceState& item : slice_state_.time_slices) {
        if (!(item.time_ms >= lower && item.time_ms <= upper)) {
            ++dropped;
            continue;
        }
        const std::int64_t sample = registration.clamp_indices(
            static_cast<double>(il), static_cast<double>(xl),
            registration.time_ms_to_sample_idx(item.time_ms))[2];
        const double snapped =
            registration.sample_idx_to_time_ms(static_cast<double>(sample));
        if (by_sample.find(sample) == by_sample.end()) {
            by_sample.emplace(sample,
                              TimeSliceState(snapped, item.visible));
        }
    }
    std::vector<TimeSliceState> slices;
    for (const auto& [sample, item] : by_sample) {
        (void)sample;
        slices.push_back(item);
    }
    if (slices.size() > kMaxTimeSlices) {
        slices.resize(kMaxTimeSlices);
    }
    if (slices.empty()) {
        const std::int64_t middle = registration.n_sample() / 2;
        slices.emplace_back(registration.sample_idx_to_time_ms(
            static_cast<double>(middle)));
    }
    std::optional<double> active = slice_state_.active_time_ms;
    const TimeSliceState* active_item = nullptr;
    if (active.has_value() && *active >= lower && *active <= upper) {
        const double active_ms = registration.sample_idx_to_time_ms(
            static_cast<double>(registration.clamp_indices(
                static_cast<double>(il), static_cast<double>(xl),
                registration.time_ms_to_sample_idx(*active))[2]));
        for (const TimeSliceState& item : slices) {
            if (same_time(item.time_ms, active_ms)) {
                active_item = &item;
                break;
            }
        }
    }
    if (active_item == nullptr) active_item = &slices.front();
    const double active_ms = active_item->time_ms;
    slice_state_ =
        OrthogonalSliceState(il, xl, std::move(slices), active_ms,
                             slice_state_.time_opacity);
    sync_well_order_fence();
    slice_state_warning_ =
        dropped > 0
            ? "已丢弃 " + std::to_string(dropped) + " 张越界 Time 切片"
            : "";
}

void WellSeismicScene::set_depth_transform(DepthTransformState state) {
    depth_transform_ = std::move(state);
    invalidate_traj();
    extract_cache_.clear();
}

void WellSeismicScene::set_vertical_domain(VerticalDomain domain) {
    if (domain == domain_) return;
    if (domain == VerticalDomain::Depth &&
        !depth_transform_.available()) {
        throw std::invalid_argument(
            "Depth domain unavailable: no time-depth transform "
            "(velocity model / checkshot / depth cube) is set");
    }
    domain_ = domain;
    invalidate_traj();
    extract_cache_.clear();
    sync_well_order_fence();
}

// ---- Wells ------------------------------------------------------------------

void WellSeismicScene::set_wells(
    std::vector<WellHead> wells,
    std::map<std::string, TimeDepthTable> td_tables) {
    std::string missing;
    for (const WellHead& well : wells) {
        if (well.id.empty()) {
            if (!missing.empty()) missing += ", ";
            missing += well.name;
        }
    }
    if (!missing.empty()) {
        throw std::invalid_argument(
            "Every joint well requires a stable source JointWellId; "
            "missing for: " + missing);
    }
    std::map<JointWellId, int> counts;
    for (const WellHead& well : wells) counts[well.id] += 1;
    std::string duplicates;
    for (const auto& [id, count] : counts) {
        if (count > 1) {
            if (!duplicates.empty()) duplicates += ", ";
            duplicates += id;
        }
    }
    if (!duplicates.empty()) {
        throw std::invalid_argument(
            "JointWellId values must be unique; duplicates: " + duplicates);
    }

    std::map<JointWellId, bool> previous_visibility = well_visibility_;
    wells_ = std::move(wells);
    well_ids_.clear();
    for (const WellHead& well : wells_) well_ids_.push_back(well.id);
    well_visibility_.clear();
    for (const JointWellId& id : well_ids_) {
        const auto it = previous_visibility.find(id);
        well_visibility_[id] = it != previous_visibility.end() ? it->second
                                                               : true;
    }
    td_tables_ = std::move(td_tables);
    std::set<JointWellId> known(well_ids_.begin(), well_ids_.end());
    std::vector<JointWellId> filtered;
    for (const JointWellId& id : fence_well_ids_) {
        if (known.count(id) != 0) filtered.push_back(id);
    }
    fence_well_ids_ = std::move(filtered);
    invalidate_traj();
    sync_well_order_fence();
}

std::vector<JointWellPresentation>
WellSeismicScene::well_presentations() const {
    // Wells in source order with stable identities and unique labels.
    std::map<std::string, int> counts;
    for (const WellHead& well : wells_) counts[well.name] += 1;
    std::map<std::string, int> occurrences;
    std::vector<JointWellPresentation> presentations;
    for (std::size_t i = 0; i < wells_.size(); ++i) {
        const JointWellId& id = well_ids_[i];
        const WellHead& well = wells_[i];
        ++occurrences[well.name];
        std::string display = well.name;
        if (counts[well.name] > 1) {
            display = well.name + " (" +
                      std::to_string(occurrences[well.name]) + ")";
        }
        const auto it = well_visibility_.find(id);
        presentations.push_back(
            {id, well.name, std::move(display),
             it != well_visibility_.end() ? it->second : true});
    }
    return presentations;
}

void WellSeismicScene::set_well_visibility(const JointWellId& well_id,
                                           bool visible) {
    if (well_visibility_.find(well_id) == well_visibility_.end()) {
        throw std::out_of_range("unknown well id: " + well_id);
    }
    well_visibility_[well_id] = visible;
}

std::map<JointWellId, WellTrajectory3D>
WellSeismicScene::well_trajectories(bool visible_only) const {
    if (!traj_cache_.has_value()) {
        traj_cache_ = std::map<JointWellId, WellTrajectory3D>();
        for (std::size_t i = 0; i < wells_.size(); ++i) {
            const JointWellId& id = well_ids_[i];
            const WellHead& well = wells_[i];
            const TimeDepthTable* td = nullptr;
            const auto by_id = td_tables_.find(id);
            if (by_id != td_tables_.end()) {
                td = &by_id->second;
            } else {
                const auto by_name = td_tables_.find(well.name);
                if (by_name != td_tables_.end()) td = &by_name->second;
            }
            (*traj_cache_)[id] = project_well_trajectory(
                well, domain_, td, kDefaultTrajectorySamples,
                &depth_transform_);
        }
    }
    if (!visible_only) return *traj_cache_;
    std::map<JointWellId, WellTrajectory3D> visible;
    for (const auto& [id, traj] : *traj_cache_) {
        const auto it = well_visibility_.find(id);
        if (it == well_visibility_.end() || it->second) visible.emplace(id, traj);
    }
    return visible;
}

void WellSeismicScene::set_formation_tops(
    std::map<std::string, std::vector<std::pair<std::string, double>>>
        tops_by_well) {
    tops_by_well_ = std::move(tops_by_well);
}

void WellSeismicScene::set_well_curves(
    std::map<std::string, std::map<std::string, WellCurve>> curves_by_well) {
    curves_by_well_ = std::move(curves_by_well);
}

std::optional<std::pair<double, double>>
WellSeismicScene::gr_value_range() const {
    std::vector<double> samples;
    for (const auto& [well, curves] : curves_by_well_) {
        const WellCurve* curve = find_gr_curve(curves);
        if (curve == nullptr) continue;
        for (double v : curve->second) {
            if (std::isfinite(v)) samples.push_back(v);
        }
    }
    if (samples.empty()) return std::nullopt;
    const double lo = percentile_of(samples, 2.0);
    const double hi = percentile_of(samples, 98.0);
    return std::make_pair(lo, hi);
}

std::map<JointWellId, WellGrTrajectory>
WellSeismicScene::gr_well_trajectories(bool visible_only) const {
    std::map<JointWellId, WellGrTrajectory> tracks;
    const auto base = well_trajectories();
    const auto presentations = well_presentations();
    for (std::size_t i = 0; i < presentations.size(); ++i) {
        const JointWellPresentation& presentation = presentations[i];
        const WellHead& well = wells_[i];
        if (visible_only && !presentation.visible) continue;
        const std::map<std::string, WellCurve>* curves = nullptr;
        const auto by_id = curves_by_well_.find(presentation.id);
        if (by_id != curves_by_well_.end()) {
            curves = &by_id->second;
        } else {
            const auto by_name = curves_by_well_.find(well.name);
            if (by_name != curves_by_well_.end()) curves = &by_name->second;
        }
        const TimeDepthTable* td = nullptr;
        const auto td_id = td_tables_.find(presentation.id);
        if (td_id != td_tables_.end()) {
            td = &td_id->second;
        } else {
            const auto td_name = td_tables_.find(well.name);
            if (td_name != td_tables_.end()) td = &td_name->second;
        }
        std::vector<std::array<double, 3>> points;
        std::vector<double> values;
        const WellCurve* curve =
            curves != nullptr ? find_gr_curve(*curves) : nullptr;
        if (curve == nullptr || td == nullptr) {
            // No GR curve, or no TD table to place it in the seismic
            // vertical domain (Time and Depth both need the MD→TWT leg).
            points = base.at(presentation.id).points;
            values.assign(points.size(),
                          std::numeric_limits<double>::quiet_NaN());
        } else {
            std::vector<double> md = curve->first;
            std::vector<double> vals = curve->second;
            const std::size_t count = std::min(md.size(), vals.size());
            md.resize(count);
            vals.resize(count);
            std::vector<std::size_t> order(count);
            for (std::size_t k = 0; k < count; ++k) order[k] = k;
            const double total_depth =
                std::max(well.total_depth_m, 1e-12);
            std::vector<double> md_keep;
            std::vector<double> val_keep;
            for (std::size_t k = 0; k < count; ++k) {
                if (std::isfinite(md[k]) && md[k] >= 0.0 &&
                    md[k] <= well.total_depth_m) {
                    md_keep.push_back(md[k]);
                    val_keep.push_back(vals[k]);
                }
            }
            std::vector<std::size_t> idx(md_keep.size());
            for (std::size_t k = 0; k < idx.size(); ++k) idx[k] = k;
            std::stable_sort(idx.begin(), idx.end(),
                             [&](std::size_t a, std::size_t b) {
                                 return md_keep[a] < md_keep[b];
                             });
            std::vector<double> x;
            std::vector<double> y;
            std::vector<double> z;
            std::vector<double> v_sorted;
            for (std::size_t k : idx) {
                const double frac = md_keep[k] / total_depth;
                x.push_back(well.x + frac * (well.bottom_x - well.x));
                y.push_back(well.y + frac * (well.bottom_y - well.y));
                if (domain_ == VerticalDomain::Time) {
                    z.push_back(td->md_to_time_ms(md_keep[k]));
                } else {
                    // Depth from MD goes through the TD table and the
                    // scene's (real) transform — MD itself is never used
                    // as scene depth for a deviated well.
                    z.push_back(depth_transform_.time_ms_to_depth_m(
                        td->md_to_time_ms(md_keep[k])));
                }
                v_sorted.push_back(val_keep[k]);
            }
            // V6 §8: drop uncalibrated samples instead of clamping.
            for (std::size_t k = 0; k < z.size(); ++k) {
                if (!std::isfinite(z[k])) continue;
                points.push_back({x[k], y[k], z[k]});
                values.push_back(v_sorted[k]);
            }
        }
        WellGrTrajectory track;
        track.id = presentation.id;
        track.name = well.name;
        track.display_name = presentation.display_name;
        track.points = std::move(points);
        track.gr_values = std::move(values);
        tracks.emplace(presentation.id, std::move(track));
    }
    return tracks;
}

void WellSeismicScene::set_curve_names(std::vector<std::string> names) {
    curve_names_ = std::move(names);
    if (curve_names_.size() > 2) curve_names_.resize(2);
}

void WellSeismicScene::set_near_well_distance_m(double distance_m) {
    near_well_m_ = distance_m;
}

// ---- Volume -------------------------------------------------------------------

void WellSeismicScene::set_volume_access(
    std::shared_ptr<IVolumeAccess> access) {
    rescale_slice_indices(volume_.get(), access.get());
    volume_ = std::move(access);
    extract_cache_.clear();
    rebuild_registration();
    reconcile_orthogonal_slice_state();
}

void WellSeismicScene::rescale_slice_indices(
    const IVolumeAccess* old_access, const IVolumeAccess* new_access) {
    // Keep IL/XL slice indices physically stationary across LOD changes:
    // indices live in loaded-volume space, so a preview refinement
    // (L0→L1) changes their meaning unless they are converted through
    // the OLD registration into survey line numbers and back through the
    // NEW one.
    if (old_access == nullptr || new_access == nullptr) return;
    if (!registration_.has_value()) return;
    if (!slice_state_.inline_index.has_value() &&
        !slice_state_.crossline_index.has_value()) {
        return;
    }
    const auto new_shape = new_access->shape();
    const auto new_strides = new_access->strides();
    std::optional<VolumeRegistration> new_reg;
    try {
        if (new_strides.has_value()) {
            new_reg = VolumeRegistration(*survey_, new_shape[0],
                                         new_shape[1], new_shape[2],
                                         *new_strides);
        } else {
            new_reg = VolumeRegistration::from_survey_and_shape(
                *survey_, new_shape);
        }
    } catch (const std::invalid_argument&) {
        return;
    }
    const auto [il_num, xl_num] = registration_->volume_idx_to_il_xl(
        static_cast<double>(slice_state_.inline_index.value_or(0)),
        static_cast<double>(slice_state_.crossline_index.value_or(0)));
    const auto [vi, vx] = new_reg->il_xl_to_volume_idx(il_num, xl_num);
    // Python round() = half-to-even (nearbyint); round, then clamp.
    const std::int64_t il = static_cast<std::int64_t>(
        std::max(0.0, std::min(static_cast<double>(new_shape[0] - 1),
                               std::nearbyint(vi))));
    const std::int64_t xl = static_cast<std::int64_t>(
        std::max(0.0, std::min(static_cast<double>(new_shape[1] - 1),
                               std::nearbyint(vx))));
    slice_state_ = OrthogonalSliceState(
        il, xl, slice_state_.time_slices, slice_state_.active_time_ms,
        slice_state_.time_opacity);
}

void WellSeismicScene::rebuild_registration() const {
    if (!survey_.has_value() || volume_ == nullptr) {
        registration_.reset();
        return;
    }
    const auto shape = volume_->shape();
    const auto strides = volume_->strides();
    if (strides.has_value()) {
        try {
            registration_ = VolumeRegistration(*survey_, shape[0], shape[1],
                                               shape[2], *strides);
            return;
        } catch (const std::invalid_argument&) {
            // Stride/shape mismatch: fall through to inference, which
            // also throws if the shape is impossible for the survey.
        }
    }
    registration_ = VolumeRegistration::from_survey_and_shape(*survey_,
                                                              shape);
}

std::vector<float> WellSeismicScene::slice_inline(
    std::int64_t il_index) const {
    if (volume_ == nullptr) {
        throw std::runtime_error(
            "No volume access set on WellSeismicScene");
    }
    return volume_->slice_inline(il_index);
}

std::vector<float> WellSeismicScene::slice_crossline(
    std::int64_t xl_index) const {
    if (volume_ == nullptr) {
        throw std::runtime_error(
            "No volume access set on WellSeismicScene");
    }
    return volume_->slice_crossline(xl_index);
}

std::vector<float> WellSeismicScene::slice_time(
    std::int64_t sample_index) const {
    if (volume_ == nullptr) {
        throw std::runtime_error(
            "No volume access set on WellSeismicScene");
    }
    return volume_->slice_time(sample_index);
}

// ---- Fences ---------------------------------------------------------------------

FenceSection WellSeismicScene::add_fence(FenceSection fence, bool activate) {
    fences_.push_back(fence);
    if (activate || !active_fence_id_.has_value()) {
        active_fence_id_ = fence.id;
    }
    return fences_.back();
}

void WellSeismicScene::set_active_fence(const std::string& fence_id) {
    for (const FenceSection& fence : fences_) {
        if (fence.id == fence_id) {
            active_fence_id_ = fence_id;
            return;
        }
    }
    throw std::out_of_range("unknown fence id: " + fence_id);
}

void WellSeismicScene::remove_fence(const std::string& fence_id) {
    const std::size_t before = fences_.size();
    fences_.erase(std::remove_if(fences_.begin(), fences_.end(),
                                 [&](const FenceSection& fence) {
                                     return fence.id == fence_id;
                                 }),
                  fences_.end());
    if (fences_.size() == before) {
        throw std::out_of_range("unknown fence id: " + fence_id);
    }
    for (auto it = extract_cache_.begin();
         it != extract_cache_.end();) {
        if (std::get<0>(it->first) == fence_id) {
            it = extract_cache_.erase(it);
        } else {
            ++it;
        }
    }
    if (fence_id == well_order_fence_id_) {
        well_order_fence_id_.reset();
        fence_well_ids_.clear();
    }
    if (active_fence_id_ == fence_id) {
        active_fence_id_ =
            fences_.empty()
                ? std::nullopt
                : std::optional<std::string>(fences_.back().id);
    }
}

bool WellSeismicScene::remove_active_fence() {
    if (!active_fence_id_.has_value()) return false;
    remove_fence(*active_fence_id_);
    return true;
}

void WellSeismicScene::clear_fences() {
    // Stale fence vertices are meaningless against a new survey and would
    // otherwise silently clamp into invalid extraction strips.
    fences_.clear();
    active_fence_id_.reset();
    fence_well_ids_.clear();
    well_order_fence_id_.reset();
    extract_cache_.clear();
    probe_.reset();
}

void WellSeismicScene::set_fence_visible(const std::string& fence_id,
                                         bool visible) {
    for (FenceSection& fence : fences_) {
        if (fence.id == fence_id) {
            fence.visible = visible;
            return;
        }
    }
    throw std::out_of_range("unknown fence id: " + fence_id);
}

FenceSection WellSeismicScene::add_well_to_well_fence(
    const std::vector<JointWellId>& well_refs, const std::string& name) {
    std::vector<JointWellId> ids;
    std::set<JointWellId> seen;
    for (const JointWellId& ref : well_refs) {
        const JointWellId id = resolve_well_ref(ref);
        if (seen.count(id) != 0) continue;
        seen.insert(id);
        ids.push_back(id);
    }
    fence_well_ids_ = std::move(ids);
    const FenceSection* fence = sync_well_order_fence(name);
    if (fence == nullptr) {
        throw std::invalid_argument("无时深，无法投影到当前 Time");
    }
    return *fence;
}

std::vector<WellPierce>
WellSeismicScene::pierce_points_on_active_time(bool visible_only) const {
    if (domain_ != VerticalDomain::Time) return {};
    if (!slice_state_.active_time_ms.has_value()) return {};
    const std::map<std::string, JointWellPresentation> presentations = [this] {
        std::map<std::string, JointWellPresentation> map;
        for (const auto& item : well_presentations()) {
            map.emplace(item.id, item);
        }
        return map;
    }();
    std::vector<WellPierce> out;
    for (const auto& [well_id, traj] :
         well_trajectories(visible_only)) {
        if (!traj.has_td) continue;
        const auto xy = pierce_xy_at_z(traj.points,
                                       *slice_state_.active_time_ms);
        if (!xy.has_value()) continue;
        const auto it = presentations.find(well_id);
        WellPierce pierce;
        pierce.well_id = well_id;
        pierce.name = it != presentations.end() ? it->second.name
                                                : traj.name;
        pierce.display_name =
            it != presentations.end() ? it->second.display_name
                                      : traj.name;
        pierce.x = xy->first;
        pierce.y = xy->second;
        pierce.z = *slice_state_.active_time_ms;
        out.push_back(std::move(pierce));
    }
    return out;
}

bool WellSeismicScene::append_fence_well(const JointWellId& well_ref) {
    const JointWellId well_id = resolve_well_ref(well_ref);
    if (std::find(fence_well_ids_.begin(), fence_well_ids_.end(),
                  well_id) != fence_well_ids_.end()) {
        return false;
    }
    std::set<JointWellId> piercing;
    for (const WellPierce& p : pierce_points_on_active_time()) {
        piercing.insert(p.well_id);
    }
    if (piercing.count(well_id) == 0) {
        throw std::invalid_argument("无时深，无法投影到当前 Time");
    }
    fence_well_ids_.push_back(well_id);
    sync_well_order_fence();
    return true;
}

std::optional<JointWellId> WellSeismicScene::pop_fence_well() {
    if (fence_well_ids_.empty()) return std::nullopt;
    const JointWellId id = fence_well_ids_.back();
    fence_well_ids_.pop_back();
    sync_well_order_fence();
    return id;
}

JointWellId WellSeismicScene::resolve_well_ref(
    const JointWellId& ref) const {
    for (std::size_t i = 0; i < wells_.size(); ++i) {
        if (ref == well_ids_[i]) return ref;
    }
    std::map<std::string, int> name_counts;
    for (const WellHead& well : wells_) name_counts[well.name] += 1;
    for (std::size_t i = 0; i < wells_.size(); ++i) {
        if (wells_[i].name == ref && name_counts[wells_[i].name] == 1) {
            return well_ids_[i];
        }
    }
    throw std::out_of_range("unknown well ref: " + ref);
}

std::pair<double, double> WellSeismicScene::head_xy(
    const JointWellId& well_id) const {
    for (std::size_t i = 0; i < wells_.size(); ++i) {
        if (well_ids_[i] == well_id) return {wells_[i].x, wells_[i].y};
    }
    throw std::out_of_range("unknown well id: " + well_id);
}

void WellSeismicScene::drop_well_order_fence() {
    const std::optional<std::string> fence_id = well_order_fence_id_;
    well_order_fence_id_.reset();
    if (!fence_id.has_value()) return;
    fences_.erase(std::remove_if(fences_.begin(), fences_.end(),
                                 [&](const FenceSection& fence) {
                                     return fence.id == *fence_id;
                                 }),
                  fences_.end());
    for (auto it = extract_cache_.begin();
         it != extract_cache_.end();) {
        if (std::get<0>(it->first) == *fence_id) {
            it = extract_cache_.erase(it);
        } else {
            ++it;
        }
    }
    if (active_fence_id_ == fence_id) {
        active_fence_id_ =
            fences_.empty()
                ? std::nullopt
                : std::optional<std::string>(fences_.back().id);
    }
}

FenceSection* WellSeismicScene::sync_well_order_fence(
    const std::string& name) {
    if (fence_well_ids_.empty()) return nullptr;
    std::vector<std::array<double, 2>> xy;
    if (domain_ == VerticalDomain::Time &&
        slice_state_.active_time_ms.has_value()) {
        std::map<JointWellId, WellPierce> piercing;
        for (const WellPierce& p :
             pierce_points_on_active_time(false)) {
            piercing.emplace(p.well_id, p);
        }
        for (const JointWellId& id : fence_well_ids_) {
            const auto it = piercing.find(id);
            if (it != piercing.end()) {
                xy.push_back({it->second.x, it->second.y});
            }
        }
    } else {
        for (const JointWellId& id : fence_well_ids_) {
            const auto [x, y] = head_xy(id);
            xy.push_back({x, y});
        }
    }
    if (xy.size() < 2) {
        drop_well_order_fence();
        return nullptr;
    }
    const std::vector<std::array<double, 2>> verts =
        well_to_well_path(xy);
    for (FenceSection& fence : fences_) {
        if (well_order_fence_id_.has_value() &&
            fence.id == *well_order_fence_id_) {
            fence.vertices_xy = verts;
            if (!name.empty()) fence.name = name;
            for (auto it = extract_cache_.begin();
                 it != extract_cache_.end();) {
                if (std::get<0>(it->first) == fence.id) {
                    it = extract_cache_.erase(it);
                } else {
                    ++it;
                }
            }
            active_fence_id_ = fence.id;
            return &fence;
        }
    }
    FenceSection fence(name.empty() ? "Wells" : name, verts);
    well_order_fence_id_ = fence.id;
    add_fence(std::move(fence), true);
    for (FenceSection& stored : fences_) {
        if (stored.id == *well_order_fence_id_) return &stored;
    }
    return nullptr;
}

const FenceSection* WellSeismicScene::active_fence() const {
    if (!active_fence_id_.has_value()) return nullptr;
    for (const FenceSection& fence : fences_) {
        if (fence.id == *active_fence_id_) return &fence;
    }
    return nullptr;
}

std::optional<FenceExtraction> WellSeismicScene::extract_active_fence(
    std::int64_t n_along, std::optional<VerticalDomain> domain) const {
    const FenceSection* fence = active_fence();
    if (fence == nullptr || volume_ == nullptr || !survey_.has_value()) {
        return std::nullopt;
    }
    const VerticalDomain use_domain = domain.value_or(domain_);
    const auto cache_key = std::make_tuple(
        fence->id, use_domain == VerticalDomain::Depth ? 1 : 0, n_along);
    const auto cached = extract_cache_.find(cache_key);
    if (cached != extract_cache_.end()) return cached->second;

    const SurveySpec& survey = *survey_;
    if (!registration_.has_value()) rebuild_registration();
    const std::int64_t nt = volume_->shape()[2];
    // Preview sample i represents native sample i*stride_t, so the axis
    // must span the FULL survey time range with spacing dt*stride_t —
    // arange(nt)*dt alone would compress the axis by the stride factor.
    const std::int64_t stride_t =
        registration_.has_value() ? registration_->strides()[2] : 1;
    std::vector<double> saxis(static_cast<std::size_t>(nt));
    for (std::int64_t t = 0; t < nt; ++t) {
        saxis[static_cast<std::size_t>(t)] =
            survey.t0_ms +
            static_cast<double>(t) * (survey.dt_ms *
                                      static_cast<double>(stride_t));
    }
    if (use_domain == VerticalDomain::Depth) {
        saxis = depth_transform_.time_ms_to_depth_m(saxis);
    }
    FenceExtraction extraction = extract_fence_strip(
        *volume_, *fence, survey, n_along, saxis,
        registration_.has_value() ? &*registration_ : nullptr);
    extract_cache_.emplace(cache_key, extraction);
    return extraction;
}

// ---- Active 2D assembly ----------------------------------------------------------

std::vector<ProfileWellHit>
WellSeismicScene::assemble_active_profile_wells(
    std::optional<VerticalDomain> domain) const {
    const FenceSection* fence = active_fence();
    if (fence == nullptr) return {};
    const VerticalDomain use_domain = domain.value_or(domain_);
    std::vector<ProfileWellHit> hits;
    const auto presentations = well_presentations();
    for (std::size_t i = 0; i < presentations.size(); ++i) {
        const JointWellPresentation& presentation = presentations[i];
        const WellHead& well = wells_[i];
        const auto vis = well_visibility_.find(presentation.id);
        if (vis != well_visibility_.end() && !vis->second) continue;
        const auto [s, dist] =
            project_point_to_polyline(well.x, well.y, fence->vertices_xy);
        if (dist > near_well_m_) continue;

        const std::map<std::string, WellCurve>* curves = nullptr;
        const auto by_id = curves_by_well_.find(presentation.id);
        if (by_id != curves_by_well_.end()) {
            curves = &by_id->second;
        } else {
            const auto by_name = curves_by_well_.find(well.name);
            if (by_name != curves_by_well_.end()) {
                curves = &by_name->second;
            }
        }
        std::optional<std::string> curve_name;
        std::optional<std::vector<double>> cmd;
        std::optional<std::vector<double>> cval;
        std::optional<std::vector<double>> curve_z;
        if (curves != nullptr) {
            // Prefer configured names, then GR→DT→RHOB (case-insensitive).
            std::vector<std::string> order = curve_names_;
            for (const char* fallback : kDefaultCurveFallback) {
                if (std::find(order.begin(), order.end(),
                              std::string(fallback)) == order.end()) {
                    order.push_back(fallback);
                }
            }
            for (const std::string& wanted : order) {
                for (const auto& [key, curve] : *curves) {
                    std::string upper_key;
                    std::string upper_wanted;
                    for (char c : key) {
                        upper_key.push_back(static_cast<char>(std::toupper(
                            static_cast<unsigned char>(c))));
                    }
                    for (char c : wanted) {
                        upper_wanted.push_back(
                            static_cast<char>(std::toupper(
                                static_cast<unsigned char>(c))));
                    }
                    if (upper_key == upper_wanted) {
                        curve_name = key;
                        cmd = curve.first;
                        cval = curve.second;
                        break;
                    }
                }
                if (curve_name.has_value()) break;
            }
        }
        if (cmd.has_value()) {
            const TimeDepthTable* td = nullptr;
            const auto td_id = td_tables_.find(presentation.id);
            if (td_id != td_tables_.end()) {
                td = &td_id->second;
            } else {
                const auto td_name = td_tables_.find(well.name);
                if (td_name != td_tables_.end()) td = &td_name->second;
            }
            if (use_domain == VerticalDomain::Depth) {
                // Curve depth = TD(MD→TWT) then the active transform —
                // never raw MD (a well-path parameter, not a seismic
                // vertical coordinate).
                if (td != nullptr && depth_transform_.available()) {
                    std::vector<double> twt =
                        td->md_to_time_ms(*cmd);
                    std::vector<double> z =
                        depth_transform_.time_ms_to_depth_m(twt);
                    // V6 §8: keep only the calibrated subset.
                    std::vector<double> md_keep;
                    std::vector<double> val_keep;
                    std::vector<double> z_keep;
                    for (std::size_t k = 0; k < z.size(); ++k) {
                        if (!std::isfinite(z[k])) continue;
                        md_keep.push_back((*cmd)[k]);
                        val_keep.push_back((*cval)[k]);
                        z_keep.push_back(z[k]);
                    }
                    cmd = std::move(md_keep);
                    cval = std::move(val_keep);
                    curve_z = std::move(z_keep);
                }
            } else if (td != nullptr) {
                std::vector<double> z = td->md_to_time_ms(*cmd);
                std::vector<double> md_keep;
                std::vector<double> val_keep;
                std::vector<double> z_keep;
                for (std::size_t k = 0; k < z.size(); ++k) {
                    if (!std::isfinite(z[k])) continue;
                    md_keep.push_back((*cmd)[k]);
                    val_keep.push_back((*cval)[k]);
                    z_keep.push_back(z[k]);
                }
                cmd = std::move(md_keep);
                cval = std::move(val_keep);
                curve_z = std::move(z_keep);
            }
        }
        ProfileWellHit hit;
        hit.id = presentation.id;
        hit.name = well.name;
        hit.display_name = presentation.display_name;
        hit.s_m = s;
        hit.distance_m = dist;
        const auto tops_id = tops_by_well_.find(presentation.id);
        if (tops_id != tops_by_well_.end()) {
            hit.tops =
                tops_in_domain(tops_id->second, use_domain);
        } else {
            const auto tops_name = tops_by_well_.find(well.name);
            if (tops_name != tops_by_well_.end()) {
                hit.tops =
                    tops_in_domain(tops_name->second, use_domain);
            }
        }
        hit.curve_name = std::move(curve_name);
        hit.curve_md = std::move(cmd);
        hit.curve_z = std::move(curve_z);
        hit.curve_values = std::move(cval);
        hits.push_back(std::move(hit));
    }
    std::stable_sort(hits.begin(), hits.end(),
                     [](const ProfileWellHit& a, const ProfileWellHit& b) {
                         return a.s_m < b.s_m;
                     });
    return hits;
}

std::vector<std::pair<std::string, double>>
WellSeismicScene::tops_in_domain(
    const std::vector<std::pair<std::string, double>>& tops,
    VerticalDomain domain) const {
    // Tops are stored as TWT ms; convert to the requested display domain.
    if (domain != VerticalDomain::Depth ||
        !depth_transform_.available()) {
        return tops;
    }
    std::vector<std::pair<std::string, double>> out;
    out.reserve(tops.size());
    for (const auto& [name, z] : tops) {
        out.emplace_back(name,
                         depth_transform_.time_ms_to_depth_m(z));
    }
    return out;
}

// ---- Probe -----------------------------------------------------------------------

ProbeState WellSeismicScene::set_probe(double s_m, double z) {
    const FenceSection* fence = active_fence();
    if (fence == nullptr) {
        throw std::runtime_error("No active fence for probe");
    }
    probe_ = probe_from_fence_s(s_m, z, fence->vertices_xy,
                                survey_ ? &*survey_ : nullptr,
                                to_string(domain_));
    return *probe_;
}

std::optional<std::array<std::int64_t, 3>>
WellSeismicScene::probe_slice_indices() const {
    if (!probe_.has_value()) return std::nullopt;
    if (registration_.has_value()) {
        double z = probe_->z;
        if (probe_->domain == "depth") {
            // Depth m → time ms via the active transform (fail-closed:
            // throws when unavailable, exactly like the forward map).
            z = depth_transform_.depth_m_to_time_ms(z);
        }
        return registration_->world_xyz_to_volume(probe_->x, probe_->y, z);
    }
    return probe_->slice_indices(survey_ ? &*survey_ : nullptr);
}

// ---- World ↔ render coordinate maps ----------------------------------------------

std::vector<std::array<double, 3>>
WellSeismicScene::world_to_render_xyz_array(
    const std::vector<std::array<double, 3>>& points) const {
    if (points.empty()) return {};
    std::vector<std::array<double, 3>> out;
    out.reserve(points.size());
    if (registration_.has_value()) {
        for (const auto& p : points) {
            double z = p[2];
            if (domain_ == VerticalDomain::Depth) {
                z = depth_transform_.depth_m_to_time_ms(z);
            }
            const auto [vi, vx] = registration_->xy_to_volume_idx(p[0], p[1]);
            const double vt = registration_->time_ms_to_sample_idx(z);
            out.push_back({vi, vx, vt});
        }
        return out;
    }
    if (!survey_.has_value()) return points;
    const SurveySpec& s = *survey_;
    const double il_step =
        s.iline_step != 0 ? static_cast<double>(s.iline_step) : 1.0;
    const double xl_step =
        s.xline_step != 0 ? static_cast<double>(s.xline_step) : 1.0;
    for (const auto& p : points) {
        double z = p[2];
        if (domain_ == VerticalDomain::Depth) {
            z = depth_transform_.depth_m_to_time_ms(z);
        }
        const auto [il, xl] = s.xy_to_il_xl(p[0], p[1]);
        const double il_idx =
            (il - static_cast<double>(s.iline_start)) / il_step;
        const double xl_idx =
            (xl - static_cast<double>(s.xline_start)) / xl_step;
        const double t_idx = s.dt_ms != 0 ? (z - s.t0_ms) / s.dt_ms : z;
        out.push_back({il_idx, xl_idx, t_idx});
    }
    return out;
}

std::array<double, 3> WellSeismicScene::world_to_render_xyz(
    double x, double y, double z) const {
    return world_to_render_xyz_array({{{x, y, z}}}).front();
}

std::vector<std::array<double, 3>>
WellSeismicScene::render_to_world_xyz_array(
    const std::vector<std::array<double, 3>>& points) const {
    if (points.empty()) return {};
    std::vector<std::array<double, 3>> out;
    out.reserve(points.size());
    if (registration_.has_value()) {
        const SurveySpec& s = registration_->survey();
        const double il_step =
            s.iline_step != 0 ? static_cast<double>(s.iline_step) : 1.0;
        const double xl_step =
            s.xline_step != 0 ? static_cast<double>(s.xline_step) : 1.0;
        for (const auto& p : points) {
            const double il =
                static_cast<double>(s.iline_start) +
                p[0] * static_cast<double>(registration_->strides()[0]) *
                    il_step;
            const double xl =
                static_cast<double>(s.xline_start) +
                p[1] * static_cast<double>(registration_->strides()[1]) *
                    xl_step;
            const double z_ms =
                s.t0_ms +
                p[2] * static_cast<double>(registration_->strides()[2]) *
                    s.dt_ms;
            const auto [x, y] = s.il_xl_to_xy(il, xl);
            const double z = domain_ == VerticalDomain::Depth
                                 ? depth_transform_.time_ms_to_depth_m(z_ms)
                                 : z_ms;
            out.push_back({x, y, z});
        }
        return out;
    }
    if (survey_.has_value()) {
        const SurveySpec& s = *survey_;
        const double il_step =
            s.iline_step != 0 ? static_cast<double>(s.iline_step) : 1.0;
        const double xl_step =
            s.xline_step != 0 ? static_cast<double>(s.xline_step) : 1.0;
        for (const auto& p : points) {
            const double il =
                static_cast<double>(s.iline_start) + p[0] * il_step;
            const double xl =
                static_cast<double>(s.xline_start) + p[1] * xl_step;
            const double z_ms =
                s.dt_ms != 0 ? s.t0_ms + p[2] * s.dt_ms : p[2];
            const auto [x, y] = s.il_xl_to_xy(il, xl);
            const double z = domain_ == VerticalDomain::Depth
                                 ? depth_transform_.time_ms_to_depth_m(z_ms)
                                 : z_ms;
            out.push_back({x, y, z});
        }
        return out;
    }
    return points;
}

std::array<double, 3> WellSeismicScene::render_to_world_xyz(
    double i, double x, double t) const {
    return render_to_world_xyz_array({{{i, x, t}}}).front();
}

// ---- Persisted joint state (version-compatible JSON) -------------------------

namespace {

constexpr int kJointStateVersion = 1;

Json slice_state_to_json(const OrthogonalSliceState& state) {
    Json j = Json::object();
    if (state.inline_index.has_value()) {
        j["inline_index"] = *state.inline_index;
    }
    if (state.crossline_index.has_value()) {
        j["crossline_index"] = *state.crossline_index;
    }
    Json slices = Json::array();
    for (const TimeSliceState& slice : state.time_slices) {
        slices.push_back(Json{{"time_ms", slice.time_ms},
                              {"visible", slice.visible}});
    }
    j["time_slices"] = std::move(slices);
    if (state.active_time_ms.has_value()) {
        j["active_time_ms"] = *state.active_time_ms;
    }
    j["time_opacity"] = state.time_opacity;
    return j;
}

std::optional<OrthogonalSliceState> slice_state_from_json(
    const Json& j) {
    // Per-entry degradation (ADR-03 parity): unknown/invalid entries are
    // skipped, never fatal for the whole restore.
    if (!j.is_object()) return std::nullopt;
    std::optional<std::int64_t> il;
    if (j.contains("inline_index") && j["inline_index"].is_number_integer()) {
        il = j["inline_index"].get<std::int64_t>();
    }
    std::optional<std::int64_t> xl;
    if (j.contains("crossline_index") &&
        j["crossline_index"].is_number_integer()) {
        xl = j["crossline_index"].get<std::int64_t>();
    }
    std::vector<TimeSliceState> slices;
    if (j.contains("time_slices") && j["time_slices"].is_array()) {
        for (const Json& item : j["time_slices"]) {
            if (!item.is_object() || !item.contains("time_ms") ||
                !item["time_ms"].is_number()) {
                continue;
            }
            const bool visible =
                item.value("visible", true);  // "false" never truthifies
            try {
                slices.emplace_back(item["time_ms"].get<double>(),
                                    visible);
            } catch (const std::invalid_argument&) {
                continue;
            }
        }
    }
    std::optional<double> active;
    if (j.contains("active_time_ms") &&
        j["active_time_ms"].is_number()) {
        active = j["active_time_ms"].get<double>();
    }
    double opacity = 0.8;
    if (j.contains("time_opacity") && j["time_opacity"].is_number()) {
        const double raw = j["time_opacity"].get<double>();
        if (raw >= 0.0 && raw <= 1.0) opacity = raw;
    }
    try {
        return OrthogonalSliceState(il, xl, std::move(slices), active,
                                    opacity);
    } catch (const std::invalid_argument&) {
        return std::nullopt;
    }
}

}  // namespace

std::string WellSeismicScene::joint_state_to_json() const {
    Json j = Json::object();
    j["version"] = kJointStateVersion;
    j["vertical_domain"] = to_string(domain_);
    Json display = Json::object();
    display["seismic_color_scale"] = display_settings_.seismic_color_scale;
    display["gr_color_scale"] = display_settings_.gr_color_scale;
    display["well_width_px"] = display_settings_.well_width_px;
    j["display_settings"] = std::move(display);
    j["orthogonal_slice_state"] = slice_state_to_json(slice_state_);
    j["near_well_m"] = near_well_m_;
    j["curve_names"] = curve_names_;
    j["preview_mode"] = preview_mode_;

    Json depth = Json::object();
    switch (depth_transform_.kind()) {
        case DepthTransformKind::None:
            depth["kind"] = "none";
            break;
        case DepthTransformKind::ExternalVolume:
            depth["kind"] = "external_volume";
            depth["v0_m_s"] = depth_transform_.constant().v0_m_s();
            break;
        case DepthTransformKind::ConstantV0:
            depth["kind"] = "constant_v0";
            depth["v0_m_s"] = depth_transform_.constant().v0_m_s();
            break;
        case DepthTransformKind::WellTzField:
            depth["kind"] = "well_tz_field";
            depth["v0_m_s"] = depth_transform_.constant().v0_m_s();
            break;
    }
    j["depth_transform"] = std::move(depth);

    Json fences = Json::array();
    for (const FenceSection& fence : fences_) {
        Json fj = Json::object();
        fj["id"] = fence.id;
        fj["name"] = fence.name;
        fj["visible"] = fence.visible;
        Json verts = Json::array();
        for (const auto& v : fence.vertices_xy) {
            verts.push_back(Json::array({v[0], v[1]}));
        }
        fj["vertices_xy"] = std::move(verts);
        fences.push_back(std::move(fj));
    }
    j["fences"] = std::move(fences);
    if (active_fence_id_.has_value()) {
        j["active_fence_id"] = *active_fence_id_;
    }
    j["fence_well_ids"] = fence_well_ids_;
    return j.dump();
}

bool WellSeismicScene::restore_joint_state(
    const std::string& json, std::vector<std::string>* restored_fences) {
    Json parsed = Json::parse(json, nullptr, false);
    if (parsed.is_discarded() || !parsed.is_object() ||
        !parsed.contains("version") ||
        !parsed["version"].is_number_integer() ||
        parsed["version"].get<int>() != kJointStateVersion) {
        // Not a joint-state object of a known version: nothing restored,
        // no state change (old/foreign payloads stay readable).
        return false;
    }
    if (parsed.contains("display_settings") &&
        parsed["display_settings"].is_object()) {
        const Json& d = parsed["display_settings"];
        try {
            display_settings_ =
                JointDisplaySettings(d.value("seismic_color_scale",
                                             "blue-white-red"),
                                     d.value("gr_color_scale", "viridis"),
                                     d.value("well_width_px", 5));
        } catch (const std::invalid_argument&) {
            // Keep defaults on invalid width.
        }
    }
    if (parsed.contains("orthogonal_slice_state")) {
        if (auto state =
                slice_state_from_json(parsed["orthogonal_slice_state"])) {
            restore_orthogonal_slice_state(std::move(*state));
        }
    }
    if (parsed.contains("near_well_m") &&
        parsed["near_well_m"].is_number()) {
        near_well_m_ = parsed["near_well_m"].get<double>();
    }
    if (parsed.contains("curve_names") &&
        parsed["curve_names"].is_array()) {
        std::vector<std::string> names;
        for (const Json& n : parsed["curve_names"]) {
            if (n.is_string()) names.push_back(n.get<std::string>());
        }
        set_curve_names(std::move(names));
    }
    if (parsed.contains("depth_transform") &&
        parsed["depth_transform"].is_object()) {
        const Json& d = parsed["depth_transform"];
        const std::string kind = d.value("kind", "none");
        const double v0 = d.value("v0_m_s", 3000.0);
        if (kind == "external_volume") {
            set_depth_transform(DepthTransformState::external_volume(v0));
        } else if (kind == "constant_v0") {
            set_depth_transform(DepthTransformState::constant_v0(v0));
        } else if (kind == "well_tz_field") {
            set_depth_transform(DepthTransformState::well_tz_field(v0));
        } else {
            set_depth_transform(DepthTransformState::none());
        }
    }
    if (parsed.contains("vertical_domain") &&
        parsed["vertical_domain"].is_string()) {
        const std::string domain = parsed["vertical_domain"].get<std::string>();
        // Fail-closed: an unavailable Depth stays Time (a stored Depth
        // state without a transform is stale, not a mandate to fake it).
        if (domain == "time") {
            set_vertical_domain(VerticalDomain::Time);
        } else if (domain == "depth") {
            try {
                set_vertical_domain(VerticalDomain::Depth);
            } catch (const std::invalid_argument&) {
                set_vertical_domain(VerticalDomain::Time);
            }
        }
    }
    if (parsed.contains("fences") && parsed["fences"].is_array()) {
        fences_.clear();
        well_order_fence_id_.reset();
        extract_cache_.clear();
        for (const Json& fj : parsed["fences"]) {
            if (!fj.is_object() || !fj.contains("vertices_xy") ||
                !fj["vertices_xy"].is_array()) {
                continue;
            }
            std::vector<std::array<double, 2>> verts;
            for (const Json& v : fj["vertices_xy"]) {
                if (v.is_array() && v.size() == 2 && v[0].is_number() &&
                    v[1].is_number()) {
                    verts.push_back({v[0].get<double>(), v[1].get<double>()});
                }
            }
            if (verts.size() < 2) continue;
            try {
                FenceSection fence(
                    fj.value("name", "Wells"), std::move(verts),
                    fj.value("id", std::string()));
                const std::string id = fence.id;
                add_fence(std::move(fence), false);
                set_fence_visible(id, fj.value("visible", true));
                if (restored_fences != nullptr) {
                    restored_fences->push_back(id);
                }
            } catch (const std::invalid_argument&) {
                continue;
            }
        }
        active_fence_id_.reset();
        if (parsed.contains("active_fence_id") &&
            parsed["active_fence_id"].is_string()) {
            const std::string id =
                parsed["active_fence_id"].get<std::string>();
            for (const FenceSection& fence : fences_) {
                if (fence.id == id) {
                    active_fence_id_ = id;
                    break;
                }
            }
        }
        if (!active_fence_id_.has_value() && !fences_.empty()) {
            active_fence_id_ = fences_.back().id;
        }
    }
    if (parsed.contains("fence_well_ids") &&
        parsed["fence_well_ids"].is_array()) {
        fence_well_ids_.clear();
        const std::set<JointWellId> known(well_ids_.begin(),
                                          well_ids_.end());
        for (const Json& id : parsed["fence_well_ids"]) {
            if (id.is_string()) {
                const JointWellId value = id.get<std::string>();
                if (known.count(value) != 0) {
                    fence_well_ids_.push_back(value);
                }
            }
        }
    }
    if (parsed.contains("preview_mode")) {
        preview_mode_ = parsed.value("preview_mode", true);
    }
    return true;
}

}  // namespace pwb::geo3d_viz::joint
