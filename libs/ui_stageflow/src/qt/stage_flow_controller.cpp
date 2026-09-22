#include "pwb/ui_stageflow/qt/stage_flow_controller.hpp"

namespace pwb::ui_stageflow::qt {

StageFlowController::StageFlowController(StagePreferenceSink preference_sink,
                                         QObject* parent)
    : QObject(parent), preferences_(std::move(preference_sink)) {
    qRegisterMetaType<StagePresentationSnapshot>(
        "pwb::ui_stageflow::StagePresentationSnapshot");
}

void StageFlowController::refresh() {
    StagePresentationSnapshot next;
    if (seams_.read_stage) {
        const auto stage = seams_.read_stage();
        next.stage_value = stage.value_or("");
    }
    next.stage_label = stage_display_label(next.stage_value);
    if (seams_.read_horizon) {
        next.horizon = seams_.read_horizon();
    }
    next.project_open = seams_.project_open ? seams_.project_open() : false;
    next.write_granted = seams_.write_granted ? seams_.write_granted() : false;
    next.running_tasks = seams_.running_tasks ? seams_.running_tasks() : 0;
    next.readiness =
        seams_.readiness ? seams_.readiness() : StageReadinessKind::Unknown;

    const bool stage_changed = next.stage_value != snapshot_.stage_value;
    const bool horizon_changed = next.horizon != snapshot_.horizon;
    const bool real_change = next != snapshot_;
    snapshot_ = next;
    if (stage_changed) {
        // Layout follows the authority — visibility matrices only, never
        // sizes (preset-switch contract).
        apply_stage_layout(snapshot_.stage_value);
    }
    if (!real_change) return;
    emit snapshot_changed();
    if (stage_changed) {
        emit stage_applied(QString::fromStdString(snapshot_.stage_value));
    }
    if (horizon_changed) {
        emit horizon_applied(
            snapshot_.horizon.has_value()
                ? QString::fromStdString(*snapshot_.horizon)
                : QString());
    }
}

void StageFlowController::request_stage(const std::string& stage_value) {
    if (stage_value.empty()) return;
    if (seams_.apply_stage) {
        seams_.apply_stage(stage_value);
    }
    refresh();
}

void StageFlowController::request_horizon(const std::string& horizon) {
    if (horizon.empty()) return;
    if (seams_.apply_horizon) {
        seams_.apply_horizon(horizon);
    }
    refresh();
}

void StageFlowController::set_panel_visible(const std::string& panel_key,
                                            bool visible) {
    if (panel_key.empty()) return;
    auto prefs = preferences_.load(snapshot_.stage_value);
    prefs.visibility_overrides[panel_key] = visible;
    preferences_.save(snapshot_.stage_value, prefs);
    apply_stage_layout(snapshot_.stage_value);
    emit snapshot_changed();
}

void StageFlowController::reset_stage_preferences() {
    preferences_.save(snapshot_.stage_value, StageUserPreferences{});
    apply_stage_layout(snapshot_.stage_value);
    emit snapshot_changed();
}

void StageFlowController::apply_stage_layout(const std::string& stage_value) {
    if (!seams_.apply_visibility) return;
    const auto profile = presentation_profile(stage_value);
    const auto prefs = preferences_.load(stage_value);
    seams_.apply_visibility(effective_visibility(profile, prefs));
    ++applied_visibility_count_;
}

void StageFlowController::apply_presentation(
    const std::string& presentation_key) {
    if (!seams_.apply_visibility) return;
    const auto profile = presentation_profile(presentation_key);
    const auto prefs = preferences_.load(presentation_key);
    seams_.apply_visibility(effective_visibility(profile, prefs));
    ++applied_visibility_count_;
}

StagePreferenceSink make_qsettings_preference_sink(QSettings& settings) {
    StagePreferenceSink sink;
    sink.load = [&settings](const std::string& key) -> std::optional<std::string> {
        const QString qkey = QString::fromStdString("stage_presentation/" + key);
        const QVariant value = settings.value(qkey);
        if (!value.isValid() || !value.canConvert<QString>()) return std::nullopt;
        return value.toString().toStdString();
    };
    sink.save = [&settings](const std::string& key, const std::string& value) {
        settings.setValue(QString::fromStdString("stage_presentation/" + key),
                          QString::fromStdString(value));
    };
    return sink;
}

}  // namespace pwb::ui_stageflow::qt
