// V14-THREE-STAGE-UX — Qt controller smoke (offscreen): seam-driven
// refresh/request flow, true-change-only signals, layout application with
// user overrides, missing-seam honesty. Manual signal counters instead of
// QtTest (the local Qt install may lack the Test module).

#include <map>
#include <optional>
#include <string>

#include <QApplication>
#include <QSettings>
#include <QTemporaryDir>

#include <pwb/ui_stageflow/qt/stage_flow_controller.hpp>

#include "ui_stageflow_test.hpp"

using namespace pwb::ui_stageflow;
using Controller = pwb::ui_stageflow::qt::StageFlowController;

namespace {

struct FakeAuthority {
    std::optional<std::string> stage;
    std::optional<std::string> horizon = "T2";
    int apply_stage_calls = 0;
    int apply_horizon_calls = 0;
    std::map<std::string, bool> last_visibility;
    int visibility_calls = 0;
};

Controller::Seams make_seams(FakeAuthority& auth) {
    Controller::Seams seams;
    seams.read_stage = [&auth] { return auth.stage; };
    seams.apply_stage = [&auth](const std::string& value) {
        auth.stage = value;
        ++auth.apply_stage_calls;
    };
    seams.read_horizon = [&auth] { return auth.horizon; };
    seams.apply_horizon = [&auth](const std::string& value) {
        auth.horizon = value;
        ++auth.apply_horizon_calls;
    };
    seams.apply_visibility = [&auth](const std::map<std::string, bool>& vis) {
        auth.last_visibility = vis;
        ++auth.visibility_calls;
    };
    seams.project_open = [] { return true; };
    seams.write_granted = [] { return true; };
    seams.readiness = [] { return StageReadinessKind::Ready; };
    return seams;
}

// One QSettings instance shared by every controller in this TU: the
// sink-under-test is the real QSettings binding (INI in a temp dir), and
// a single instance keeps the Qt settings cache coherent between
// controllers without relying on flush timing.
StagePreferenceSink make_memory_sink() {
    static QTemporaryDir dir;  // static: outlives all controllers in this TU
    static QSettings* settings = nullptr;
    if (settings == nullptr) {
        settings = new QSettings(dir.filePath("prefs.ini"),
                                 QSettings::IniFormat);
        settings->clear();
    }
    settings->sync();
    return pwb::ui_stageflow::qt::make_qsettings_preference_sink(*settings);
}

struct Counters {
    int changed = 0;
    int stage_applied = 0;
    int horizon_applied = 0;
};

void bind_counters(Controller& controller, Counters& counters) {
    QObject::connect(&controller, &Controller::snapshot_changed, [&] {
        ++counters.changed;
    });
    QObject::connect(&controller, &Controller::stage_applied,
                     [&](const QString&) { ++counters.stage_applied; });
    QObject::connect(&controller, &Controller::horizon_applied,
                     [&](const QString&) { ++counters.horizon_applied; });
}

}  // namespace

PWB_TEST(controller_refresh_and_signals) {
    FakeAuthority auth;
    auth.stage = kStage2Value;
    Controller controller(make_memory_sink());
    controller.set_seams(make_seams(auth));
    Counters counters;
    bind_counters(controller, counters);

    controller.refresh();
    CHECK(controller.snapshot().stage_value == kStage2Value);
    CHECK(controller.snapshot().stage_label.find("约束") != std::string::npos);
    CHECK(controller.snapshot().horizon.has_value());
    CHECK(*controller.snapshot().horizon == "T2");
    CHECK(counters.changed == 1);
    CHECK(counters.stage_applied == 1);
    CHECK(auth.visibility_calls == 1);
    // Stage-2 profile applied (factor surfaces visible).
    CHECK(auth.last_visibility.at("workstation.composite_input") == true);
    CHECK(auth.last_visibility.at("mapping.composer") == false);

    // Same-value refresh: no signal (true-change contract).
    controller.refresh();
    CHECK(counters.changed == 1);
    CHECK(counters.stage_applied == 1);
    CHECK(auth.visibility_calls == 1);
}

PWB_TEST(controller_request_stage_routes_through_authority) {
    FakeAuthority auth;
    auth.stage = kStage1Value;
    Controller controller(make_memory_sink());
    controller.set_seams(make_seams(auth));
    controller.refresh();
    Counters counters;
    bind_counters(controller, counters);

    controller.request_stage(kStage3Value);
    CHECK(auth.apply_stage_calls == 1);
    CHECK(controller.snapshot().stage_value == kStage3Value);
    CHECK(counters.stage_applied == 1);
    // Layout followed the new authority value.
    CHECK(auth.last_visibility.at("mapping.composer") == true);
    CHECK(auth.last_visibility.at("workstation.composite_input") == false);

    // Empty request is a no-op (never invents a stage).
    controller.request_stage("");
    CHECK(auth.apply_stage_calls == 1);
}

PWB_TEST(controller_request_horizon) {
    FakeAuthority auth;
    auth.stage = kStage1Value;
    Controller controller(make_memory_sink());
    controller.set_seams(make_seams(auth));
    controller.refresh();
    Counters counters;
    bind_counters(controller, counters);

    controller.request_horizon("T3");
    CHECK(auth.apply_horizon_calls == 1);
    CHECK(controller.snapshot().horizon.has_value());
    CHECK(*controller.snapshot().horizon == "T3");
    CHECK(counters.horizon_applied == 1);
}

PWB_TEST(controller_user_override_wins_and_persists) {
    {
        FakeAuthority auth;
        auth.stage = kStage2Value;
        Controller controller(make_memory_sink());
        controller.set_seams(make_seams(auth));
        controller.refresh();
        // User re-enables the seismic dock for stage 2.
        controller.set_panel_visible("workstation.seismic", true);
        CHECK(auth.last_visibility.at("workstation.seismic") == true);
        CHECK(auth.last_visibility.at("mapping.composer") == false);
    }
    {
        // A fresh controller (same QSettings identity) sees the override.
        FakeAuthority auth;
        auth.stage = kStage2Value;
        Controller controller(make_memory_sink());
        controller.set_seams(make_seams(auth));
        controller.refresh();
        CHECK(auth.last_visibility.at("workstation.seismic") == true);
        // Reset restores the profile default.
        controller.reset_stage_preferences();
        CHECK(auth.last_visibility.at("workstation.seismic") == false);
    }
}

PWB_TEST(controller_missing_seams_honest_noop) {
    Controller controller(make_memory_sink());
    // No seams at all: refresh yields an honest empty/unknown snapshot and
    // no crash; requests are no-ops.
    Counters counters;
    bind_counters(controller, counters);
    controller.refresh();
    CHECK(controller.snapshot().stage_value.empty());
    CHECK(controller.snapshot().readiness == StageReadinessKind::Unknown);
    CHECK(counters.changed == 1);
    controller.request_stage(kStage1Value);  // no apply seam -> nothing
    CHECK(controller.snapshot().stage_value.empty());
    controller.request_horizon("T1");
    CHECK(!controller.snapshot().horizon.has_value());
    controller.set_panel_visible("x", true);  // no visibility seam -> safe
    controller.reset_stage_preferences();
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    return ::pwb_test::run_all("ui_stageflow.qt_widgets_smoke");
}
