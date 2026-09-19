#include "pwb/ui_workers/correlation_load.hpp"

#include <algorithm>
#include <filesystem>
#include <set>

namespace pwb::ui_workers {

std::vector<ResourceSlice> list_well_log_resources(
    const std::vector<ResourceSlice>& resources) {
    std::vector<ResourceSlice> wells;
    for (const auto& r : resources) {
        if (r.type == "well_log") wells.push_back(r);
    }
    std::sort(wells.begin(), wells.end(), [](const auto& a, const auto& b) {
        return std::tie(a.name, a.id) < std::tie(b.name, b.id);
    });
    return wells;
}

CorrelationLoadResult load_correlation_wells(
    const CorrelationLoadInput& input) {
    auto wells = list_well_log_resources(input.project.resources);
    if (input.resource_ids) {
        const std::set<std::string> wanted(input.resource_ids->begin(),
                                           input.resource_ids->end());
        std::vector<ResourceSlice> filtered;
        for (const auto& r : wells) {
            if (wanted.count(r.id)) filtered.push_back(r);
        }
        wells = std::move(filtered);
    }
    const int cap = std::max(1, input.max_wells);
    if (wells.size() > static_cast<std::size_t>(cap)) {
        wells.resize(static_cast<std::size_t>(cap));
    }

    CorrelationLoadResult out;
    const bool has_task = input.project.prediction_task.has_value();
    for (const auto& resource : wells) {
        auto ref = ref_from_resource(resource);
        if (!ref) {
            out.warnings.push_back("跳过 " + resource.name + ": 不支持可视化");
            continue;
        }
        if (!input.seams.resolve_fn) {
            throw KernelUnavailable("VizAdapter.resolve");
        }
        VizPayloadSlice payload = input.seams.resolve_fn(*ref, input.project);
        std::any data = payload.well_log;
        if (!data.has_value()) {
            out.warnings.push_back(
                "跳过 " + resource.name + ": " +
                (!payload.message.empty() ? payload.message : "无法加载 LAS"));
            continue;
        }
        if (input.project.attach_prediction_facies && has_task) {
            // merge_prediction_onto_well_log is unconditional in Python
            // when attach && task — an unbound seam is a host
            // misconfiguration, not a skip.
            if (!input.seams.merge_prediction_fn) {
                throw KernelUnavailable("merge_prediction_onto_well_log");
            }
            data = input.seams.merge_prediction_fn(
                data, input.project.prediction_task);
        }
        out.logs.push_back(data);
        // str(getattr(data,"well_name","") or Path(name).stem or id)
        std::string well_name;
        if (input.seams.well_name_fn) {
            well_name = input.seams.well_name_fn(data);
        }
        if (well_name.empty()) {
            well_name = std::filesystem::path(resource.name).stem().string();
        }
        if (well_name.empty()) well_name = resource.id;
        out.names.push_back(well_name);
        out.loaded_ids.push_back(resource.id);
    }
    return out;
}

CorrelationLoadResult run_correlation_load(const CorrelationLoadInput& input,
                                           job::JobContext& ctx) {
    // threading.Event boundary checks — pre-load and post-load only.
    ctx.check_cancelled();
    CorrelationLoadResult result;
    try {
        result = input.loader_fn ? input.loader_fn(input)
                                 : load_correlation_wells(input);
    } catch (const job::JobCancelled& exc) {
        // Python's blanket `except Exception` treats JobCancelled like any
        // other failure — cancelled.emit() iff the flag is set, else
        // failed("JobCancelled: <msg>"). Only rethrow as cancellation
        // when the outer token was actually cancelled.
        if (ctx.token().is_cancelled()) {
            throw;
        }
        throw PyStyleError("JobCancelled", exc.what());
    } catch (const std::exception& exc) {
        if (ctx.token().is_cancelled()) {
            ctx.check_cancelled();
        }
        rethrow_as_py_error(exc);
    }
    ctx.check_cancelled();
    return result;
}

job::JobSpec make_correlation_load_job_spec(
    CorrelationLoadInput input,
    std::function<void(const CorrelationLoadResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "load.correlation";
    spec.title = "连井剖面加载";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_correlation_load(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const CorrelationLoadResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

}  // namespace pwb::ui_workers
