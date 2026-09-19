// diag_main.cpp — opt-in install/diagnostic helper for paleo-workbench.
//
// Built ONLY when Pwb::Ui or Pwb::Application exists (see
// apps/paleo_workbench_platform/CMakeLists.txt). It prints one key=value per
// line describing the install tree it expects, then exits 0. It never opens a
// GUI, so it can run headless in a package smoke test.
//
// Qt is optional at compile time: when Pwb::Ui/Application links Qt, the
// PWB_HAS_QT compile definition is set and QT_VERSION_STR is reported;
// otherwise "qt=unavailable" is printed and the file still compiles.

#include <cstdio>

#ifdef PWB_HAS_QT
#include <QtCore/qglobal.h>
#endif

#ifndef PWB_VERSION
#define PWB_VERSION "0.0.0"
#endif

int main()
{
    std::printf("pwb-diagnose=1\n");
    std::printf("version=%s\n", PWB_VERSION);
#ifdef PWB_COMMIT
    std::printf("commit=%s\n", PWB_COMMIT);
#else
    std::printf("commit=unknown\n");
#endif

#ifdef PWB_HAS_QT
    std::printf("qt=%s\n", QT_VERSION_STR);
#else
    std::printf("qt=unavailable\n");
#endif

#ifdef PWB_INSTALL_PREFIX
    std::printf("prefix=%s\n", PWB_INSTALL_PREFIX);
#else
    std::printf("prefix=unset\n");
#endif

    // Resource search dirs the application would probe (relative to prefix).
#ifdef PWB_RESOURCE_DIR
    std::printf("resource_dir=%s\n", PWB_RESOURCE_DIR);
#endif
#ifdef PWB_TEMPLATE_DIR
    std::printf("template_dir=%s\n", PWB_TEMPLATE_DIR);
#endif
#ifdef PWB_ICON_DIR
    std::printf("icon_dir=%s\n", PWB_ICON_DIR);
#endif
#ifdef PWB_SCHEMA_DIR
    std::printf("schema_dir=%s\n", PWB_SCHEMA_DIR);
#endif

    // Expected runtime binary / DLL dirs.
#ifdef PWB_BIN_DIR
    std::printf("bin_dir=%s\n", PWB_BIN_DIR);
#endif
#ifdef PWB_QGIS_RUNTIME_DIR
    std::printf("qgis_runtime_dir=%s\n", PWB_QGIS_RUNTIME_DIR);
#endif
#ifdef PWB_QT_RUNTIME_DIR
    std::printf("qt_runtime_dir=%s\n", PWB_QT_RUNTIME_DIR);
#endif

    return 0;
}
