// 08-line closure — MapDocumentBank implementation. See the header for the
// orchestration contract; document_io and the scene command stack own the
// data and edit substance.

#include "closure_mapping_document.hpp"

#include <QMessageBox>
#include <QPushButton>
#include <QVariantMap>

#include <pwb/mapping_document/document_io.hpp>
#include <pwb/ui_pages_mapedit/map_edit_scene.hpp>
#include <pwb/ui_pages_mapedit/map_edit_view.hpp>

namespace pwb::app::closure_mapping {
namespace {

using pwb::mapping_document::DocumentIoDiagnostics;
using pwb::mapping_document::FeatureIdGenerator;

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

std::string document_id(const domain::Json& doc) {
    if (!doc.is_object()) return {};
    const auto it = doc.find("id");
    return it != doc.end() && it->is_string() ? it->get<std::string>()
                                              : std::string{};
}

std::string document_title(const domain::Json& doc) {
    if (!doc.is_object()) return {};
    for (const char* key : {"name", "title"}) {
        const auto it = doc.find(key);
        if (it != doc.end() && it->is_string()) {
            return it->get<std::string>();
        }
    }
    return {};
}

}  // namespace

MapDocumentBank::MapDocumentBank(ui_pages_mapedit::MapEditScene* scene,
                                 ui_pages_mapedit::MapEditView* view,
                                 QObject* parent)
    : QObject(parent), scene_(scene), view_(view) {}

std::optional<std::size_t> MapDocumentBank::index_of(
    const std::string& id) const {
    for (std::size_t i = 0; i < documents_.size(); ++i) {
        if (document_id(documents_[i]) == id) return i;
    }
    return std::nullopt;
}

domain::Json* MapDocumentBank::active_document() {
    return active_.has_value() ? &documents_[*active_] : nullptr;
}

std::string MapDocumentBank::active_id() const {
    return active_.has_value() ? document_id(documents_[*active_])
                               : std::string{};
}

bool MapDocumentBank::is_dirty() const {
    return scene_ != nullptr && scene_->is_dirty();
}

void MapDocumentBank::bind_active() {
    if (scene_ == nullptr) return;
    bound_ = active_.has_value() ? documents_[*active_] : domain::Json::object();
    saved_copy_ = bound_;
    scene_->load_document(active_.has_value() ? &bound_ : nullptr);
    // Restore the saved viewport (Python _restore_view_state_from_document).
    if (view_ != nullptr && bound_.is_object()) {
        const auto vs = bound_.find("view_state");
        if (vs != bound_.end() && vs->is_object()) {
            QVariantMap state;
            if (const auto c = vs->find("center");
                c != vs->end() && c->is_array() && c->size() == 2) {
                // The view-state contract is {"center": [x, y], "scale": m11}
                // (map_edit_view read_view_state shape).
                state["center"] = QVariantList{(*c)[0].get<double>(),
                                               (*c)[1].get<double>()};
            }
            if (const auto s = vs->find("scale");
                s != vs->end() && s->is_number()) {
                state["scale"] = s->get<double>();
            }
            if (!state.empty()) {
                view_->apply_view_state(state, /*emit_change=*/false);
            }
        }
    }
    emit dirty_changed(false);
    emit active_changed(qstr(active_id()));
}

bool MapDocumentBank::set_documents(std::vector<domain::Json> documents,
                                    const std::string& prefer_id,
                                    QWidget* guard_parent) {
    // Capture the previous id BEFORE the move — list positions shift.
    const std::string previous_id = active_id();
    documents_ = std::move(documents);

    std::string prefer = prefer_id.empty() ? previous_id : prefer_id;
    auto next = prefer.empty() ? std::nullopt : index_of(prefer);
    if (!next.has_value() && !documents_.empty()) next = std::size_t{0};
    const std::string next_id =
        next.has_value() ? document_id(documents_[*next]) : std::string{};

    const bool switch_required =
        active_.has_value() && !documents_.empty() &&
        next_id != previous_id && is_dirty();
    if (switch_required && !guard_active_) {
        // Guarded cross-document switch inside set_documents — resolve via
        // the same 保存/放弃/取消 contract, then apply.
        guard_active_ = true;
        const bool applied = switch_to(next_id, guard_parent);
        guard_active_ = false;
        if (!applied) {
            // Cancelled (or save failed): keep the current binding. Re-map
            // the active index into the NEW list by id — the old index may
            // point at a different document now.
            if (const auto keep = index_of(previous_id); keep.has_value()) {
                active_ = keep;
            } else {
                // The dirty document was removed project-side; accept the
                // incoming list without rebinding the scene content.
                active_ = next;
            }
            emit active_changed(qstr(active_id()));
            return false;
        }
        return true;
    }
    active_ = next;
    bind_active();
    return true;
}

bool MapDocumentBank::switch_to(const std::string& id,
                                QWidget* guard_parent) {
    const auto next = index_of(id);
    if (!next.has_value()) return false;
    if (*next == active_) return true;

    if (is_dirty()) {
        // Dirty without a guard surface: refuse the switch (a silent
        // save-less switch would drop edits — never implicit).
        if (guard_parent == nullptr) {
            return false;
        }
        QMessageBox box(guard_parent);
        box.setWindowTitle(QStringLiteral("未保存的编图修改"));
        box.setText(QStringLiteral("当前图件有未保存的修改，切换前如何处理？"));
        auto* save_btn = box.addButton(QStringLiteral("保存"),
                                       QMessageBox::AcceptRole);
        auto* discard_btn = box.addButton(QStringLiteral("放弃修改"),
                                          QMessageBox::DestructiveRole);
        box.addButton(QStringLiteral("取消"), QMessageBox::RejectRole);
        box.exec();
        auto* clicked = box.clickedButton();
        if (clicked == save_btn) {
            if (!save_active(guard_parent)) {
                return false;  // save failed — stay on the document
            }
        } else if (clicked == discard_btn) {
            discard_active();
        } else {
            return false;  // user cancelled the switch
        }
    }

    active_ = next;
    bind_active();
    return true;
}

bool MapDocumentBank::save_active(QWidget* parent) {
    if (scene_ == nullptr || active_ == std::nullopt) return false;

    // Topology save gate (Python validate then rollback/abort on issues).
    const auto [all_clear, issues] = scene_->validate_for_save();
    if (!all_clear) {
        if (parent != nullptr) {
            const int count = issues.is_array()
                                  ? static_cast<int>(issues.size())
                                  : 0;
            QMessageBox::warning(
                parent, QStringLiteral("保存失败"),
                QStringLiteral("拓扑检查未通过（%1 个问题），已取消保存。")
                    .arg(count));
        }
        return false;
    }

    // Editor features → normalized legacy records (document_io pipeline).
    DocumentIoDiagnostics diagnostics;
    FeatureIdGenerator ids;
    domain::Json features = domain::Json::array();
    for (auto& record : scene_->export_features()) {
        features.push_back(std::move(record));
    }
    pwb::mapping_document::apply_features_to_document(bound_, features,
                                                      &diagnostics, ids);

    // Viewport rides with the document (Python view_state L1083).
    if (view_ != nullptr && bound_.is_object()) {
        const QVariantMap state = view_->view_state();
        if (!state.isEmpty()) {
            domain::Json vs = domain::Json::object();
            if (const auto it = state.find("center");
                it != state.end() && it->canConvert<QVariantList>()) {
                const auto center = it->toList();
                if (center.size() == 2) {
                    vs["center"] = domain::Json::array(
                        {center[0].toDouble(), center[1].toDouble()});
                }
            }
            if (const auto it = state.find("scale"); it != state.end()) {
                vs["scale"] = it->toDouble();
            }
            bound_["view_state"] = vs;
        }
    }

    // Publish the normalized document back into the bank list and persist.
    documents_[*active_] = bound_;

    bool persisted = true;
    std::string error;
    if (persist_fn_ != nullptr) {
        persisted = persist_fn_(&error);
    } else {
        persisted = false;
        error = "未接入工程持久化";
    }
    if (!persisted) {
        // Nothing was written — the in-memory document stays normalized,
        // the scene stays dirty so the next save retries.
        if (parent != nullptr) {
            QMessageBox::warning(parent, QStringLiteral("保存失败"),
                                 qstr(error));
        }
        return false;
    }

    // Latch the pristine copy only after a successful persist — a failed
    // save must keep the previous discard target (header contract).
    saved_copy_ = bound_;
    last_warnings_ = diagnostics.warnings;
    scene_->set_dirty(false);
    emit dirty_changed(false);
    emit document_saved(qstr(active_id()));
    return true;
}

void MapDocumentBank::discard_active() {
    // Rebind the pristine last-saved copy (drop every scene edit).
    if (active_ == std::nullopt) return;
    documents_[*active_] = saved_copy_;
    bind_active();
}

void MapDocumentBank::set_persist_fn(
    std::function<bool(std::string* error)> fn) {
    persist_fn_ = std::move(fn);
}

}  // namespace pwb::app::closure_mapping
