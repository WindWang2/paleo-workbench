// V14-THREE-STAGE-UX — ui_stageflow core tests (Qt-free):
// stage layout profiles, preference codec round-trip + version fence,
// effective visibility merge, surface state vocabulary.

#include <map>
#include <optional>
#include <string>

#include <pwb/ui_stageflow/stage_presentation.hpp>
#include <pwb/ui_stageflow/surface_state.hpp>

#include "ui_stageflow_test.hpp"

using namespace pwb::ui_stageflow;

// ---------------------------------------------------------------- profiles

PWB_TEST(stage_layout_profile_matrix) {
    const auto s1 = stage_layout_profile(kStage1Value);
    CHECK(s1.stage_value == kStage1Value);
    CHECK(s1.lower_pane_mode == kLowerPaneSeismicWell);
    // M3: the seismic/well surfaces live in the science-host bottom
    // two-pane — the legacy placeholder docks stay managed-but-hidden.
    CHECK(s1.visibility.at("workstation.seismic") == false);
    CHECK(s1.visibility.at("workstation.well") == false);
    CHECK(s1.visibility.at("workstation.composite_input") == false);
    CHECK(s1.visibility.at("workstation.composite_linked") == false);
    CHECK(s1.visibility.at("workstation.facies_palette") == true);
    CHECK(s1.visibility.at("mapping.composer") == false);
    CHECK(s1.visibility.at("mapping.bottom") == false);
    CHECK(s1.visibility.at("window.constraint_panel") == false);

    const auto s2 = stage_layout_profile(kStage2Value);
    CHECK(s2.lower_pane_mode == kLowerPaneCrossWell);
    CHECK(s2.visibility.at("workstation.composite_input") == true);
    CHECK(s2.visibility.at("workstation.composite_linked") == true);
    CHECK(s2.visibility.at("workstation.seismic") == false);
    CHECK(s2.visibility.at("mapping.reference") == true);
    CHECK(s2.visibility.at("mapping.bottom") == true);
    CHECK(s2.visibility.at("mapping.chrome") == true);
    CHECK(s2.visibility.at("window.constraint_panel") == true);
    CHECK(s2.visibility.at("window.factor_stats") == true);
    CHECK(s2.visibility.at("mapping.composer") == false);

    const auto s3 = stage_layout_profile(kStage3Value);
    CHECK(s3.lower_pane_mode == kLowerPaneFactors);
    CHECK(s3.visibility.at("mapping.composer") == true);
    CHECK(s3.visibility.at("workstation.composite_input") == false);
    CHECK(s3.visibility.at("window.constraint_panel") == false);
    CHECK(s3.visibility.at("mapping.bottom") == true);

    // The three profiles manage the SAME key set (matrix shape is stable —
    // an app applying them never sees a dock key appear/vanish per stage).
    const auto keys1 = profile_managed_keys();
    for (const std::string value : {kStage1Value, kStage2Value, kStage3Value}) {
        const auto profile = stage_layout_profile(value);
        CHECK(profile.visibility.size() == keys1.size());
    }

    // User-owned docks are never managed by any profile: a stage switch
    // must never yank navigation/diagnostics away from the user.
    for (const std::string value : {kStage1Value, kStage2Value, kStage3Value}) {
        const auto profile = stage_layout_profile(value);
        CHECK(profile.visibility.count("workstation.nav") == 0);
        CHECK(profile.visibility.count("workstation.hub") == 0);
        CHECK(profile.visibility.count("workstation.tasks") == 0);
        CHECK(profile.visibility.count("workstation.agent") == 0);
        CHECK(profile.visibility.count("workstation.inspector") == 0);
        CHECK(profile.visibility.count("workstation.logs") == 0);
        CHECK(profile.visibility.count("workstation.console") == 0);
        CHECK(profile.visibility.count("workstation.mapping_stage") == 0);
        CHECK(profile.visibility.count("workstation.composite_layer") == 0);
    }
}

