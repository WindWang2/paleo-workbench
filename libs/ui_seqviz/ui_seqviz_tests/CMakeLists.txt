# UI-10 — ui_seqviz tests. ctest names: ui_seqviz.* — the core state test
# is Qt-free/headless; the widget smoke runs offscreen.

add_executable(ui_seqviz.core_state core_state_test.cpp)
target_compile_features(ui_seqviz.core_state PRIVATE cxx_std_20)
target_include_directories(ui_seqviz.core_state PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ui_seqviz.core_state PRIVATE
    Pwb::UiSeqviz Pwb::Domain Pwb::UiWorkers Pwb::JobRuntime
    Pwb::MappingDocument Pwb::WellScience Pwb::UiDataCore)
add_test(NAME ui_seqviz.core_state COMMAND ui_seqviz.core_state)
set_tests_properties(ui_seqviz.core_state PROPERTIES TIMEOUT 120)

# Qt widget smoke (offscreen): every ported widget constructs + responds.
if(TARGET pwb_ui_seqviz_qt)
    add_executable(ui_seqviz.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_seqviz.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_seqviz.qt_widgets_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_seqviz.qt_widgets_smoke PRIVATE
        Pwb::UiSeqvizQt Pwb::UiShellQt Qt6::Widgets Qt6::Gui)
    add_test(NAME ui_seqviz.qt_widgets_smoke
             COMMAND ui_seqviz.qt_widgets_smoke)
    set_tests_properties(ui_seqviz.qt_widgets_smoke PROPERTIES
        TIMEOUT 180
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        # QGIS vendor runtime closure (link path reaches qgis libs through
        # UiShellQt); prepend so libodbc/libcryptopp etc. resolve.
        ENVIRONMENT_MODIFICATION "LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}")
endif()
