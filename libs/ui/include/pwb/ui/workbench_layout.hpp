#pragma once

// CONV-27 — workbench layout persistence. Qt window layout (dock geometry,
// toolbars) is persisted separately from business state (QGIS project /
// working copies / catalog): the only bridge is the QSettings key
// namespace, never the document.
//
// Safe-restore contract (fixes the bad-layout-kills-startup class):
//   * state is guarded by a version key; unknown/missing version -> the
//     default layout, never a best-effort restore of foreign bytes;
//   * QMainWindow::restoreState's own verdict is honored: a state blob
//     that fails to parse discards cleanly instead of half-applying;
//   * restore of a null/short blob is rejected before touching the window.

#include <QByteArray>
#include <QString>
#include <QSettings>

class QMainWindow;

namespace pwb::ui {

class WorkbenchLayout {
public:
    // Version of the layout state schema. Unrecognized (newer/older)
    // versions are dropped and the default layout applies.
    static constexpr int kLayoutStateVersion = 1;

    explicit WorkbenchLayout(QSettings* settings = nullptr);

    // Saves geometry + dock/toolbar state under the version guard.
    void save(const QMainWindow& window);
    // Restores both. Returns true when the stored state existed, matched
    // the known version, and restoreState/restoreGeometry accepted it.
    // Any failure leaves the window on its default layout (no partial
    // application — a failed restoreState is re-run against an empty
    // state by clearing first).
    bool restore(QMainWindow& window);
    // Drops the persisted layout (menu action "重置布局"); the next save
    // starts a fresh generation.
    void reset();
    // True when a same-version layout is stored.
    bool has_stored_layout() const;

private:
    QSettings& settings();
    QSettings* settings_ = nullptr;   // lazily bound default store
};

}  // namespace pwb::ui