PWB_TEST(stage_layout_profile_lenient_fallback) {
    // Unknown/empty stage -> lenient stage-1 behavior, never an invention.
    const auto unknown = stage_layout_profile("stage_four");
    const auto empty = stage_layout_profile("");
    CHECK(unknown.stage_value == kStage1Value);
    CHECK(empty.stage_value == kStage1Value);
    // Known alias tolerance (stage_from_value vocabulary).
    CHECK(stage_layout_profile("phase2").stage_value == kStage2Value);
    CHECK(stage_layout_profile("智能预测").stage_value == kStage1Value);
}

PWB_TEST(stage_display_labels) {
    CHECK(stage_display_label(kStage1Value).find("智能预测") != std::string::npos);
    CHECK(stage_display_label(kStage2Value).find("约束") != std::string::npos);
    CHECK(stage_display_label(kStage3Value).find("综合") != std::string::npos);
    // Honest unknown: raw value comes back; empty maps to an honest label.
    CHECK(stage_display_label("stage_x") == "stage_x");
    CHECK(!stage_display_label("").empty());
}

// ---------------------------------------------------------------- codec

PWB_TEST(preference_codec_roundtrip) {
    StageUserPreferences prefs;
    prefs.visibility_overrides["workstation.seismic"] = false;
    prefs.visibility_overrides["mapping.composer"] = true;
    const auto blob = serialize_stage_preferences(prefs);
    const auto back = parse_stage_preferences(blob);
    CHECK(back == prefs);

    // Corrupt entries are skipped, valid ones survive (honest partial load).
    const auto partial = parse_stage_preferences(
        "workstation.well=1,bad,noeq=,=1,mapping.bottom=0");
    CHECK(partial.visibility_overrides.size() == 2);
    CHECK(partial.visibility_overrides.at("workstation.well") == true);
    CHECK(partial.visibility_overrides.at("mapping.bottom") == false);

    // Empty round-trip.
    CHECK(serialize_stage_preferences({}).empty());
    CHECK(parse_stage_preferences("").visibility_overrides.empty());
}

PWB_TEST(preference_store_fence) {
    std::map<std::string, std::string> kv;
    StagePreferenceSink sink;
    sink.load = [&kv](const std::string& key) -> std::optional<std::string> {
        const auto it = kv.find(key);
        if (it == kv.end()) return std::nullopt;
        return it->second;
    };
    sink.save = [&kv](const std::string& key, const std::string& value) {
        kv[key] = value;
    };

    StagePreferenceStore store(sink);
    // No version fence -> defaults (honest unknown), no crash.
    CHECK(store.load(kStage2Value).visibility_overrides.empty());

    StageUserPreferences prefs;
    prefs.visibility_overrides["mapping.bottom"] = false;
    store.save(kStage2Value, prefs);  // writes the fence
    CHECK(kv.count("version") == 1);
    CHECK(store.load(kStage2Value) == prefs);
    CHECK(store.load(kStage1Value).visibility_overrides.empty());

    // Fence mismatch -> defaults (restore parity: exact version only).
    kv["version"] = "999";
    CHECK(store.load(kStage2Value).visibility_overrides.empty());

    // Null sink: load/save are safe no-ops.
    StagePreferenceStore null_store(StagePreferenceSink{});
    CHECK(null_store.load(kStage1Value).visibility_overrides.empty());
    null_store.save(kStage1Value, prefs);
}

PWB_TEST(effective_visibility_merge) {
    const auto profile = stage_layout_profile(kStage2Value);
    StageUserPreferences prefs;
    prefs.visibility_overrides["workstation.seismic"] = true;  // user re-enables
    const auto merged = effective_visibility(profile, prefs);
    CHECK(merged.at("workstation.seismic") == true);  // override wins
    CHECK(merged.at("mapping.composer") == false);    // profile default
    CHECK(merged.at("mapping.bottom") == true);
}

