#include "pwb/ui_workers/contour_draft.hpp"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <limits>
#include <set>

namespace pwb::ui_workers {

namespace {

std::string default_id() {
    static std::atomic<unsigned long long> counter{0};
    return "__cpp_id_" + std::to_string(++counter);
}

IdFn id_fn_or_default(const IdFn& id_fn) {
    if (id_fn) return id_fn;
    return [] { return default_id(); };
}

// _grid_from_task — prefers the resolved FactorGridResult grid carried on
// the slice; falls back to legacy `parameters` lists with the same
// ValueError diagnostics as Python.
struct ResolvedGrid {
    std::vector<double> x;
    std::vector<double> y;
    Grid2D z;
};

[[noreturn]] void throw_missing_grid() {
    throw PyValueError(
        "FactorMapTask 缺少 grid_x/grid_y/grid_z，请先完成插值");
}

template <typename T>
std::vector<double> to_double_vector(const std::any& value, bool* ok) {
    std::vector<double> out;
    if (const auto* v = std::any_cast<std::vector<T>>(&value)) {
        out.reserve(v->size());
        for (const T& item : *v) out.push_back(static_cast<double>(item));
        *ok = true;
    }
    return out;
}

std::vector<double> any_to_double_vector(const std::any& value, bool* ok) {
    *ok = false;
    for (auto fn : {to_double_vector<double>, to_double_vector<float>,
                    to_double_vector<int>, to_double_vector<long long>,
                    to_double_vector<std::int64_t>,
                    to_double_vector<unsigned>}) {
        auto out = fn(value, ok);
        if (*ok) return out;
    }
    if (const auto* v = std::any_cast<std::vector<std::any>>(&value)) {
        std::vector<double> out;
        out.reserve(v->size());
        for (const auto& item : *v) {
            if (const auto* d = std::any_cast<double>(&item))
                out.push_back(*d);
            else if (const auto* f = std::any_cast<float>(&item))
                out.push_back(*f);
            else if (const auto* i = std::any_cast<int>(&item))
                out.push_back(*i);
            else if (const auto* i64 = std::any_cast<std::int64_t>(&item))
                out.push_back(static_cast<double>(*i64));
            else
                out.push_back(std::numeric_limits<double>::quiet_NaN());
        }
        *ok = true;
        return out;
    }
    return {};
}

// Legacy `parameters` rows -> Grid2D (None cells become NaN, like the
// object-dtype coercion in Python).
Grid2D any_to_grid(const std::any& value, bool* ok) {
    *ok = false;
    const auto* rows_any = std::any_cast<std::vector<std::any>>(&value);
    const auto* rows_vec =
        std::any_cast<std::vector<std::vector<double>>>(&value);
    Grid2D grid;
    if (rows_vec) {
        grid.rows = rows_vec->size();
        grid.cols = rows_vec->empty() ? 0 : rows_vec->front().size();
        grid.data.reserve(grid.rows * grid.cols);
        for (const auto& row : *rows_vec) {
            for (double v : row) grid.data.push_back(v);
        }
        *ok = true;
        return grid;
    }
    if (!rows_any) return grid;
    grid.rows = rows_any->size();
    std::size_t cols = 0;
    std::vector<double> data;
    for (const auto& row_any : *rows_any) {
        bool row_ok = false;
        auto row = any_to_double_vector(row_any, &row_ok);
        if (!row_ok) {
            // Non-sequence row -> the numpy asarray would produce ndim != 2.
            throw PyValueError("grid_z 维数错误");
        }
        if (cols == 0) cols = row.size();
        for (double v : row) data.push_back(v);
    }
    grid.cols = cols;
    grid.data = std::move(data);
    *ok = true;
    return grid;
}

ResolvedGrid grid_from_task(const FactorTaskSlice& task) {
    // Resolved FactorGridResult path (factor_grid_result_for_task collected
    // host-side) — no exception fallback needed in the slice world: absent
    // grids are simply not present.
    if (task.grid_x && task.grid_y && task.grid_z && !task.grid_x->empty() &&
        !task.grid_y->empty() && !task.grid_z->empty()) {
        return {*task.grid_x, *task.grid_y, *task.grid_z};
    }
    // Legacy parameters fallback (the `or {}` / `.get()` dance in Python).
    const auto gx_it = task.parameters.find("grid_x");
    const auto gy_it = task.parameters.find("grid_y");
    const auto gz_it = task.parameters.find("grid_z");
    const bool gx_missing = gx_it == task.parameters.end() ||
                            !gx_it->second.has_value();
    const bool gy_missing = gy_it == task.parameters.end() ||
                            !gy_it->second.has_value();
    const bool gz_missing = gz_it == task.parameters.end() ||
                            !gz_it->second.has_value();
    if (gx_missing || gy_missing || gz_missing) throw_missing_grid();

    bool ok_x = false, ok_y = false, ok_z = false;
    auto x = any_to_double_vector(gx_it->second, &ok_x);
    auto y = any_to_double_vector(gy_it->second, &ok_y);
    Grid2D z;
    try {
        z = any_to_grid(gz_it->second, &ok_z);
    } catch (const PyStyleError&) {
        throw;
    }
    if (!ok_x || !ok_y || !ok_z || x.empty() || y.empty() || z.rows == 0) {
        throw_missing_grid();
    }
    return {std::move(x), std::move(y), std::move(z)};
}

// _engine_contours_for_task — stored refined isolines reused when the level
// request matches what was generated (abs_tol=1e-6 per level).
struct EngineContours {
    std::vector<ContourSegmentSlice> segments;
    std::vector<double> stored_levels;
};

std::optional<EngineContours> engine_contours_for_task(
    const FactorTaskSlice& task,
    const std::optional<std::vector<double>>& requested_levels,
    const IdFn& id_fn) {
    if (!task.engine_contours || task.engine_contours->empty()) {
        return std::nullopt;
    }
    if (!task.stored_contour_levels || task.stored_contour_levels->empty()) {
        return std::nullopt;
    }
    const auto& stored = *task.stored_contour_levels;
    if (requested_levels &&
        !(requested_levels->size() == stored.size() &&
          std::equal(requested_levels->begin(), requested_levels->end(),
                     stored.begin(), [](double a, double b) {
                         return std::fabs(a - b) <= 1e-6;
                     }))) {
        return std::nullopt;
    }
    // Sorted by float(level_str) — Python sorts kv pairs by float key.
    std::vector<std::pair<double, const std::vector<std::vector<
                                      std::pair<double, double>>>*>>
        ordered;
    ordered.reserve(task.engine_contours->size());
    for (const auto& [level_str, lines] : *task.engine_contours) {
        // float(level_str) parity: a corrupt key raises ValueError which
        // the caller's except (ValueError, ImportError) turns into a
        // whole-task skip — strict-parse so the same propagates.
        std::size_t pos = 0;
        const double level = std::stod(level_str, &pos);
        if (pos != level_str.size()) {
            throw std::invalid_argument(
                "could not convert string to float: '" + level_str + "'");
        }
        ordered.push_back({level, &lines});
    }
    std::sort(ordered.begin(), ordered.end(),
              [](const auto& a, const auto& b) { return a.first < b.first; });

    EngineContours out;
    out.stored_levels = stored;
    for (const auto& [level, lines] : ordered) {
        for (const auto& line : *lines) {
            if (line.size() < 2) continue;
            // math.isclose(first, last, abs_tol=1e-9) — Python keeps the
            // default rel_tol=1e-9 alongside, so use py_isclose (both).
            const bool closed =
                line.size() >= 3 &&
                py_isclose(line.front().first, line.back().first, 1e-9,
                           1e-9) &&
                py_isclose(line.front().second, line.back().second, 1e-9,
                           1e-9);
            ContourSegmentSlice seg;
            seg.id = id_fn();
            seg.level = level;
            seg.coordinates = line;
            seg.closed = closed;
            seg.properties["level"] = level;
            seg.properties["refined"] = true;
            out.segments.push_back(std::move(seg));
        }
    }
    if (out.segments.empty()) return std::nullopt;
    return out;
}

// _segments_from_lines_dict — sorted levels, >=2-point Nx2 lines only.
std::vector<ContourSegmentSlice> segments_from_lines_dict(
    const std::map<double, std::vector<std::vector<std::pair<double, double>>>>&
        lines_dict,
    const IdFn& id_fn) {
    std::vector<ContourSegmentSlice> segments;
    for (const auto& [level, lines] : lines_dict) {
        for (const auto& line : lines) {
            if (line.size() < 2) continue;
            // math.isclose(first, last, abs_tol=1e-9) — Python keeps the
            // default rel_tol=1e-9 alongside, so use py_isclose (both).
            const bool closed =
                line.size() >= 3 &&
                py_isclose(line.front().first, line.back().first, 1e-9,
                           1e-9) &&
                py_isclose(line.front().second, line.back().second, 1e-9,
                           1e-9);
            ContourSegmentSlice seg;
            seg.id = id_fn();
            seg.level = level;
            seg.coordinates = line;
            seg.closed = closed;
            seg.properties["level"] = level;
            segments.push_back(std::move(seg));
        }
    }
    return segments;
}

}  // namespace

std::vector<double> suggest_nice_levels_from_range(double lo, double hi,
                                                   int n_levels) {
    if (!std::isfinite(lo) || !std::isfinite(hi)) return {};
    if (py_isclose(lo, hi)) return {lo};
    const double raw = (hi - lo) / std::max(n_levels, 1);
    const double magnitude =
        raw > 0 ? std::pow(10.0, std::floor(std::log10(raw))) : 1.0;
    double step = 10.0 * magnitude;
    for (double multiplier : {1.0, 2.0, 2.5, 5.0}) {
        const double candidate = multiplier * magnitude;
        if (candidate >= raw) {
            step = candidate;
            break;
        }
    }
    std::vector<double> levels;
    double level = std::ceil(lo / step) * step;
    int guard = 0;
    while (level <= hi && guard < 512) {
        if (!(py_isclose(level, lo) || py_isclose(level, hi))) {
            levels.push_back(py_round(level, 6));
        }
        level += step;
        ++guard;
    }
    return levels;
}

std::vector<double> suggest_levels_fallback(double lo, double hi,
                                            int n_levels) {
    // geoviz suggest_levels: linspace(lo, hi, n+2)[1:-1], round 6.
    if (!std::isfinite(lo) || !std::isfinite(hi)) return {};
    if (py_isclose(lo, hi)) return {lo};
    const int n = std::max(2, n_levels);
    const auto spaced = np_linspace(lo, hi, static_cast<std::size_t>(n) + 2);
    std::vector<double> levels;
    for (std::size_t i = 1; i + 1 < spaced.size(); ++i) {
        levels.push_back(py_round(spaced[i], 6));
    }
    return levels;
}

std::vector<double> suggest_nice_levels(const Grid2D& grid_z, int n_levels) {
    double lo = std::numeric_limits<double>::infinity();
    double hi = -std::numeric_limits<double>::infinity();
    bool any = false;
    for (double v : grid_z.data) {
        if (std::isfinite(v)) {
            lo = std::min(lo, v);
            hi = std::max(hi, v);
            any = true;
        }
    }
    if (!any) return {};
    auto levels = suggest_nice_levels_from_range(lo, hi, n_levels);
    if (!levels.empty()) return levels;
    return suggest_levels_fallback(lo, hi, n_levels);
}

ContourDraftSlice upsert_contour_draft(
    ContourDraftSlice draft, std::vector<ContourDraftSlice>& existing,
    const std::string& updated_at) {
    draft.updated_at = updated_at;
    for (std::size_t i = 0; i < existing.size(); ++i) {
        const auto& ex = existing[i];
        const bool same_task = !draft.linked_factor_task_id.empty() &&
                               ex.linked_factor_task_id ==
                                   draft.linked_factor_task_id;
        const bool same_scope = draft.linked_factor_task_id.empty() &&
                                ex.target_horizon == draft.target_horizon &&
                                ex.factor_type == draft.factor_type &&
                                ex.generator_version ==
                                    kContourDraftGeneratorVersion;
        if (same_task || same_scope) {
            draft.id = ex.id;
            draft.updated_at = updated_at;
            existing[i] = draft;
            return draft;
        }
    }
    existing.push_back(draft);
    return draft;
}

std::vector<std::map<std::string, std::any>> line_features_from_contour_draft(
    const ContourDraftSlice& draft) {
    std::vector<std::map<std::string, std::any>> features;
    for (const auto& seg : draft.segments) {
        if (seg.coordinates.size() < 2) continue;
        std::map<std::string, std::any> feature;
        feature["id"] = seg.id;
        feature["kind"] = std::string("line");
        char name_buf[64];
        std::snprintf(name_buf, sizeof(name_buf), "L=%g", seg.level);
        feature["name"] = std::string(name_buf);
        feature["role"] = std::string("contour");
        std::vector<std::any> coords;
        coords.reserve(seg.coordinates.size());
        for (const auto& p : seg.coordinates) {
            coords.push_back(std::vector<double>{p.first, p.second});
        }
        feature["coordinates"] = coords;
        std::map<std::string, std::any> props;
        props["role"] = std::string("contour");
        props["constraint_role"] = std::string("contour");
        props["level"] = seg.level;
        props["closed"] = seg.closed;
        props["contour_draft_id"] = draft.id;
        props["factor_type"] = draft.factor_type;
        props["target_horizon"] = draft.target_horizon;
        for (const auto& [k, v] : seg.properties) props[k] = v;
        feature["properties"] = props;
        features.push_back(std::move(feature));
    }
    return features;
}

ContourDraftSlice contour_draft_from_factor_task(
    const FactorTaskSlice& task,
    const std::optional<std::vector<double>>& levels, int n_levels,
    const std::optional<std::string>& name,
    const job::CancellationToken& token, const ExtractLinesFn& extract_lines_fn,
    const IdFn& id_fn_raw) {
    const IdFn id_fn = id_fn_or_default(id_fn_raw);
    const ResolvedGrid grid = grid_from_task(task);

    double zmin = std::numeric_limits<double>::infinity();
    double zmax = -std::numeric_limits<double>::infinity();
    bool any = false;
    for (double v : grid.z.data) {
        if (std::isfinite(v)) {
            zmin = std::min(zmin, v);
            zmax = std::max(zmax, v);
            any = true;
        }
    }
    if (!any) {
        throw PyValueError("网格无有效数值，无法生成等值线");
    }

    std::vector<double> use_levels =
        levels ? *levels : suggest_nice_levels(grid.z, n_levels);
    if (use_levels.empty()) use_levels = {zmin};

    std::vector<ContourSegmentSlice> segments;
    if (auto engine = engine_contours_for_task(task, levels, id_fn)) {
        segments = std::move(engine->segments);
        use_levels = engine->stored_levels;
    } else {
        if (!extract_lines_fn) {
            throw PyImportError(
                "geoviz.extract_contour_lines unavailable; ensure geoviz "
                "facade is installed");
        }
        auto lines_dict =
            extract_lines_fn(grid.x, grid.y, grid.z, use_levels, token);
        segments = segments_from_lines_dict(lines_dict, id_fn);
    }

    const std::string factor_label =
        !task.factor_type.empty() ? task.factor_type : task.name;
    ContourDraftSlice draft;
    draft.id = id_fn();
    draft.name = name && !name->empty()
                     ? *name
                     : task.target_horizon + " " + factor_label + " 等值线初稿";
    draft.target_horizon = task.target_horizon;
    draft.factor_type = task.factor_type;
    draft.linked_factor_task_id = task.id;
    draft.levels = use_levels;
    draft.segments = std::move(segments);
    // `parameters.get("grid_n") or len(grid_x)` — falsy values fall back.
    const int grid_n = param_int(task, "grid_n").value_or(0);
    draft.source_grid_n =
        grid_n != 0 ? grid_n : static_cast<int>(grid.x.size());
    const auto backend = param_str(task, "interp_backend");
    draft.source_backend =
        backend.value_or(!task.method.empty() ? task.method : "");
    draft.source_value_range = {zmin, zmax};
    draft.status = "draft";
    draft.generator_version = kContourDraftGeneratorVersion;
    return draft;
}

ContourDraftSlice compile_contour_draft_from_task(
    const FactorTaskSlice& task, std::vector<ContourDraftSlice>& ledger,
    const std::optional<std::vector<double>>& levels, int n_levels,
    const job::CancellationToken& token, const ExtractLinesFn& extract_lines_fn,
    const IdFn& id_fn, const std::string& updated_at) {
    auto draft = contour_draft_from_factor_task(
        task, levels, n_levels, std::nullopt, token, extract_lines_fn, id_fn);
    return upsert_contour_draft(std::move(draft), ledger, updated_at);
}

std::vector<ContourDraftSlice> compile_contour_drafts_for_project(
    const std::vector<FactorTaskSlice>& factor_map_tasks,
    std::vector<ContourDraftSlice>& ledger,
    const std::optional<std::set<std::string>>& task_ids, bool only_complete,
    int n_levels, const job::CancellationToken& token,
    const ExtractLinesFn& extract_lines_fn, const IdFn& id_fn,
    const std::string& updated_at) {
    std::vector<ContourDraftSlice> drafts;
    for (const auto& task : factor_map_tasks) {
        token.check_cancelled();
        if (task_ids && !task_ids->count(task.id)) continue;
        if (only_complete && task.status != "complete") continue;
        try {
            auto draft = compile_contour_draft_from_task(
                task, ledger, std::nullopt, n_levels, token, extract_lines_fn,
                id_fn, updated_at);
            drafts.push_back(std::move(draft));
        } catch (const PyValueError&) {
            continue;
        } catch (const PyImportError&) {
            continue;
        } catch (const std::invalid_argument&) {
            // Seam-thrown ValueError equivalents skip the same way.
            continue;
        }
    }
    token.check_cancelled();
    return drafts;
}

ContourDraftResult run_contour_drafts(const ContourDraftInput& input,
                                      job::JobContext& ctx) {
    return with_py_errors([&]() -> ContourDraftResult {
        ctx.check_cancelled();
        auto ledger = input.contour_drafts;  // snapshot copy semantics
        auto drafts = compile_contour_drafts_for_project(
            input.factor_map_tasks, ledger, std::nullopt, /*only_complete=*/true,
            input.n_levels, ctx.token(), input.extract_lines_fn, input.id_fn,
            input.updated_at);
        ctx.check_cancelled();
        return {std::move(drafts), std::move(ledger)};
    });
}

job::JobSpec make_contour_draft_job_spec(
    ContourDraftInput input,
    std::function<void(const ContourDraftResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel, std::function<void()> on_terminal) {
    job::JobSpec spec;
    spec.kind = "compute.contour_draft";
    spec.title = "等值线初稿提取";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_contour_drafts(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done),
                    on_terminal](const std::any& result) {
        if (on_done) on_done(std::any_cast<const ContourDraftResult&>(result));
        if (on_terminal) on_terminal();
    };
    spec.on_fail = [on_fail = std::move(on_fail),
                    on_terminal](const std::string& error) {
        if (on_fail) on_fail(error);
        if (on_terminal) on_terminal();
    };
    spec.on_cancel = [on_cancel = std::move(on_cancel), on_terminal]() {
        if (on_cancel) on_cancel();
        if (on_terminal) on_terminal();
    };
    return spec;
}

}  // namespace pwb::ui_workers
