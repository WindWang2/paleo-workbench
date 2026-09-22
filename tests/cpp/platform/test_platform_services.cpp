// platform.platform_services — CONV-PS acceptance: token/QSS parity against
// the frozen Python oracle, legacy QSettings migration, version-fenced
// window layout, recent-list semantics, diagnostics probe, Qt session
// policy, resource locator. Includes a negative self-check: the comparator
// must FAIL corrupted data (a passing oracle test proves nothing unless it
// can fail).

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>

#include <QAction>
#include <QApplication>
#include <QByteArray>
#include <QDir>
#include <QDockWidget>
#include <QFile>
#include <QMainWindow>
#include <QMap>
#include <QSettings>
#include <QTemporaryDir>

#include <qgsapplication.h>

#include <nlohmann/json.hpp>

#include <pwb/platform_services/diagnostics_report.hpp>
#include <pwb/platform_services/qt_session_policy.hpp>
#include <pwb/platform_services/resource_locator.hpp>
#include <pwb/platform_services/settings_service.hpp>
#include <pwb/platform_services/theme_service.hpp>
#include <pwb/platform_services/theme_tokens.hpp>
#include <pwb/qgis/qgis_runtime.hpp>

#include "test_framework.hpp"
// PWB-V14-DATA-LINEAGE: setenv/unsetenv are POSIX-only; MSVC equivalent
// through the CRT (process environment), same semantics for this test.
#if defined(_WIN32)
#include <stdlib.h>
inline int pwb_setenv(const char* name, const char* value, int overwrite) {
    char* existing = nullptr;
    std::size_t size = 0;
    if (!overwrite && _dupenv_s(&existing, &size, name) == 0 &&
        existing != nullptr) {
        free(existing);
        return 0;
    }
    return _putenv_s(name, value);
}
inline int pwb_unsetenv(const char* name) { return _putenv_s(name, ""); }
#else
#include <stdlib.h>
inline int pwb_setenv(const char* name, const char* value, int overwrite) {
    return ::setenv(name, value, overwrite);
}
inline int pwb_unsetenv(const char* name) { return ::unsetenv(name); }
#endif