// ---------------------------------------------------------------- surfaces

PWB_TEST(surface_state_vocabulary) {
    // Every kind has non-empty title + hint (dual-signal contract) and a
    // state-language token key.
    const std::vector<SurfaceKind> kinds = {
        SurfaceKind::Ready,     SurfaceKind::Loading,     SurfaceKind::Busy,
        SurfaceKind::Queued,    SurfaceKind::Cancelled,   SurfaceKind::Stale,
        SurfaceKind::Degraded,  SurfaceKind::MissingSource,
        SurfaceKind::Unsupported, SurfaceKind::Error,     SurfaceKind::NoProject,
        SurfaceKind::NoLayer,   SurfaceKind::NoSelection, SurfaceKind::Empty};
    for (const SurfaceKind kind : kinds) {
        const auto state = surface_state_for(kind);
        CHECK_MSG(!state.title.empty(), "surface title empty");
        CHECK_MSG(!state.hint.empty(), "surface hint empty");
        const auto token = surface_token_key(kind);
        CHECK(!token.category.empty());
        CHECK(!token.value.empty());
    }
    // Retry only for actionable-transient kinds.
    CHECK(!surface_state_for(SurfaceKind::Error).retry_action_id.empty());
    CHECK(!surface_state_for(SurfaceKind::Stale).retry_action_id.empty());
    CHECK(!surface_state_for(SurfaceKind::MissingSource).retry_action_id.empty());
    CHECK(surface_state_for(SurfaceKind::Busy).retry_action_id.empty());
    CHECK(surface_state_for(SurfaceKind::NoProject).retry_action_id.empty());
    CHECK(surface_state_for(SurfaceKind::Ready).retry_action_id.empty());
}

PWB_TEST(surface_task_derivation) {
    // Precedence: fail > cancelled > busy > queued; subject lands in title.
    auto failed = surface_for_task(false, false, false, true, "boom", "因子图");
    CHECK(failed.kind == SurfaceKind::Error);
    CHECK(failed.title.find("因子图") != std::string::npos);
    CHECK(failed.hint == "boom");
    auto cancelled = surface_for_task(false, false, true, false, "", "等值线");
    CHECK(cancelled.kind == SurfaceKind::Cancelled);
    // running + cancelled -> cancelled is the honest "user asked to stop".
    auto busy = surface_for_task(true, false, true, false, "", "x");
    CHECK(busy.kind == SurfaceKind::Cancelled);
    auto queued = surface_for_task(false, true, false, false, "", "x");
    CHECK(queued.kind == SurfaceKind::Queued);
    auto ok = surface_for_task(false, false, false, false, "", "x");
    CHECK(ok.kind == SurfaceKind::Ready);
}

PWB_TEST(surface_factor_derivation) {
    auto computing = surface_for_factor(true, false, false, false, "厚度");
    CHECK(computing.kind == SurfaceKind::Busy);
    CHECK(computing.title.find("厚度") != std::string::npos);
    CHECK(computing.hint.find("主地图") != std::string::npos);
    auto stale = surface_for_factor(false, true, false, false, "厚度");
    CHECK(stale.kind == SurfaceKind::Stale);
    CHECK(!stale.retry_action_id.empty());
    CHECK(stale.hint.find("综合编图") != std::string::npos);
    auto missing = surface_for_factor(false, false, true, false, "厚度");
    CHECK(missing.kind == SurfaceKind::MissingSource);
    // Fail-closed: failed beats computing.
    auto failed_factor = surface_for_factor(true, false, false, true, "厚度");
    CHECK(failed_factor.kind == SurfaceKind::Error);
    auto ok = surface_for_factor(false, false, false, false, "厚度");
    CHECK(ok.kind == SurfaceKind::Ready);
}

int main() { return ::pwb_test::run_all("ui_stageflow.core"); }
