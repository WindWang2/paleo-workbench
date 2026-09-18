#pragma once

// ThemeService — port of paleo_workbench/ui/theme.py ThemeManager: runtime
// owner of the current (theme, density) pair. Persists under the unified
// QSettings identity (PaleoWorkbench, Workstation) with the Python keys
// "ui/theme" / "ui/density", so the native app and a legacy Python install
// read the same store. Invalid persisted values coerce exactly like the
// Python manager (unknown -> light / comfortable).

#include <QObject>
#include <QSettings>
#include <QString>

#include <pwb/platform_services/theme_tokens.hpp>

class QWidget;

namespace pwb::platform_services {

class ThemeService : public QObject {
    Q_OBJECT
public:
    // Storage identity shared with the Python workstation (ui/theme.py).
    static const QString organization();
    static const QString application();
    static const QString theme_key();     // "ui/theme"
    static const QString density_key();   // "ui/density"

    explicit ThemeService(QObject* parent = nullptr);

    // Binds the persistence backend. Null (default) uses the production
    // (organization(), application()) store; tests bind a temp-file store
    // so the user config is never touched.
    void set_store(QSettings* store);
    QSettings* store() const { return store_; }

    ThemeMode theme() const { return theme_; }
    Density density() const { return density_; }

    // Exact-value setters; a value that already is current is a no-op (the
    // Python manager neither emits nor re-persists on unchanged values).
    // Changes emit theme_changed and persist.
    void set_theme(ThemeMode mode);
    void set_density(Density density);
    void toggle_density();  // compact <-> comfortable

    // Pure state restore (unknown/missing keep current). Emits nothing:
    // construction-time callers apply() explicitly once the widget tree is
    // complete — polishing half-built UI is not a side effect worth having.
    // Caller owns the QSettings (tests pass a temp-file store; production
    // passes the unified (organization(), application()) store).
    void load_persisted(QSettings& settings);

    // Renders the platform sheet for the current (theme, density).
    QString stylesheet() const;

    // Applies the current sheet to the shell window (window-level QSS
    // cascades to every child dock/menu/toolbar; theme switches re-render).
    void apply(QWidget& shell);

signals:
    // (theme, density) Python-vocabulary strings, emitted after every
    // CHANGED value (set_theme/set_density/toggle_density; no-change values
    // emit nothing, and load_persisted never emits) — the shell re-applies
    // its sheet and resyncs the checkable menu state on it.
    void theme_changed(const QString& theme, const QString& density);

private:
    void emit_and_persist();

    ThemeMode theme_ = ThemeMode::Light;
    Density density_ = Density::Comfortable;
    QSettings* store_ = nullptr;  // not owned when injected; owned never
};

}  // namespace pwb::platform_services
