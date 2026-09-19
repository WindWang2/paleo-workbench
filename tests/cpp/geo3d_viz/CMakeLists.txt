# CONV-GEO3D test suite: core (scene registry / camera / adapter /
# controller — headless), widget (offscreen smoke / open-close / invalid
# geometry / selection) and the Python oracle conformance replay.

if(NOT TARGET Pwb::Geo3DViz)
    message(FATAL_ERROR "geo3d_viz tests need Pwb::Geo3DViz")
endif()

set(PWB_GEO3D_FIXTURES "${CMAKE_CURRENT_SOURCE_DIR}/fixtures")

add_executable(geo3d.core_test geo3d_core_test.cpp)
target_compile_features(geo3d.core_test PRIVATE cxx_std_20)
target_link_libraries(geo3d.core_test PRIVATE Pwb::Geo3DViz Qt6::Core
                                               Qt6::Gui Qt6::Widgets)
target_compile_definitions(geo3d.core_test PRIVATE
    PWB_GEO3D_FIXTURES="${PWB_GEO3D_FIXTURES}")
add_test(NAME geo3d.core_test COMMAND geo3d.core_test)
set_tests_properties(geo3d.core_test PROPERTIES TIMEOUT 300)

add_executable(geo3d.widget_test geo3d_widget_test.cpp)
target_compile_features(geo3d.widget_test PRIVATE cxx_std_20)
target_link_libraries(geo3d.widget_test PRIVATE Pwb::Geo3DViz Qt6::Core
                                                Qt6::Gui Qt6::Widgets)
if(UNIX AND NOT APPLE)
    # VIZ-C: the widget test installs an X error handler so broken-GLX
    # hosts fail softly into the honest GL-less degradation path instead
    # of dying inside QOpenGLContext creation.
    find_package(X11)
    if(X11_FOUND)
        target_link_libraries(geo3d.widget_test PRIVATE X11::X11)
        target_compile_definitions(geo3d.widget_test PRIVATE
            PWB_GEO3D_HAVE_X11=1)
    else()
        message(STATUS "geo3d.widget_test: X11 not found — the X error "
                       "guard is disabled (broken-GLX hosts may abort)")
    endif()
endif()
add_test(NAME geo3d.widget_test COMMAND geo3d.widget_test)
set_tests_properties(geo3d.widget_test PROPERTIES TIMEOUT 300
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;QT_LOGGING_RULES=qt.*=false")

add_executable(geo3d.oracle_test geo3d_oracle_test.cpp)
target_compile_features(geo3d.oracle_test PRIVATE cxx_std_20)
target_link_libraries(geo3d.oracle_test PRIVATE Pwb::Geo3DViz Qt6::Core
                                                Qt6::Gui Qt6::Widgets)
target_compile_definitions(geo3d.oracle_test PRIVATE
    PWB_GEO3D_STYLE_ORACLE="${PWB_GEO3D_FIXTURES}/geo3d_style_oracle.json"
    PWB_GEO3D_STATE_ORACLE="${PWB_GEO3D_FIXTURES}/geo3d_state_oracle.json")
add_test(NAME geo3d.oracle_test COMMAND geo3d.oracle_test)
set_tests_properties(geo3d.oracle_test PROPERTIES TIMEOUT 300)
