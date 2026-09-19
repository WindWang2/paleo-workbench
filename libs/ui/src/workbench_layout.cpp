#include <pwb/ui/workbench_layout.hpp>

#include <QMainWindow>

namespace pwb::ui {
namespace {
constexpr auto kWindowGeometryKey = "layout/window_geometry";
constexpr auto kWindowStateKey = "layout/window_state";
constexpr auto kStateVersionKey = "layout/state_version";
}  // namespace

WorkbenchLayout::WorkbenchLayout(QSettings* settings) : settings_(settings) {}

QSettings& WorkbenchLayout::settings() {
    if (settings_ == nullptr) {
        // Same identity the Python workbench used (B2 unification), so a
        // machine that ran the PySide6 product does not grow a second
        // layout store.
        static QSettings default_store(QStringLiteral("PaleoWorkbench"),
                                       QStringLiteral("WorkstationCpp"));
        settings_ = &default_store;
    }
    return *settings_;
}

void WorkbenchLayout::save(const QMainWindow& window) {
    QSettings& store = settings();
    store.setValue(kStateVersionKey, kLayoutStateVersion);
    store.setValue(kWindowGeometryKey, window.saveGeometry());
    store.setValue(kWindowStateKey, window.saveState());
    store.sync();
}

bool WorkbenchLayout::has_stored_layout() const {
    // const_cast only to reach the lazily-bound store; no mutation.
    auto* self = const_cast<WorkbenchLayout*>(this);
    const QVariant version = self->settings().value(kStateVersionKey);
    if (!version.isValid() || version.toInt() != kLayoutStateVersion) {
        return false;
    }
    const QVariant state = self->settings().value(kWindowStateKey);
    return state.isValid() && state.toByteArray().size() >= 4;
}

bool WorkbenchLayout::restore(QMainWindow& window) {
    QSettings& store = settings();
    const QVariant version = store.value(kStateVersionKey);
    if (!version.isValid()) return false;
    bool version_ok = false;
    const int parsed = version.toInt(&version_ok);
    if (!version_ok || parsed != kLayoutStateVersion) {
        // Unknown schema generation: drop, default layout stands.
        return false;
    }
    const QByteArray geometry =
        store.value(kWindowGeometryKey).toByteArray();
    const QByteArray state = store.value(kWindowStateKey).toByteArray();
    // Reject empty/truncated blobs before touching the window.
    if (state.size() < 4) return false;

    // Dock/toolbar state is the verdict; geometry applies only when the
    // state parsed (a corrupt blob must not half-apply: no window move on
    // a layout we are about to reject).
    if (!window.restoreState(state)) return false;
    if (!geometry.isEmpty()) {
        window.restoreGeometry(geometry);
    }
    return true;
}

void WorkbenchLayout::reset() {
    QSettings& store = settings();
    store.remove(kWindowGeometryKey);
    store.remove(kWindowStateKey);
    store.remove(kStateVersionKey);
    store.sync();
}

}  // namespace pwb::ui
