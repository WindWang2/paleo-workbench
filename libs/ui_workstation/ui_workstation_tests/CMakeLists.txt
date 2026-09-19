# UI-12 — ui_workstation tests. ctest names: ui_workstation.* —
# Qt-free core semantics headless, Qt widgets offscreen smoke.

add_executable(ui_workstation.core core_test.cpp)
target_compile_features(ui_workstation.core PRIVATE cxx_std_20)
target_link_libraries(ui_workstation.core PRIVATE Pwb::UiWorkstation)
target_include_directories(ui_workstation.core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_workstation.core COMMAND ui_workstation.core)
set_tests_properties(ui_workstation.core PROPERTIES TIMEOUT 120)

# Qt widget smoke (offscreen): every ported widget constructs +
# responds; the frame composes the registry dock set.
if(TARGET pwb_ui_workstation_qt)
    add_executable(ui_workstation.qt_widgets_smoke
        qt_widgets_smoke_test.cpp)
    target_compile_features(ui_workstation.qt_widgets_smoke
        PRIVATE cxx_std_20)
    set_target_properties(ui_workstation.qt_widgets_smoke
        PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_workstation.qt_widgets_smoke PRIVATE
        Pwb::UiWorkstationQt Qt6::Widgets)
    add_test(NAME ui_workstation.qt_widgets_smoke
             COMMAND ui_workstation.qt_widgets_smoke)
    set_tests_properties(ui_workstation.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        # Transitive link reaches the vendored QGIS runtime (via
        # UiShellQt); prepend so libodbc/libcryptopp etc. resolve.
        ENVIRONMENT_MODIFICATION
        "LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}")
endif()
