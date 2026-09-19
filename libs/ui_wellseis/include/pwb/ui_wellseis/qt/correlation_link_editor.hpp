#pragma once

// UI-09 — CorrelationLinkEditor Qt shell (correlation_link_editor.py).
// Modal editor over the working CorrelationDraftSlice:
//   LINKS table — add manual links (unique-label pickers), remove, edit
//     method/notes;
//   TOPS table — edit method/confidence/status/notes (depth and identity
//     stay owned by the canvas picks).
// Every mutation routes through the correlation.hpp draft ops — the
// dialog never constructs links or bumps the draft by hand. Tables are
// read-only QTableView + StringTableModel (V11 D2 ⑥ parity) with
// key-anchored selection across rebuilds.

#include <functional>
#include <string>
#include <utility>
#include <vector>

#include <QDialog>
#include <QString>
#include <QStringList>

#include <pwb/ui_wellseis/slices.hpp>

class QTableView;

namespace pwb::ui_wellseis::qt {

class StringTableModel;

// Link id authority lives in the session layer (Python add_manual_link
// allocates it) — injected; default generates "link:<n>" from the draft
// size for tests/shell use.
struct CorrelationEditorHooks {
    std::function<std::string(const CorrelationDraftSlice& draft)>
        new_link_id;
    // QInputDialog.getItem seam (tests pick programmatically; production
    // installs the real dialog).
    std::function<std::pair<QString, bool>(
        const QString& title, const QString& label,
        const QStringList& items, int current)>
        pick_item;
};

class CorrelationLinkEditor : public QDialog {
    Q_OBJECT
public:
    CorrelationLinkEditor(CorrelationDraftSlice& draft, QWidget* parent,
                          CorrelationEditorHooks hooks = {});

    // run_link_editor parity — generation delta drives the host's
    // on_changed.
    [[nodiscard]] int generation() const;

private:
    void rebuild_tables();
    std::string selected_link_id() const;
    std::string selected_top_id() const;
    void add_link();
    void remove_link();
    void edit_link();
    void edit_top();

    CorrelationDraftSlice& draft_;
    CorrelationEditorHooks hooks_;
    StringTableModel* link_model_ = nullptr;
    StringTableModel* top_model_ = nullptr;
    QTableView* link_table_ = nullptr;
    QTableView* top_table_ = nullptr;
    // Rebuilt id->top map per refresh (R3-M3: a worker can extend the
    // draft's tops through the nested event loop while this modal is up).
    std::vector<CorrelationTopSlice> tops_snapshot_;
};

// run_link_editor(parent, draft, on_changed) parity — modal exec + the
// generation-moved notification.
void run_link_editor(QWidget* parent, CorrelationDraftSlice& draft,
                     CorrelationEditorHooks hooks,
                     const std::function<void()>& on_changed);

}  // namespace pwb::ui_wellseis::qt
