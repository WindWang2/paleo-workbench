#include <pwb/mapping_document/native_edit_session.hpp>

#include "python_compat.hpp"

#include <algorithm>

namespace pwb::mapping_document {

namespace {

std::string str_or_empty(const Json& value) {
    return value.is_string() ? value.get<std::string>() : value.dump();
}

std::string str_or_empty(std::string value) { return value; }

// Python `str(x or "")`: a falsy id candidate (null/0/false/""/empty
// container) yields "", and truthy scalars go through Python str().
std::string json_to_id(const Json& value) {
    if (!detail::py_truthy(value)) return "";
    return detail::py_str(value);
}

}  // namespace

NativeEditSessionController::NativeEditSessionController()
    : session_set_ptr_(&owned_session_set_) {}

NativeEditSessionController::NativeEditSessionController(
    EditSessionSet& session_set)
    : session_set_ptr_(&session_set) {}

NativeEditSessionController::NativeEditSessionController(FeatureIdGenerator ids)
    : session_set_ptr_(&owned_session_set_), ids_(std::move(ids)) {}

bool NativeEditSessionController::bridge_supports(
    const NativeEditBridgeStack& stack) {
    // The four core operations are pure-virtual on the seam: an object that
    // is_a NativeEditBridgeStack implements them by construction. Whether the
    // ADAPTED bridge actually offers the native edit face stays the stack's
    // own answer (legacy adapters return false — D-27d-03).
    return stack.supports_native_editing();
}

bool NativeEditSessionController::is_open(const std::string& layer_id) const {
    return sessions_.find(layer_id) != sessions_.end();
}

std::vector<std::string> NativeEditSessionController::session_layer_ids() const {
    // Join order (the Python dict's insertion order), not id order.
    return session_order_;
}

NativeEditBridgeStack* NativeEditSessionController::stack_for(
    const std::string& layer_id) {
    auto it = sessions_.find(layer_id);
    return it == sessions_.end() ? nullptr : it->second.stack;
}

// -- lifecycle --------------------------------------------------------------

std::pair<bool, std::string> NativeEditSessionController::open(
    NativeEditBridgeStack& stack, ICommittedDeltaSink& layer,
    const EditGate& gate, std::uintptr_t canvas_address) {
    const std::string layer_id = layer.id();
    if (is_open(layer_id)) return {true, ""};
    if (gate) {
        auto [allowed, reason] = gate(layer_id);
        if (!allowed) {
            return {false, reason.empty() ? "门禁拒绝" : reason};
        }
    }
    if (!bridge_supports(stack)) {
        return {false, "当前 QGIS 桥不支持原生编辑（需重建桥扩展）"};
    }
    // Whole-set growth: with a session set already open, a gate-passing new
    // layer JOINS it (replacement would kick the existing layers out of the
    // suppression window while their host sessions stay alive — state fork).
    if (session_set_ptr_->is_open()) {
        const std::string& layer_crs = layer.crs();
        const std::string& effective_crs =
            layer_crs.empty() ? session_set_ptr_->frozen_crs() : layer_crs;
        if (!session_set_ptr_->active_layer_ids(&stack).empty() &&
            session_set_ptr_->frozen_crs() != effective_crs) {
            // Same-session layers need the same CRS; a mismatching layer
            // stays out of the session with an honest message.
            return {false,
                    "图层「" +
                        (layer.name().empty() ? layer_id : layer.name()) +
                        "」CRS 与编辑会话不一致——该图层不参与本次会话"};
        }
    }
    // Committed-callback direct wiring (same path the canvas_shim host uses;
    // an unavailable surface only means the host routes handle_committed
    // explicitly).
    try {
        stack.set_committed_callback(
            canvas_address,
            [this](const std::string& doc_id, const Json& delta) {
                handle_committed(doc_id, delta);
            });
    } catch (const std::exception&) {
        // "set_committed_callback unavailable" — debug-grade only.
    }
    std::string error;
    try {
        error = str_or_empty(Json(stack.start_mirror_layer_editing(layer_id)));
    } catch (const std::exception& exc) {
        return {false, std::string("镜像层进入编辑失败：") + exc.what()};
    }
    if (!error.empty()) {
        return {false, "镜像层进入编辑失败：" + error};
    }
    sessions_[layer_id] = Session{&stack, &layer, canvas_address};
    session_order_.push_back(layer_id);
    if (session_set_ptr_->is_open()) {
        session_set_ptr_->request_join({layer_id});  // gate passed → grow
    } else {
        // Suppression window opens: set = {active layer}.
        session_set_ptr_->open(layer_id, layer.crs(), &stack);
    }
    return {true, ""};
}

std::pair<bool, std::string> NativeEditSessionController::rollback(
    const std::string& layer_id) {
    auto it = sessions_.find(layer_id);
    if (it == sessions_.end()) {
        return {false, "该图层没有进行中的原生编辑会话"};
    }
    NativeEditBridgeStack* stack = it->second.stack;
    std::erase(session_order_, layer_id);
    sessions_.erase(it);
    std::string error;
    try {
        error = str_or_empty(Json(stack->roll_back_mirror_layer(layer_id)));
    } catch (const std::exception& exc) {
        return {false, std::string("回滚失败：") + exc.what()};
    }
    if (!error.empty()) {
        return {false, "回滚失败：" + error};
    }
    session_set_ptr_->discard(layer_id);
    gestures_.clear();
    pending_commits_.erase(layer_id);
    return {true, ""};
}

// -- committed deltas --------------------------------------------------------

void NativeEditSessionController::handle_committed(const std::string& doc_id,
                                                   const Json& delta_json) {
    Json delta;
    if (delta_json.is_object()) {
        delta = delta_json;
    } else if (delta_json.is_string()) {
        try {
            delta = Json::parse(delta_json.get<std::string>());
        } catch (const std::exception&) {
            warnings_.push_back("native commit delta unparsable for " + doc_id);
            return;
        }
    } else {
        warnings_.push_back("native commit delta unparsable for " + doc_id);
        return;
    }
    if (!delta.is_object()) {
        warnings_.push_back("native commit delta unparsable for " + doc_id);
        return;
    }
    pending_commits_[doc_id] = std::move(delta);
}

// -- read-back ---------------------------------------------------------------

std::vector<Json> NativeEditSessionController::readback_features(
    NativeEditBridgeStack& stack, const std::string& layer_id) const {
    Json payload;
    try {
        payload = stack.mirror_features_json(layer_id);
    } catch (const std::exception&) {
        return {};
    }
    if (payload.is_string()) {
        try {
            payload = Json::parse(payload.get<std::string>());
        } catch (const std::exception&) {
            return {};
        }
    }
    if (!payload.is_object()) {
        return {};
    }
    // Python: `if not payload or not payload.get("exists")` — truthiness of
    // an arbitrary JSON value (containers included), not a strict bool probe.
    const auto exists_it = payload.find("exists");
    if (exists_it == payload.end() || !detail::py_truthy(*exists_it)) {
        return {};
    }
    std::vector<Json> normalized;
    if (!payload.contains("features") || !payload["features"].is_array()) {
        return normalized;
    }
    for (const Json& feature : payload["features"]) {
        if (!feature.is_object()) continue;
        // Python `properties = feature.get("properties") or {}` +
        // `dict(properties)` — a truthy non-object properties would raise
        // TypeError inside the guarded call and yield [] wholesale.
        const auto props_it = feature.find("properties");
        Json properties = Json::object();
        if (props_it != feature.end() && !props_it->is_null()) {
            if (!props_it->is_object()) return {};
            properties = *props_it;
        }
        std::string feature_id;
        if (properties.contains("__pwb_fid")) {
            feature_id = json_to_id(properties["__pwb_fid"]);
        }
        if (feature_id.empty() && feature.contains("id")) {
            feature_id = json_to_id(feature["id"]);
        }
        // (json_to_id already yields "" for falsy candidates, so the `or`
        // fallthrough above matches Python `a or b or ""`.)
        if (feature_id.empty()) continue;
        Json entry = Json::object();
        entry["feature_id"] = feature_id;
        const auto geom_it = feature.find("geometry");
        // Python `feature.get("geometry") or {}` — empty containers falsy.
        entry["geometry"] =
            geom_it != feature.end() && detail::py_truthy(*geom_it)
                ? *geom_it
                : Json::object();
        entry["attributes"] = properties;
        normalized.push_back(std::move(entry));
    }
    return normalized;
}

// -- attribute writes ---------------------------------------------------------

bool NativeEditSessionController::supports_attribute_write(
    const NativeEditBridgeStack& stack) {
    return stack.has_attribute_write();
}

std::pair<bool, std::string> NativeEditSessionController::set_feature_attributes(
    const std::string& layer_id, const std::vector<std::string>& feature_ids,
    const Json& attributes) {
    auto it = sessions_.find(layer_id);
    if (it == sessions_.end()) {
        return {false, "该图层没有进行中的原生编辑会话"};
    }
    NativeEditBridgeStack* stack = it->second.stack;
    if (!supports_attribute_write(*stack)) {
        return {false, "当前 QGIS 桥不支持编辑期属性写入（需重建 qgis_render_bridge）"};
    }
    std::vector<std::string> ids;
    for (const std::string& fid : feature_ids) {
        if (!fid.empty()) ids.push_back(fid);
    }
    if (ids.empty()) {
        return {false, "没有要修改的要素"};
    }
    Json values = Json::object();
    if (attributes.is_object()) {
        for (auto it2 = attributes.begin(); it2 != attributes.end(); ++it2) {
            values[it2.key()] = it2.value();
        }
    }
    if (values.empty()) {
        return {false, "没有要写入的属性"};
    }
    std::string error;
    try {
        error = str_or_empty(Json(stack->set_mirror_feature_attributes(
            layer_id, Json(ids), values)));
    } catch (const std::exception& exc) {
        // Bridge-side exceptions are not swallowed: the reason surfaces.
        return {false, std::string("属性写入失败：") + exc.what()};
    }
    if (!error.empty()) return {false, error};
    return {true, ""};
}

std::optional<bool> NativeEditSessionController::pending_changes(
    const std::string& layer_id) {
    auto it = sessions_.find(layer_id);
    if (it == sessions_.end()) return false;
    try {
        return it->second.stack->mirror_layer_dirty(layer_id);
    } catch (const std::exception& exc) {
        // Python catches the probe failure and returns None (unknown —
        // never guessed); a throwing bridge surface must not escape.
        warnings_.push_back("mirror_layer_dirty unavailable: " + std::string(exc.what()));
        return std::nullopt;
    }
}

// -- topology gate ------------------------------------------------------------

std::vector<Json> NativeEditSessionController::topology_gate_issues(
    ICommitTopologyGate& topology) {
    // M4 checker gate; old bridges fall back to per-layer validate_records.
    if (!sessions_.empty()) {
        const std::string first_layer = session_order_.front();
        const Session& first = sessions_.at(first_layer);
        NativeEditBridgeStack& stack = *first.stack;
        const std::uintptr_t canvas = first.canvas;
        ICommitTopologyGate::RunResult run =
            topology.run_for_commit(stack, canvas, session_layer_ids());
        if (run.available) {
            for (const std::string& layer_id : session_order_) {
                const Session& session = sessions_.at(layer_id);
                std::size_t count = 0;
                for (const Json& issue : run.issues) {
                    if (json_to_id(issue.value("layer_id", Json())) == layer_id) {
                        ++count;
                    }
                }
                topology.record_validation(layer_id, count);
            }
            return run.issues;
        }
    }
    std::vector<Json> issues;
    for (const std::string& layer_id : session_order_) {
        const Session& session = sessions_.at(layer_id);
        std::vector<Json> records = readback_features(*session.stack, layer_id);
        std::vector<Json> layer_issues =
            topology.validate_records(layer_id, records);
        topology.record_validation(layer_id, layer_issues.size());
        issues.insert(issues.end(), layer_issues.begin(), layer_issues.end());
    }
    return issues;
}

// -- save: whole-set all-or-nothing -------------------------------------------

std::pair<bool, std::string> NativeEditSessionController::commit_all(
    const EditGate& gate, ICommitTopologyGate* topology,
    const GeologyGate& geology, const OnCommitted& on_committed) {
    if (sessions_.empty()) return {true, ""};
    // Commit gate 1: whole-set role-gate re-check (join order).
    for (const std::string& layer_id : session_order_) {
        const Session& session = sessions_.at(layer_id);
        if (gate) {
            auto [allowed, reason] = gate(layer_id);
            if (!allowed) {
                const std::string name =
                    session.layer->name().empty() ? layer_id : session.layer->name();
                return {false, "图层「" + name + "」" + reason + "（全部编辑未提交）"};
            }
        }
    }
    // Commit gate 2: zero topology errors across the set (M4 bridge checker
    // with ignore exemptions first; old bridges fall back to validate_records
    // — the read-back geometry is the edit-buffer fact).
    if (topology != nullptr && topology->enabled()) {
        std::vector<Json> issues = topology_gate_issues(*topology);
        if (!issues.empty()) {
            const std::size_t shown_count = std::min<std::size_t>(issues.size(), 3);
            std::string details;
            for (std::size_t i = 0; i < shown_count; ++i) {
                if (i > 0) details += "；";
                details += json_to_id(issues[i].value("feature_id", Json())) + "：" +
                           json_to_id(issues[i].value("message", Json()));
            }
            std::string more = issues.size() > 3
                                   ? "（另有 " +
                                         std::to_string(issues.size() - 3) +
                                         " 个问题）"
                                   : "";
            const std::string first_layer =
                json_to_id(issues[0].value("layer_id", Json()));
            auto it = sessions_.find(first_layer);
            const Session& session = it != sessions_.end()
                                         ? it->second
                                         : sessions_.at(session_order_.front());
            const std::string name = session.layer->name().empty()
                                         ? first_layer
                                         : session.layer->name();
            return {false,
                    "图层「" + name + "」" + std::to_string(issues.size()) +
                        " 个要素未通过拓扑检查：" + details + more +
                        "（全部编辑未提交）"};
        }
    }
    // Commit gate 2': geological invariant gate (error-level violations block
    // the whole set; warnings pass — the host reports them separately).
    if (geology) {
        std::map<std::string, std::vector<Json>> records;
        for (const std::string& layer_id : session_order_) {
            records[layer_id] =
                readback_features(*sessions_.at(layer_id).stack, layer_id);
        }
        std::vector<Json> violations = geology(records);
        std::vector<Json> errors;
        for (const Json& violation : violations) {
            // Python `getattr(v, "severity", "error") == "error"`: a MISSING
            // severity defaults to "error" (blocks); a present non-string
            // value is never equal to "error" (passes as warning).
            const auto sev = violation.find("severity");
            const bool is_error =
                sev == violation.end()
                    ? true
                    : (sev->is_string() &&
                       sev->get<std::string>() == "error");
            if (is_error) errors.push_back(violation);
        }
        if (!errors.empty()) {
            const Json& first = errors.front();
            std::string first_layer = json_to_id(first.value("layer_id", Json()));
            std::vector<std::string> names;
            for (const Json& violation : errors) {
                std::string vid = json_to_id(violation.value("layer_id", Json()));
                auto it = sessions_.find(vid);
                std::string name =
                    (it != sessions_.end() && !it->second.layer->name().empty())
                        ? it->second.layer->name()
                        : vid;
                if (std::find(names.begin(), names.end(), name) == names.end()) {
                    names.push_back(name);
                }
            }
            std::sort(names.begin(), names.end());
            std::string joined;
            for (std::size_t i = 0; i < names.size(); ++i) {
                if (i > 0) joined += "、";
                joined += names[i];
            }
            if (joined.empty()) joined = "图件";
            return {false,
                    "地质不变量校验未通过（" + joined + "）：" +
                        json_to_id(first.value("code", Json())) + "：" +
                        json_to_id(first.value("message", Json())) + "——共 " +
                        std::to_string(errors.size()) +
                        " 个 error 级违规（全部编辑未提交）"};
        }
    }
    // Snapshots (compensation input): capture each layer's mirror truth
    // before committing — only a multi-session set needs it (a single failed
    // session has no "already committed layer" to compensate).
    std::map<std::string, Json> snapshots;
    bool all_restorable = sessions_.size() >= 2;
    if (all_restorable) {
        for (const std::string& layer_id : session_order_) {
            if (!sessions_.at(layer_id).stack->has_restore_snapshot()) {
                all_restorable = false;
                break;
            }
        }
    }
    if (all_restorable) {
        for (const std::string& layer_id : session_order_) {
            try {
                snapshots[layer_id] =
                    sessions_.at(layer_id).stack->mirror_features_json(layer_id, 0);
            } catch (const std::exception&) {
                warnings_.push_back("snapshot capture failed: " + layer_id);
            }
        }
    }
    // Per-layer commit (session-set order = join order); failure →
    // remaining layers roll back + committed layers are compensated.
    std::vector<std::pair<std::string, Session>> ordered;
    ordered.reserve(session_order_.size());
    for (const std::string& layer_id : session_order_) {
        ordered.emplace_back(layer_id, sessions_.at(layer_id));
    }
    std::vector<std::pair<std::string, Session>> committed;
    std::string failure_layer;
    std::string failed_reason;
    for (const auto& [layer_id, session] : ordered) {
        std::string error;
        try {
            error = str_or_empty(Json(session.stack->commit_mirror_layer(layer_id)));
        } catch (const std::exception& exc) {
            error = exc.what();
        }
        if (!error.empty()) {
            // All-or-nothing + compensation: the failed layer X keeps its
            // session (QGIS commit failure leaves the buffer intact —
            // retryable); layers after X roll back; committed layers reopen
            // their sessions and restore from the snapshots (content-
            // equivalent), the restore macro stays on the undo stack (the
            // escape hatch). The suppression window converges onto the
            // failed layer (commit retryable).
            const std::string name = session.layer->name().empty()
                                         ? layer_id
                                         : session.layer->name();
            failed_reason = "图层「" + name + "」提交失败：" + error +
                            "（其后图层已回滚，已提交层已补偿恢复）";
            failure_layer = layer_id;
            for (const std::string& remaining_id : session_order_) {
                const bool already_committed =
                    std::any_of(committed.begin(), committed.end(),
                                [&remaining_id](const auto& done) {
                                    return done.first == remaining_id;
                                });
                if (already_committed || remaining_id == layer_id) continue;
                try {
                    sessions_.at(remaining_id)
                        .stack->roll_back_mirror_layer(remaining_id);
                } catch (const std::exception&) {
                    warnings_.push_back("post-failure rollback failed: " +
                                        remaining_id);
                }
            }
            break;
        }
        committed.emplace_back(layer_id, session);
        // Python applies each committed layer's delta and fires the ledger
        // hook inline in the commit loop — a later failure in the set does
        // not un-apply the earlier layers' write-backs.
        auto pending = pending_commits_.find(layer_id);
        if (pending != pending_commits_.end()) {
            session.layer->apply_committed_delta(
                pending->second, "native-" + layer_id, "native",
                gestures_.audit_records());
            pending_commits_.erase(pending);
        }
        if (on_committed) on_committed(*session.layer);
    }
    if (!failure_layer.empty()) {
        std::vector<std::string> compensated =
            compensate_committed(committed, snapshots);
        for (const auto& [done_id, done] : committed) {
            const bool is_compensated =
                std::find(compensated.begin(), compensated.end(), done_id) !=
                compensated.end();
            if (is_compensated) continue;  // keeps its session (undoable macro)
            std::erase(session_order_, done_id);
            sessions_.erase(done_id);
            session_set_ptr_->discard(done_id);
        }
        std::vector<std::string> rolled;
        for (const std::string& rolled_id : session_order_) {
            if (rolled_id != failure_layer) rolled.push_back(rolled_id);
        }
        for (const std::string& rolled_id : rolled) {
            const bool is_compensated =
                std::find(compensated.begin(), compensated.end(), rolled_id) !=
                compensated.end();
            if (is_compensated) continue;
            std::erase(session_order_, rolled_id);
            sessions_.erase(rolled_id);
            session_set_ptr_->discard(rolled_id);
        }
        return {false, failed_reason};
    }
    for (const auto& [layer_id, session] : committed) {
        (void)session;
        std::erase(session_order_, layer_id);
        sessions_.erase(layer_id);
    }
    session_set_ptr_->close();
    gestures_.clear();
    return {true, ""};
}

std::vector<std::string> NativeEditSessionController::compensate_committed(
    const std::vector<std::pair<std::string, Session>>& committed,
    const std::map<std::string, Json>& snapshots) {
    // Committed-layer compensation (D9): reopen + one restore macro +
    // gesture registration. Returns the ids successfully compensated;
    // failures roll the session back best-effort and log (never throws —
    // the compensation runs ON a failure path and must not open a new one).
    std::vector<std::string> compensated;
    for (const auto& [done_id, session] : committed) {
        auto snapshot = snapshots.find(done_id);
        NativeEditBridgeStack* stack = session.stack;
        if (snapshot == snapshots.end() || !stack->has_restore_snapshot()) {
            continue;
        }
        std::string reopen_error;
        try {
            reopen_error = str_or_empty(Json(stack->start_mirror_layer_editing(done_id)));
        } catch (const std::exception& exc) {
            reopen_error = exc.what();
        }
        if (!reopen_error.empty()) {
            warnings_.push_back("compensation reopen failed: " + done_id + ": " +
                                reopen_error);
            continue;
        }
        std::string restore_error;
        try {
            restore_error = str_or_empty(
                Json(stack->restore_mirror_snapshot(done_id, snapshot->second)));
        } catch (const std::exception& exc) {
            restore_error = exc.what();
        }
        if (!restore_error.empty()) {
            warnings_.push_back("compensation restore failed: " + done_id + ": " +
                                restore_error);
            try {
                stack->roll_back_mirror_layer(done_id);
            } catch (const std::exception&) {
            }
            continue;
        }
        compensations_.push_back(done_id);
        gestures_.finish(ids_.new_id("gesture"), "撤销复合提交", {done_id});
        compensated.push_back(done_id);
    }
    return compensated;
}

// -- gestures ------------------------------------------------------------------

bool NativeEditSessionController::undo_gesture() {
    const std::vector<std::string> plan = gestures_.undo_plan();
    const std::string gesture_id = gestures_.current_gesture_id();
    if (plan.empty()) return false;
    bool ok = true;
    for (const std::string& layer_id : plan) {
        auto it = sessions_.find(layer_id);
        if (it == sessions_.end()) continue;
        try {
            it->second.stack->undo_mirror_edit(layer_id);
        } catch (const std::exception& exc) {
            warnings_.push_back("gesture undo failed: " + layer_id + ": " +
                                exc.what());
            ok = false;
        }
    }
    if (!gesture_id.empty() && ok) gestures_.mark_undone(gesture_id);
    return ok;
}

bool NativeEditSessionController::redo_gesture() {
    const std::vector<std::string> plan = gestures_.redo_plan();
    const std::string gesture_id = gestures_.current_gesture_id();
    if (plan.empty()) return false;
    bool ok = true;
    for (const std::string& layer_id : plan) {
        auto it = sessions_.find(layer_id);
        if (it == sessions_.end()) continue;
        try {
            it->second.stack->redo_mirror_edit(layer_id);
        } catch (const std::exception& exc) {
            warnings_.push_back("gesture redo failed: " + layer_id + ": " +
                                exc.what());
            ok = false;
        }
    }
    if (!gesture_id.empty() && ok) gestures_.mark_redone(gesture_id);
    return ok;
}

}  // namespace pwb::mapping_document
