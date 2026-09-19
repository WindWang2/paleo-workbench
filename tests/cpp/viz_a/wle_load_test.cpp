// viz_a.wle_load — the production WLE load_fn for the well_log worker
// seam: real parses over the frozen fixtures (payload type, well name,
// curve facts), honest nullopt for non-LAS/unreadable/unparseable paths,
// cooperative cancellation propagation, resolve integration, and the
// worker-level cancel semantics (pre-cancel and post-completion).

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>

#include <welllog/core/document.hpp>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/well_log_load.hpp>
#include <pwb/ui_workers/wle_load.hpp>

using namespace pwb::ui_workers;
namespace fs = std::filesystem;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::string fixture(const std::string& rel) {
    return (fs::path(PWB_VIZ_A_FIXTURE_ROOT) / rel).string();
}

}  // namespace

int main() {
    const auto load_fn = make_wle_load_fn();
    const std::function<bool()> never_cancel = [] { return false; };

    // Real load of an accepted fixture: payload carries the WLE document.
    const std::string las = fixture("las/01_normal_multisection.las");
    auto loaded = load_fn(las, never_cancel);
    check(loaded.has_value(), "accepted fixture loads");
    if (loaded) {
        check(loaded->well_name.find("\xE4\xBA\x95") != std::string::npos,
              "unicode well name scanned");  // 井
        auto payload = std::any_cast<pwb::ui_workers::WleDocumentPayload>(
            loaded->data);
        const auto& document = payload.document;
        check(document != nullptr, "payload type is the WLE document");
        check(payload.diagnostics == 0, "clean fixture has no diagnostics");
        check(document->sampling_axes().size() == 1, "one sampling axis");
        check(document->sampling_axes().front().coordinates.length() == 5,
              "row count (5 accepted rows)");
        check(document->curves().size() == 3, "3 non-depth curves");
        check(document->curves().front().mnemonic == "GR" &&
                  document->curves().front().unit == "GAPI",
              "curve mnemonic/unit");
        // Null sentinel row -> NaN + null bitmap (row 3, GR = -999.25).
        bool gr_null = false;
        for (const auto& curve : document->curves()) {
            if (curve.mnemonic == "GR") {
                const auto value = curve.values.value_as_double(2);
                gr_null = value && std::isnan(*value);
            }
        }
        check(gr_null, "null sentinel becomes NaN");
    }

    // WLE-rejected fixture: honest nullopt (viz_resolve turns this into the
    // message payload).
    check(!load_fn(fixture("las/11_missing_vers.las"), never_cancel).has_value(),
          "missing VERS is nullopt");

    // Non-LAS resources stay on the message path (no fabricated parse).
    check(!load_fn(fixture("las/01_normal_multisection.las") + ".xml", never_cancel)
               .has_value(),
          "xml path is nullopt");
    check(!load_fn("/nonexistent/x.las", never_cancel).has_value(),
          "unreadable path is nullopt");

    // Pre-cancel propagates honestly.
    bool threw_cancelled = false;
    try {
        (void)load_fn(las, [] { return true; });
    } catch (const WellLogLoadCancelled&) {
        threw_cancelled = true;
    }
    check(threw_cancelled, "pre-cancel throws WellLogLoadCancelled");

    // resolve integration: well_log kind assembles the payload slice.
    VizRefSlice ref;
    ref.kind = "well_log";
    ref.id = "r1";
    ref.label = "curve";
    std::vector<ResourceSlice> resources;
    ResourceSlice res;
    res.id = "r1";
    res.name = "01";
    res.path = las;
    res.type = "well_log";
    res.format = "las";
    resources.push_back(res);
    auto payload = viz_resolve(ref, resources, "", never_cancel, load_fn);
    check(payload.kind == "well_log", "resolve payload kind");
    check(payload.well_log.has_value() && payload.well_names.size() == 1,
          "resolve payload carries document + name");

    // resolve for a missing file: honest message payload.
    res.path = "/nonexistent/x.las";
    resources[0] = res;
    payload = viz_resolve(ref, resources, "", never_cancel, load_fn);
    check(payload.kind == "message" &&
              payload.message.find("\xE4\xB8\x8D\xE5\xAD\x98\xE5\x9C\xA8") !=
                  std::string::npos,
          "missing file message payload");  // 不存在

    // Worker-level semantics over the production adapter.
    const auto spec = [&] {
        WellLogLoadInput input;
        input.ref = ref;
        input.resources = resources;
        input.load_fn = load_fn;
        return input;
    };

    // (a) pre-cancel: JobCancelled, no parse, no cancelling hint.
    {
        auto input = spec();
        input.ref.kind = "well_log";
        input.resources[0].path = las;
        input.phase->cancel_requested = true;
        bool cancelling_hint = false;
        request_well_log_cancel(input.phase, [&] { cancelling_hint = true; });
        check(!cancelling_hint, "pre-cancel emits no cancelling hint");
        pwb::job::JobContext ctx{"viz-a-test", pwb::job::CancellationToken{}};
        bool job_cancelled = false;
        try {
            (void)run_well_log_load(input, ctx);
        } catch (const pwb::job::JobCancelled&) {
            job_cancelled = true;
        }
        check(job_cancelled, "worker pre-cancel -> JobCancelled");
    }

    // (b) normal run returns the payload; a cancel AFTER completion cannot
    // retroactively cancel it (late-result discard only applies to results
    // arriving after the flag was set).
    {
        auto input = spec();
        input.resources[0].path = las;
        pwb::job::JobContext ctx{"viz-a-test", pwb::job::CancellationToken{}};
        auto result = run_well_log_load(input, ctx);
        check(result.payload.kind == "well_log", "worker run payload kind");
        const bool cancelled_flag_before =
            input.phase->cancel_requested.load();
        request_well_log_cancel(input.phase, [] {});
        check(cancelled_flag_before == false &&
                  input.phase->cancel_requested.load() == true,
              "post-run cancel only sets the flag");
        check(!input.phase->parse_active, "parse_active cleared after run");
    }

    // (c) cancelling hint fires exactly once while a parse is active.
    {
        auto input = spec();
        input.resources[0].path = las;
        input.phase->parse_active = true;
        int hints = 0;
        request_well_log_cancel(input.phase, [&] { ++hints; });
        request_well_log_cancel(input.phase, [&] { ++hints; });
        check(hints == 1, "cancelling hint emitted once");
    }

    // (d) LATE-RESULT DISCARD regression: the resolve seam returns a valid
    // payload but the cancel flag was raised while it ran — the worker must
    // surface JobCancelled and the payload must never reach on_done
    // (well_log_load.cpp "late successful payload -> DISCARDED" path).
    {
        WellLogLoadInput input;
        input.ref.kind = "well_log";
        ResourceSlice res;
        res.id = "late";
        res.path = las;
        res.type = "well_log";
        res.format = "las";
        input.resources.push_back(res);
        // The flag must be set before run_well_log_load's return checkpoint
        // sees it: the resolve closure raises it mid-run, then succeeds.
        input.resolve_fn = [&input](const VizRefSlice&,
                                    const std::vector<ResourceSlice>&,
                                    const std::string&,
                                    const std::function<bool()>&) {
            input.phase->cancel_requested.store(true);
            VizPayloadSlice payload;
            payload.kind = "well_log";
            payload.well_log = WleDocumentPayload{};
            payload.well_names.push_back("late");
            return payload;
        };
        pwb::job::JobContext ctx{"viz-a-test", pwb::job::CancellationToken{}};
        bool late_discarded = false;
        try {
            const auto result = run_well_log_load(input, ctx);
            // Reaching here means the payload survived — failure.
            check(result.payload.kind != "well_log",
                  "late payload must not be returned");
        } catch (const pwb::job::JobCancelled&) {
            late_discarded = true;
        }
        check(late_discarded, "late successful payload discarded -> JobCancelled");
    }

    if (g_failures == 0) {
        std::printf("viz_a.wle_load: OK\n");
        return 0;
    }
    std::printf("viz_a.wle_load: %d failure(s)\n", g_failures);
    return 1;
}
