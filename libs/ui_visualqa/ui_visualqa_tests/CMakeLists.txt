# UI-16 — ui_visualqa tests. ctest names: ui_visualqa.*
#
#   ui_visualqa.core_smoke        Qt-free: registries/vocabulary parity,
#                                 check bodies on synthetic snapshots,
#                                 dual-volume numpy-parity math.
#   ui_visualqa.qt_widgets_smoke  offscreen Qt: drive recipes over a
#                                 FakeProbe seam double, V11 scenario
#                                 host on the real ported widgets +
#                                 injected surface seams, dual-volume
#                                 prototype window.

# --- Qt-free core smoke ----------------------------------------------------
add_executable(ui_visualqa.core_smoke core_smoke_test.cpp)
target_compile_features(ui_visualqa.core_smoke PRIVATE cxx_std_20)
target_link_libraries(ui_visualqa.core_smoke PRIVATE
    Pwb::UiVisualqa Pwb::Domain Pwb::ToolPolicy)
target_include_directories(ui_visualqa.core_smoke PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_visualqa.core_smoke COMMAND ui_visualqa.core_smoke)
set_tests_properties(ui_visualqa.core_smoke PROPERTIES TIMEOUT 120)

# --- Qt widget smoke (offscreen) -------------------------------------------
if(TARGET pwb_ui_visualqa_qt)
    add_executable(ui_visualqa.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_visualqa.qt_widgets_smoke
        PRIVATE cxx_std_20)
    set_target_properties(ui_visualqa.qt_widgets_smoke
        PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_visualqa.qt_widgets_smoke PRIVATE
        Pwb::UiVisualqaQt Pwb::ToolPolicy Qt6::Widgets)
    target_include_directories(ui_visualqa.qt_widgets_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_visualqa.qt_widgets_smoke
             COMMAND ui_visualqa.qt_widgets_smoke)
    # The V11 builders reuse Pwb::UiWorkstationQt/Pwb::UiWellseisQt which
    # link the vendored QGIS/GDAL stack — same runtime env protocol as
    # libs/ui_map/ui_map_tests so the SO deps resolve.
    set_tests_properties(ui_visualqa.qt_widgets_smoke PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        TIMEOUT 180)
endif()
