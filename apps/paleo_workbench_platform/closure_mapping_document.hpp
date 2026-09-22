// 08-line closure — mapping_document consumption adapter.
//
// Bridges the orphaned ui_pages_mapedit editing scene (a PaleoMapDocument
// -shaped domain::Json bound through mapping_document::document_io) to the
// product document flow:
//   * multi-document (期次/图件) bank over project.paleomap_documents
//     entries — the SAME Json model the project schema carries verbatim
//     (no second document model);
//   * guarded document switch (保存/放弃/取消 — Python mapping_page #532);
//   * save = topology gate (scene.validate_for_save) → scene export →
//     document_io::apply_features_to_document → view_state/edit_history
//     stash → optional project persist seam;
//   * discard = restore the last-saved copy of the active document;
//   * restore = rebind (features_from_document inside the scene) + the
//     saved view_state/CRS ride in the document (load parity).
//
// The Qt-free cores (document_io, scene command stack) stay authoritative;
// this adapter owns only orchestration the Python host did in
// mapping_page.py.

#pragma once

#include <QObject>
#include <QString>

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

class QWidget;

namespace pwb::ui_pages_mapedit {
class MapEditScene;
class MapEditView;
}  // namespace pwb::ui_pages_mapedit

namespace pwb::app::closure_mapping {

class MapDocumentBank : public QObject {
    Q_OBJECT
public:
    MapDocumentBank(ui_pages_mapedit::MapEditScene* scene,
                    ui_pages_mapedit::MapEditView* view,
                    QObject* parent = nullptr);

    // update_state parity: replace the document list and activate
    // `prefer_id` (falling back to the previous active id, then the first
    // document). When the active document is dirty and the incoming list
    // no longer contains it (or a different id is requested), the guard
    // dialog runs against `guard_parent`; cancelling keeps the current
    // binding and returns false.
    bool set_documents(std::vector<domain::Json> documents,
                       const std::string& prefer_id,
                       QWidget* guard_parent);

    // Project document consumer view — the bank's list mirrors
    // project.paleomap_documents entries (id / linked horizon fields are
    // preserved verbatim).
    const std::vector<domain::Json>& documents() const { return documents_; }
    domain::Json* active_document();
    std::string active_id() const;

    bool is_dirty() const;

    // Save path (Python save_draft parity): validate_for_save → export →
    // apply_features_to_document → view_state stash → persist seam.
    // On a topology gate failure this reports the issues and returns false
    // (never a silent drop).
    bool save_active(QWidget* parent);

    // Discard: drop scene edits and rebind the last-saved copy of the
    // active document (a pristine clone taken at bind time).
    void discard_active();

    // Explicit guarded switch to another document in the bank.
    bool switch_to(const std::string& id, QWidget* guard_parent);

    // Persist seam — the project-document write (12's global save routes
    // here through the installer). Unset ⇒ save still normalizes the
    // bound document in memory but reports false (nothing was persisted).
    void set_persist_fn(std::function<bool(std::string* error)> fn);

    // Diagnostics from the last save (document_io warnings).
    const std::vector<std::string>& last_warnings() const {
        return last_warnings_;
    }

    // M5-2 context groups: the editing scene (selection → ribbon context
    // group injection). Non-owning — owned by the mapping page.
    ui_pages_mapedit::MapEditScene* edit_scene() const { return scene_; }

signals:
    void active_changed(const QString& id);
    void document_saved(const QString& id);
    void dirty_changed(bool dirty);

private:
    void bind_active();
    std::optional<std::size_t> index_of(const std::string& id) const;

    ui_pages_mapedit::MapEditScene* scene_ = nullptr;
    ui_pages_mapedit::MapEditView* view_ = nullptr;

    std::vector<domain::Json> documents_;
    std::optional<std::size_t> active_;
    // Pristine last-saved copy of the active document (discard source).
    domain::Json saved_copy_ = domain::Json::object();
    // The scene binds this member — documents_ entries are copied into it
    // so re-entrancy on the caller's list can never dangle the binding.
    domain::Json bound_ = domain::Json::object();

    std::function<bool(std::string* error)> persist_fn_;
    std::vector<std::string> last_warnings_;
    bool guard_active_ = false;
};

}  // namespace pwb::app::closure_mapping