namespace {

using namespace pwb::platform_services;

nlohmann::json load_fixture(const char* name) {
    const std::string path =
        std::string(PWB_TEST_SRC_DIR) + "/fixtures/platform_services/" + name;
    std::ifstream stream(path);
    if (!stream) {
        std::fprintf(stderr, "cannot open fixture %s\n", path.c_str());
        std::exit(2);
    }
    return nlohmann::json::parse(stream);
}

bool palette_matches(const std::map<std::string, std::string>& palette,
                     const nlohmann::json& expected) {
    if (palette.size() != expected.size()) return false;
    for (const auto& [key, value] : expected.items()) {
        const auto it = palette.find(key);
        if (it == palette.end() || it->second != value.get<std::string>()) {
            return false;
        }
    }
    return true;
}

void check_theme_tokens_parity() {
    const auto themes = load_fixture("theme_palettes.json");
    PWB_CHECK(palette_matches(palette_for(ThemeMode::Light),
                              themes.at("light")));
    PWB_CHECK(palette_matches(palette_for(ThemeMode::Dark),
                              themes.at("dark")));
    PWB_CHECK(palette_matches(palette_for(ThemeMode::HighContrast),
                              themes.at("high_contrast")));
    // Fallback + normalization contracts frozen from palette_for().
    PWB_CHECK(palette_matches(palette_for(ThemeMode::Light),
                              themes.at("fallback_unknown")));
    PWB_CHECK(palette_matches(palette_for(ThemeMode::HighContrast),
                              themes.at("normalized_dash")));

    // Negative self-check: a corrupted palette must not match.
    auto corrupted = themes.at("dark");
    corrupted["PRIMARY"] = "#deadbe";
    PWB_CHECK(!palette_matches(palette_for(ThemeMode::Dark), corrupted));
    auto truncated = themes.at("light");
    truncated.erase(truncated.begin());
    PWB_CHECK(!palette_matches(palette_for(ThemeMode::Light), truncated));

    // Density tables + unknown-density fallback.
    const auto densities = load_fixture("theme_density.json");
    const auto check_density = [&densities](Density density,
                                            const char* name) {
        const auto metrics = density_for(density);
        const auto& expected = densities.at(name);
        PWB_CHECK(metrics.padding_y == expected.at("padding_y").get<int>());
        PWB_CHECK(metrics.padding_x == expected.at("padding_x").get<int>());
        PWB_CHECK(metrics.btn_height == expected.at("btn_height").get<int>());
        PWB_CHECK(metrics.row_height == expected.at("row_height").get<int>());
        PWB_CHECK(metrics.toolbar_height ==
                  expected.at("toolbar_height").get<int>());
        PWB_CHECK(metrics.app_bar_height ==
                  expected.at("app_bar_height").get<int>());
        PWB_CHECK(metrics.rail_width == expected.at("rail_width").get<int>());
        PWB_CHECK(metrics.rail_item_size ==
                  expected.at("rail_item_size").get<int>());
        PWB_CHECK(metrics.font_delta == expected.at("font_delta").get<int>());
        PWB_CHECK(metrics.tab_padding == expected.at("tab_padding").get<std::string>());
        PWB_CHECK(metrics.menu_padding == expected.at("menu_padding").get<std::string>());
        PWB_CHECK(metrics.item_padding == expected.at("item_padding").get<std::string>());
        PWB_CHECK(metrics.combo_item_height ==
                  expected.at("combo_item_height").get<int>());
    };
    check_density(Density::Compact, "compact");
    check_density(Density::Comfortable, "comfortable");
    check_density(Density::Comfortable, "fallback_bogus");

    // Coercion: exact values parse; anything else falls back like Python.
    PWB_CHECK(theme_from_string("dark") == ThemeMode::Dark);
    PWB_CHECK(theme_from_string("high_contrast") == ThemeMode::HighContrast);
    PWB_CHECK(theme_from_string("light") == ThemeMode::Light);
    PWB_CHECK(theme_from_string("High-Contrast") == ThemeMode::Light);
    PWB_CHECK(theme_from_normalized("HIGH-CONTRAST") ==
              ThemeMode::HighContrast);
    PWB_CHECK(theme_from_normalized("High_Contrast") ==
              ThemeMode::HighContrast);
    PWB_CHECK(theme_from_normalized("high_contrast") ==
              ThemeMode::HighContrast);
    // Python palette_for lowercases and dash-normalizes but does NOT trim:
    // a padded value misses the key table and falls back to light.
    PWB_CHECK(theme_from_normalized("dark ") == ThemeMode::Light);
    PWB_CHECK(theme_from_normalized("midnight") == ThemeMode::Light);
    PWB_CHECK(density_from_string("compact") == Density::Compact);
    PWB_CHECK(density_from_string("ultra") == Density::Comfortable);

    // QSS: rendered from the palette, theme-differentiated, density-aware.
    const std::string light_qss = build_platform_qss(ThemeMode::Light,
                                                     Density::Comfortable);
    const std::string dark_qss = build_platform_qss(ThemeMode::Dark,
                                                    Density::Comfortable);
    PWB_CHECK(!light_qss.empty() && !dark_qss.empty());
    PWB_CHECK(light_qss != dark_qss);
    PWB_CHECK(light_qss.find("#0b5563") != std::string::npos);  // light PRIMARY
    PWB_CHECK(dark_qss.find("#2dd4bf") != std::string::npos);   // dark PRIMARY
    PWB_CHECK(light_qss.find("6px 24px 6px 12px") != std::string::npos);
    const std::string compact_qss = build_platform_qss(
        ThemeMode::Light, Density::Compact);
    PWB_CHECK(compact_qss.find("4px 18px 4px 8px") != std::string::npos);
    PWB_CHECK(compact_qss.find("6px 24px 6px 12px") == std::string::npos);

    const auto meta = load_fixture("app_meta.json");
    PWB_CHECK(app_version() == meta.at("app_version").get<std::string>());
}

void check_theme_service() {
    QTemporaryDir dir;
    const QString path = dir.path() + "/theme.ini";
    {
        QSettings store(path, QSettings::IniFormat);
        ThemeService theme;
        theme.set_store(&store);
        QStringList emissions;
        QObject::connect(&theme, &ThemeService::theme_changed,
                         [&emissions](const QString& theme_value,
                                      const QString& density_value) {
                             emissions << theme_value << density_value;
                         });
        theme.set_theme(ThemeMode::Dark);
        theme.set_density(Density::Compact);
        // First emission carries the new theme with the previous density;
        // the second carries both new values (ui/theme.py contract).
        PWB_CHECK(emissions.size() == 4);
        PWB_CHECK(emissions.at(0) == "dark" && emissions.at(1) == "comfortable");
        PWB_CHECK(emissions.at(2) == "dark" && emissions.at(3) == "compact");
        // No-change setters neither emit nor re-persist (Python manager
        // parity): repeated clicks must not re-polish the app.
        theme.set_theme(ThemeMode::Dark);
        theme.set_density(Density::Compact);
        PWB_CHECK(emissions.size() == 4);
        // Persistence landed in the bound store under the Python keys.
        PWB_CHECK(store.value("ui/theme").toString() == "dark");
        PWB_CHECK(store.value("ui/density").toString() == "compact");
    }
    {
        QSettings store(path, QSettings::IniFormat);
        ThemeService restored;
        restored.load_persisted(store);
        PWB_CHECK(restored.theme() == ThemeMode::Dark);
        PWB_CHECK(restored.density() == Density::Compact);
        PWB_CHECK(restored.stylesheet().contains("#2dd4bf"));  // apply is explicit
    }
    {
        // Corrupted values coerce exactly like the Python manager.
        QSettings store(path, QSettings::IniFormat);
        store.setValue("ui/theme", "midnight");
        store.setValue("ui/density", "ultra");
        store.sync();
        ThemeService coerced;
        coerced.load_persisted(store);
        PWB_CHECK(coerced.theme() == ThemeMode::Light);
        PWB_CHECK(coerced.density() == Density::Comfortable);
    }
    PWB_CHECK(ThemeService::organization() == "PaleoWorkbench");
    PWB_CHECK(ThemeService::application() == "Workstation");
}

void check_legacy_migration() {
    QTemporaryDir dir;
    const QString target_path = dir.path() + "/workstation.ini";
    const QString shell_path = dir.path() + "/workstation_v3.ini";
    const QString panels_path = dir.path() + "/legacy_panels.ini";
    // migrate_legacy_layout_settings opens the HISTORICAL stores by
    // (org, app-name) identity — point the default QSettings backend at the
    // temp dir so the test never touches the developer's real config.
    QSettings::setDefaultFormat(QSettings::IniFormat);
    QSettings::setPath(QSettings::IniFormat, QSettings::UserScope,
                       dir.path());

    // Seed the historical identities through their real (org, app) names;
    // the redirected default backend writes them under dir/.
    {
        QSettings shell("PaleoWorkbench", "WorkstationV3");
        shell.setValue("layout/windowState.v4",
                       QByteArray("v3-window-state-blob"));
        shell.setValue("layout/inspector_user_hidden", true);
        shell.sync();
        QSettings panels("PaleoWorkbench", "paleo-workbench");
        panels.setValue("panel_layout/mapping:layer_tree/floating", true);
        panels.setValue("panel_layout/mapping:layer_tree/geometry",
                        "10,20,300,400");
        panels.setValue("panel_layout/deep/nested/key", 7);
        panels.sync();
    }
    QSettings target("PaleoWorkbench", "Workstation");

    // Pre-existing target window state must survive the migration.
    target.setValue("layout/window_state", QByteArray("already-there"));

    const bool migrated =
        migrate_legacy_layout_settings(target);
    PWB_CHECK_MSG(migrated, "migration reported nothing moved");
    PWB_CHECK(target.value("layout/window_state").toByteArray()
              == QByteArray("already-there"));  // not overwritten
    PWB_CHECK(target.value("layout/state_version").toInt()
              == kLayoutStateVersion);
    PWB_CHECK(target.value("layout/inspector_user_hidden").toBool());
    PWB_CHECK(target.value(
        "panel_layout/mapping:layer_tree/floating").toBool());
    PWB_CHECK(target.value(
        "panel_layout/mapping:layer_tree/geometry").toString()
        == "10,20,300,400");
    PWB_CHECK(target.value("panel_layout/deep/nested/key").toInt() == 7);

    {
        QSettings shell("PaleoWorkbench", "WorkstationV3");
        PWB_CHECK(!shell.contains("layout/windowState.v4"));
        QSettings panels("PaleoWorkbench", "paleo-workbench");
        PWB_CHECK(!panels.contains("panel_layout/mapping:layer_tree/floating"));
    }

    // Idempotent: a second run moves nothing.
    PWB_CHECK(!migrate_legacy_layout_settings(target));

    // Partial stores: each legacy identity alone, plus missing inspector
    // flag — each must migrate independently and stay idempotent.
    {
        QSettings shell_only("PaleoWorkbench", "WorkstationV3");
        shell_only.setValue("layout/windowState.v4",
                            QByteArray("v3-only-blob"));
        shell_only.sync();
        QSettings fresh_target(dir.path() + "/t2.ini", QSettings::IniFormat);
        PWB_CHECK(migrate_legacy_layout_settings(fresh_target));
        PWB_CHECK(fresh_target.contains("layout/window_state"));
        PWB_CHECK(fresh_target.value("layout/state_version").toInt()
                  == kLayoutStateVersion);
        PWB_CHECK(
            !fresh_target.contains("layout/inspector_user_hidden"));
        QSettings panels("PaleoWorkbench", "paleo-workbench");
        PWB_CHECK(!panels.contains("panel_layout/mapping:layer_tree/floating")
                  || panels.allKeys().isEmpty());
        PWB_CHECK(!migrate_legacy_layout_settings(fresh_target));
    }
    {
        QSettings panels_only("PaleoWorkbench", "paleo-workbench");
        panels_only.setValue("panel_layout/preview/docked_sizes", "1,2,3");
        panels_only.sync();
        QSettings fresh_target(dir.path() + "/t3.ini", QSettings::IniFormat);
        PWB_CHECK(migrate_legacy_layout_settings(fresh_target));
        PWB_CHECK(fresh_target.value("panel_layout/preview/docked_sizes")
                      .toString() == "1,2,3");
        PWB_CHECK(!fresh_target.contains("layout/window_state"));
        PWB_CHECK(!migrate_legacy_layout_settings(fresh_target));
    }
}

void check_window_layout_fence() {
    QTemporaryDir dir;
    const QString path = dir.path() + "/layout.ini";

    {
        QMainWindow source;
        source.setObjectName("WorkstationFrame");
        auto* dock = new QDockWidget("图层", &source);
        dock->setObjectName("layer-tree-dock");
        source.addDockWidget(Qt::LeftDockWidgetArea, dock);
        source.resize(1111, 555);
        QSettings store(path, QSettings::IniFormat);
        // Invisible windows: save only with force (default-geometry rule).
        save_window_layout(store, source, /*force=*/true);
        PWB_CHECK(store.value("layout/state_version").toInt()
                  == kLayoutStateVersion);
        PWB_CHECK(!store.value("layout/window_state").toByteArray().isEmpty());
    }
    {
        QMainWindow restored;
        restored.setObjectName("WorkstationFrame");
        auto* dock = new QDockWidget("图层", &restored);
        dock->setObjectName("layer-tree-dock");
        restored.addDockWidget(Qt::RightDockWidgetArea, dock);
        QSettings store(path, QSettings::IniFormat);
        restore_window_layout(store, restored);
        PWB_CHECK(restored.dockWidgetArea(dock) == Qt::LeftDockWidgetArea);
    }
    {
        // Version fence: an unknown state version is discarded wholesale.
        QSettings store(path, QSettings::IniFormat);
        store.setValue("layout/state_version", 99);
        store.sync();
        QMainWindow fenced;
        auto* dock = new QDockWidget("图层", &fenced);
        dock->setObjectName("layer-tree-dock");
        fenced.addDockWidget(Qt::RightDockWidgetArea, dock);
        restore_window_layout(store, fenced);
        PWB_CHECK(fenced.dockWidgetArea(dock) == Qt::RightDockWidgetArea);
    }
    {
        // Missing version (fresh store): nothing to restore, no crash.
        QSettings fresh(dir.path() + "/empty.ini", QSettings::IniFormat);
        QMainWindow plain;
        auto* dock = new QDockWidget("图层", &plain);
        dock->setObjectName("layer-tree-dock");
        plain.addDockWidget(Qt::RightDockWidgetArea, dock);
        restore_window_layout(fresh, plain);
        PWB_CHECK(plain.dockWidgetArea(dock) == Qt::RightDockWidgetArea);
    }
}

void check_clamp_to_desktop() {
    const QRect primary(0, 0, 1920, 1040);   // available geometry
    const QRect secondary(1920, 0, 1920, 1080);
    const QList<QRect> dual = {primary, secondary};

    // Fully offscreen -> primary, +24px margin, size bounded to primary.
    const QRect gone(5000, 5000, 2000, 1000);
    const QRect clamped = clamp_to_desktop(gone, dual, primary);
    PWB_CHECK(clamped.x() == 24 && clamped.y() == 24);
    PWB_CHECK(clamped.width() == 1920 && clamped.height() == 1000);

    // Crossing the desktop's right edge: size preserved, position pulled
    // back so at least 60px stays visible. Qt QRect::right() is inclusive:
    // union right = 3839 -> clamp at 3839-60 = 3779.
    const QRect partial(3800, 100, 800, 600);
    const QRect pulled = clamp_to_desktop(partial, dual, primary);
    PWB_CHECK(pulled.width() == 800 && pulled.height() == 600);
    PWB_CHECK(pulled.x() == 3779);
    // Inside the union but left of the secondary screen: untouched — the
    // Python contract clamps against the desktop union, not per screen.
    const QRect spanning(1800, 100, 800, 600);
    PWB_CHECK(clamp_to_desktop(spanning, dual, primary) == spanning);

    // Fully inside: untouched.
    const QRect inside(100, 100, 400, 300);
    PWB_CHECK(clamp_to_desktop(inside, dual, primary) == inside);

    // Straddling the top edge: y pulled to 0 (>=60px visible rule keeps it
    // at max(y, top) = 0, then min(0, bottom-60) = 0).
    const QRect straddle(100, -200, 400, 300);
    const QList<QRect> single = {primary};
    PWB_CHECK(clamp_to_desktop(straddle, single, primary).y() == 0);
    // Fully above the screen: reset to primary +24px margin.
    const QRect above(100, -500, 400, 300);
    const QRect reset = clamp_to_desktop(above, single, primary);
    PWB_CHECK(reset.x() == 24 && reset.y() == 24);
    // No screens: unchanged (no monitor info -> no opinion).
    PWB_CHECK(clamp_to_desktop(inside, {}, primary) == inside);
}

void check_recent_lists() {
    QTemporaryDir dir;
    QSettings store(dir.path() + "/recent.ini", QSettings::IniFormat);

    // Commands: command_registry.py semantics — cap 8, dedupe to front.
    for (int i = 0; i < 12; ++i) {
        push_recent_command(store, QStringLiteral("cmd-%1").arg(i));
    }
    PWB_CHECK(load_recent_commands(store).size() == kRecentCommandsMax);
    // Load-side coercion: an over-cap stored list trims from the tail.
    QStringList overcap;
    for (int i = 0; i < 15; ++i) overcap << QStringLiteral("old-%1").arg(i);
    store.setValue("ui/recent_commands", overcap);
    const QStringList trimmed = load_recent_commands(store);
    PWB_CHECK(trimmed.size() == kRecentCommandsMax);
    PWB_CHECK(trimmed.first() == "old-0");
    PWB_CHECK(!trimmed.contains("old-14"));
    push_recent_command(store, "cmd-11");  // moves to front, no duplicate
    const QStringList commands = load_recent_commands(store);
    PWB_CHECK(commands.first() == "cmd-11");
    PWB_CHECK(commands.count("cmd-11") == 1);
    push_recent_command(store, "");  // empty id is a no-op
    PWB_CHECK(load_recent_commands(store).first() == "cmd-11");

    // Single stored string coerces to a one-element list.
    store.setValue("ui/recent_commands", "solo");
    PWB_CHECK(load_recent_commands(store) == QStringList{"solo"});

    // Projects: native MRU, cap 10, clear.
    for (int i = 0; i < 13; ++i) {
        push_recent_project(store, QStringLiteral("/proj-%1").arg(i));
    }
    PWB_CHECK(load_recent_projects(store).size() == kRecentProjectsMax);
    push_recent_project(store, "/proj-12");
    PWB_CHECK(load_recent_projects(store).first() == "/proj-12");
    // Mid-list project moves to the front without duplicating.
    const int before = load_recent_projects(store).size();
    push_recent_project(store, "/proj-5");
    const QStringList projects_moved = load_recent_projects(store);
    PWB_CHECK(projects_moved.first() == "/proj-5");
    PWB_CHECK(projects_moved.count("/proj-5") == 1);
    PWB_CHECK(projects_moved.size() == before);
    clear_recent_projects(store);
    PWB_CHECK(load_recent_projects(store).isEmpty());
    push_recent_project(store, "");  // empty push is a no-op
    PWB_CHECK(load_recent_projects(store).isEmpty());
}

void check_diagnostics() {
    PWB_CHECK(version_line().find(app_version()) != std::string::npos);
    PWB_CHECK(version_line().find("native") != std::string::npos);

    const RuntimeProbe probe = probe_qgis_runtime();
    if (!pwb::qgis::QgisRuntime::initialized()) {
        // Honest degraded report when QGIS was never acquired.
        PWB_CHECK(!probe.degraded_reasons.empty());
        return;
    }
    PWB_CHECK(probe.qgis_available);
    PWB_CHECK(!probe.qgis_version.empty());
    PWB_CHECK(probe.provider_count > 0);
    bool crs_ok = true;
    for (const auto& [authid, ok] : probe.crs_probes) crs_ok = crs_ok && ok;
    PWB_CHECK_MSG(crs_ok, "CRS round-trip probes failed");
    PWB_CHECK(probe.transform_available);

    const std::string text = environment_report_text();
    PWB_CHECK(text.find("=== Paleo Workbench Platform Diagnostics ===")
              != std::string::npos);
    PWB_CHECK(text.find(app_version()) != std::string::npos);
    PWB_CHECK(text.find("Providers:") != std::string::npos);
    PWB_CHECK(text.find("Locale:") != std::string::npos);
}

void check_session_policy() {
    // effective_qt_platform_hint read-only cases (env saved/restored).
    const char* keys[] = {"QT_QPA_PLATFORM", "WAYLAND_DISPLAY",
                          "XDG_SESSION_TYPE", "DISPLAY",
                          "PALEO_FORCE_XCB", "PALEO_ALLOW_NVIDIA_EGL",
                          "__EGL_VENDOR_LIBRARY_FILENAMES"};
    QMap<QString, QString> saved;
    for (const char* key : keys) {
        if (const char* v = std::getenv(key)) {
            saved.insert(key, v);
        }
        pwb_unsetenv(key);
    }
    auto restore_env = [saved, keys]() {
        for (const char* key : keys) pwb_unsetenv(key);
        for (auto it = saved.begin(); it != saved.end(); ++it) {
            pwb_setenv(it.key().toLatin1().constData(),
                   it.value().toLatin1().constData(), 1);
        }
    };

    pwb_setenv("QT_QPA_PLATFORM", "offscreen", 1);
    PWB_CHECK(configure_qt_platform_for_session() == "offscreen");
    PWB_CHECK(effective_qt_platform_hint() == "offscreen");

    // xcb on a Wayland session is cleared unless forced.
    pwb_setenv("QT_QPA_PLATFORM", "xcb", 1);
    pwb_setenv("WAYLAND_DISPLAY", "wayland-0", 1);
    PWB_CHECK(configure_qt_platform_for_session() == "");
    // The first configure already cleared the variable (one-time contract):
    // a forced run must re-set it before checking the opt-out.
    pwb_setenv("QT_QPA_PLATFORM", "xcb", 1);
    pwb_setenv("PALEO_FORCE_XCB", "1", 1);
    PWB_CHECK(configure_qt_platform_for_session() == "xcb");
    PWB_CHECK(effective_qt_platform_hint().find("forced")
              != std::string::npos);
    pwb_unsetenv("PALEO_FORCE_XCB");

    // Mesa EGL pin on Wayland with an injected existing candidate. The
    // pin's environment write is Q_OS_UNIX-only (a Wayland/NVIDIA EGL
    // mitigation); on Windows the function can never pin, so the pin
    // assertions would be vacuous failures (V14-THREE-STAGE-UX guard —
    // the test had never run on this platform).
    QTemporaryDir dir;
    const std::string vendor_json =
        (dir.filePath("50_mesa.json")).toStdString();
    { QFile f(QString::fromStdString(vendor_json)); f.open(QIODevice::WriteOnly); }
    pwb_unsetenv("__EGL_VENDOR_LIBRARY_FILENAMES");  // configure() may have pinned
    pwb_setenv("QT_QPA_PLATFORM", "offscreen", 1);
#if !defined(Q_OS_WIN)
    PWB_CHECK(pin_mesa_egl_on_wayland({vendor_json}) == vendor_json);
    PWB_CHECK(std::getenv("__EGL_VENDOR_LIBRARY_FILENAMES") != nullptr);
    // Already pinned -> untouched; opt-out -> untouched.
    PWB_CHECK(pin_mesa_egl_on_wayland({vendor_json + "x"}) == "");
    pwb_setenv("PALEO_ALLOW_NVIDIA_EGL", "1", 1);
    pwb_unsetenv("__EGL_VENDOR_LIBRARY_FILENAMES");
    PWB_CHECK(pin_mesa_egl_on_wayland({vendor_json}) == "");
    pwb_unsetenv("PALEO_ALLOW_NVIDIA_EGL");
    // No Wayland session -> untouched.
    pwb_unsetenv("WAYLAND_DISPLAY");
#endif
    PWB_CHECK(pin_mesa_egl_on_wayland({vendor_json}) == "");

    restore_env();
}

void check_resource_locator() {
    QTemporaryDir dir;
    const QString root = dir.path() + "/resources";
    QDir().mkpath(root + "/icons");
    { QFile f(root + "/icons/layers.svg"); f.open(QIODevice::WriteOnly); }

    qputenv("PALEO_RESOURCES_DIR", root.toUtf8());
    PWB_CHECK(resources_root() == QDir(root).canonicalPath());
    PWB_CHECK(icon_file("layers.svg").endsWith("layers.svg"));
    PWB_CHECK(icon_file("missing.svg").isEmpty());
    // Traversal outside the root is refused.
    PWB_CHECK(resource_file("../escape.txt").isEmpty());
    PWB_CHECK(resource_file("").isEmpty());

    qunsetenv("PALEO_RESOURCES_DIR");
    // Dev tree contract since the Python retirement: <source>/resources is
    // the native-owned resource root (facies JSONs + ui/assets/icons); the
    // retired package under legacy/python_reference is never probed.
    const bool resources_tree_exists =
        QDir(QStringLiteral(PWB_SOURCE_DIR) + "/resources").exists();
    PWB_CHECK(resources_tree_exists || resources_root().isEmpty());
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    check_theme_tokens_parity();
    check_theme_service();
    check_legacy_migration();
    check_window_layout_fence();
    check_clamp_to_desktop();
    check_recent_lists();
    check_diagnostics();
    check_session_policy();
    check_resource_locator();

    pwb::qgis::QgisRuntime::release();
    return pwb::test::report("platform.platform_services");
}
