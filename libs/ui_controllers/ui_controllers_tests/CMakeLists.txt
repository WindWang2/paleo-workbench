# UI-14 — ui_controllers tests. ctest names: ui_controllers.*
# (Qt-free core smoke) + ui_controllers.qt_smoke (offscreen).

add_executable(ui_controllers.core_smoke core_smoke_test.cpp)
target_compile_features(ui_controllers.core_smoke PRIVATE cxx_std_20)
target_link_libraries(ui_controllers.core_smoke PRIVATE
    Pwb::UiControllers)
target_include_directories(ui_controllers.core_smoke PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_controllers.core_smoke COMMAND ui_controllers.core_smoke)
set_tests_properties(ui_controllers.core_smoke PROPERTIES TIMEOUT 120)

# Qt smoke (offscreen): the QObject shells construct, signal-emit, wire
# pages by metaobject name and drive a JobOwnerRunner task to completion
# on the real QgsTaskManager (QgsApplication fixture inside the test).
if(TARGET pwb_ui_controllers_qt)
    add_executable(ui_controllers.qt_smoke qt_smoke_test.cpp)
    target_compile_features(ui_controllers.qt_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_controllers.qt_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_controllers.qt_smoke PRIVATE
        Pwb::UiControllersQt Qt6::Widgets)
    target_include_directories(ui_controllers.qt_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_controllers.qt_smoke
             COMMAND ui_controllers.qt_smoke)
    set_tests_properties(ui_controllers.qt_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        # QGIS vendor runtime closure — the task bridge reaches
        # QgsApplication::taskManager().
        ENVIRONMENT_MODIFICATION "LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}")
endif()
