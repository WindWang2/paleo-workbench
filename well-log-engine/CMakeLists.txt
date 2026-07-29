cmake_minimum_required(VERSION 3.24)

if(NOT DEFINED CMAKE_TOOLCHAIN_FILE AND DEFINED ENV{VCPKG_ROOT})
    set(
        CMAKE_TOOLCHAIN_FILE
        "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
        CACHE FILEPATH
        "Default WellLogEngine vcpkg toolchain"
    )
endif()

project(
    WellLogEngine
    VERSION 0.1.0
    DESCRIPTION "Host-independent C++20 well logging engine"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CTest)
include(CMakePackageConfigHelpers)
include(GNUInstallDirs)

option(WELLLOG_BUILD_TESTS "Build WellLogEngine tests" ${BUILD_TESTING})
option(WELLLOG_BUILD_SHARED "Build WellLogEngine shared libraries" OFF)
option(WELLLOG_WARNINGS_AS_ERRORS "Treat WellLogEngine warnings as errors" OFF)
option(
    WELLLOG_BUILD_QT_WIDGETS
    "Build the optional Qt Widgets/OpenGL adapter"
    OFF
)

if(WELLLOG_BUILD_QT_WIDGETS)
    find_package(
        Qt6 6.8
        REQUIRED
        COMPONENTS Widgets OpenGLWidgets
    )
    if(WELLLOG_BUILD_TESTS)
        find_package(Qt6 6.8 REQUIRED COMPONENTS Test)
    endif()
    qt_standard_project_setup(REQUIRES 6.8)
endif()

if(WELLLOG_BUILD_SHARED)
    set(WELLLOG_LIBRARY_TYPE SHARED)
else()
    set(WELLLOG_LIBRARY_TYPE STATIC)
endif()

function(welllog_enable_warnings target)
    if(MSVC)
        target_compile_options("${target}" PRIVATE /W4 /permissive-)
        if(WELLLOG_WARNINGS_AS_ERRORS)
            target_compile_options("${target}" PRIVATE /WX)
        endif()
    else()
        target_compile_options(
            "${target}"
            PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion
        )
        if(WELLLOG_WARNINGS_AS_ERRORS)
            target_compile_options("${target}" PRIVATE -Werror)
        endif()
    endif()
endfunction()

add_library(welllog_core ${WELLLOG_LIBRARY_TYPE}
    src/core/document.cpp
    src/core/entity_id.cpp
)
add_library(WellLog::Core ALIAS welllog_core)
set_target_properties(welllog_core PROPERTIES
    EXPORT_NAME Core
    OUTPUT_NAME welllog-core
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_core PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_core)
target_include_directories(welllog_core
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_core
        PRIVATE WELLLOG_CORE_BUILD
        PUBLIC WELLLOG_CORE_SHARED
    )
endif()

add_library(welllog_scene ${WELLLOG_LIBRARY_TYPE}
    src/scene/scene.cpp
)
add_library(WellLog::Scene ALIAS welllog_scene)
set_target_properties(welllog_scene PROPERTIES
    EXPORT_NAME Scene
    OUTPUT_NAME welllog-scene
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_scene PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_scene)
target_link_libraries(welllog_scene PUBLIC WellLog::Core)
target_include_directories(welllog_scene
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_scene
        PRIVATE WELLLOG_SCENE_BUILD
        PUBLIC WELLLOG_SCENE_SHARED
    )
endif()

add_library(welllog_export_vector ${WELLLOG_LIBRARY_TYPE}
    src/export_vector/svg.cpp
)
add_library(WellLog::ExportVector ALIAS welllog_export_vector)
set_target_properties(welllog_export_vector PROPERTIES
    EXPORT_NAME ExportVector
    OUTPUT_NAME welllog-export-vector
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_export_vector PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_export_vector)
target_link_libraries(welllog_export_vector PUBLIC WellLog::Scene)
target_include_directories(welllog_export_vector
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_export_vector
        PRIVATE WELLLOG_EXPORT_VECTOR_BUILD
        PUBLIC WELLLOG_EXPORT_VECTOR_SHARED
    )
endif()

add_library(welllog_session ${WELLLOG_LIBRARY_TYPE}
    src/session/session.cpp
)
add_library(WellLog::Session ALIAS welllog_session)
set_target_properties(welllog_session PROPERTIES
    EXPORT_NAME Session
    OUTPUT_NAME welllog-session
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_session PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_session)
target_link_libraries(welllog_session PUBLIC WellLog::Core WellLog::Scene)
target_include_directories(welllog_session
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_session
        PRIVATE WELLLOG_SESSION_BUILD
        PUBLIC WELLLOG_SESSION_SHARED
    )
endif()

add_library(welllog_io ${WELLLOG_LIBRARY_TYPE}
    src/io/manifest.cpp
)
add_library(WellLog::IO ALIAS welllog_io)
set_target_properties(welllog_io PROPERTIES
    EXPORT_NAME IO
    OUTPUT_NAME welllog-io
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_io PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_io)
target_link_libraries(welllog_io PUBLIC WellLog::Core)
target_include_directories(welllog_io
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_io
        PRIVATE WELLLOG_IO_BUILD
        PUBLIC WELLLOG_IO_SHARED
    )
endif()

add_library(welllog_render_gl ${WELLLOG_LIBRARY_TYPE}
    src/render_gl/capability.cpp
    src/render_gl/renderer.cpp
)
add_library(WellLog::RenderGL ALIAS welllog_render_gl)
set_target_properties(welllog_render_gl PROPERTIES
    EXPORT_NAME RenderGL
    OUTPUT_NAME welllog-render-gl
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_render_gl PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_render_gl)
target_link_libraries(welllog_render_gl PUBLIC WellLog::Scene)
target_include_directories(welllog_render_gl
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
    PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_render_gl
        PRIVATE WELLLOG_RENDER_GL_BUILD
        PUBLIC WELLLOG_RENDER_GL_SHARED
    )
endif()

if(WELLLOG_BUILD_QT_WIDGETS)
    qt_add_library(welllog_qtwidgets ${WELLLOG_LIBRARY_TYPE}
        src/qtwidgets/well_log_view.cpp
        include/welllog/qtwidgets/well_log_view.hpp
    )
    add_library(WellLog::QtWidgets ALIAS welllog_qtwidgets)
    set_target_properties(welllog_qtwidgets PROPERTIES
        EXPORT_NAME QtWidgets
        OUTPUT_NAME welllog-qtwidgets
        VERSION "${PROJECT_VERSION}"
        SOVERSION "${PROJECT_VERSION_MAJOR}"
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN YES
    )
    target_compile_features(welllog_qtwidgets PUBLIC cxx_std_20)
    welllog_enable_warnings(welllog_qtwidgets)
    target_link_libraries(
        welllog_qtwidgets
        PUBLIC
            WellLog::RenderGL
            WellLog::Session
            Qt6::OpenGLWidgets
            Qt6::Widgets
    )
    target_include_directories(welllog_qtwidgets
        PUBLIC
            "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
            "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    if(WELLLOG_BUILD_SHARED)
        target_compile_definitions(
            welllog_qtwidgets
            PRIVATE WELLLOG_QTWIDGETS_BUILD
            PUBLIC WELLLOG_QTWIDGETS_SHARED
        )
    endif()
endif()

install(
    TARGETS
        welllog_core
        welllog_scene
        welllog_export_vector
        welllog_session
        welllog_io
        welllog_render_gl
    EXPORT WellLogTargets
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    INCLUDES DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
)
if(WELLLOG_BUILD_QT_WIDGETS)
    install(
        TARGETS welllog_qtwidgets
        EXPORT WellLogTargets
        RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        INCLUDES DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    )
endif()
install(
    DIRECTORY include/
    DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    FILES_MATCHING PATTERN "*.hpp"
)
install(
    DIRECTORY schemas/
    DESTINATION "${CMAKE_INSTALL_DATADIR}/welllog/schemas"
    FILES_MATCHING PATTERN "*.json"
)
install(
    EXPORT WellLogTargets
    FILE WellLogTargets.cmake
    NAMESPACE WellLog::
    DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/WellLog"
)
configure_package_config_file(
    cmake/WellLogConfig.cmake.in
    "${CMAKE_CURRENT_BINARY_DIR}/WellLogConfig.cmake"
    INSTALL_DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/WellLog"
)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/WellLogConfigVersion.cmake"
    VERSION "${PROJECT_VERSION}"
    COMPATIBILITY SameMajorVersion
)
install(
    FILES
        "${CMAKE_CURRENT_BINARY_DIR}/WellLogConfig.cmake"
        "${CMAKE_CURRENT_BINARY_DIR}/WellLogConfigVersion.cmake"
    DESTINATION "${CMAKE_INSTALL_LIBDIR}/cmake/WellLog"
)

if(WELLLOG_BUILD_TESTS)
    add_executable(welllog_session_tests
        tests/integration/session_submission_test.cpp
    )
    target_compile_features(welllog_session_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_session_tests)
    target_link_libraries(welllog_session_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.session COMMAND welllog_session_tests)

    add_executable(welllog_manifest_tests
        tests/integration/manifest_roundtrip_test.cpp
    )
    target_compile_features(welllog_manifest_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_manifest_tests)
    target_link_libraries(
        welllog_manifest_tests
        PRIVATE WellLog::IO WellLog::Session
    )
    add_test(NAME welllog.manifest COMMAND welllog_manifest_tests)

    add_executable(welllog_headless_svg_tests
        tests/integration/headless_svg_test.cpp
    )
    target_compile_features(welllog_headless_svg_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_headless_svg_tests)
    target_link_libraries(
        welllog_headless_svg_tests
        PRIVATE WellLog::ExportVector WellLog::Session
    )
    add_test(NAME welllog.headless-svg COMMAND welllog_headless_svg_tests)

    add_executable(welllog_viewport_tests
        tests/integration/viewport_interaction_test.cpp
    )
    target_compile_features(welllog_viewport_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_viewport_tests)
    target_link_libraries(welllog_viewport_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.viewport COMMAND welllog_viewport_tests)

    add_executable(welllog_render_gl_tests
        tests/render_gl/capability_test.cpp
    )
    target_compile_features(welllog_render_gl_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_render_gl_tests)
    target_include_directories(
        welllog_render_gl_tests
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(
        welllog_render_gl_tests
        PRIVATE WellLog::RenderGL
    )
    add_test(NAME welllog.render-gl COMMAND welllog_render_gl_tests)

    if(WELLLOG_BUILD_QT_WIDGETS)
        qt_add_executable(welllog_qt_widget_tests
            tests/qt/well_log_view_test.cpp
        )
        welllog_enable_warnings(welllog_qt_widget_tests)
        target_link_libraries(
            welllog_qt_widget_tests
            PRIVATE WellLog::QtWidgets Qt6::Test
        )
        add_test(NAME welllog.qt-widget COMMAND welllog_qt_widget_tests)
        add_test(
            NAME welllog.qt-unavailable
            COMMAND
                welllog_qt_widget_tests
                unavailable_context_publishes_a_capability_report
        )
        set_tests_properties(
            welllog.qt-unavailable
            PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=minimal"
        )
        if(UNIX AND NOT APPLE)
            set_tests_properties(
                welllog.qt-widget
                PROPERTIES ENVIRONMENT "LIBGL_ALWAYS_SOFTWARE=1"
            )
        endif()
    endif()

    add_test(
        NAME welllog.package.consumer
        COMMAND
            "${CMAKE_COMMAND}"
            "-DENGINE_BUILD_DIR=${CMAKE_BINARY_DIR}"
            "-DCONSUMER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/tests/consumer"
            "-DTEST_ROOT=${CMAKE_CURRENT_BINARY_DIR}/package-consumer"
            "-DTEST_CONFIG=$<CONFIG>"
            "-DENGINE_GENERATOR=${CMAKE_GENERATOR}"
            "-DENGINE_GENERATOR_PLATFORM=${CMAKE_GENERATOR_PLATFORM}"
            "-DENGINE_GENERATOR_TOOLSET=${CMAKE_GENERATOR_TOOLSET}"
            "-DENGINE_CXX_COMPILER=${CMAKE_CXX_COMPILER}"
            "-DENGINE_CXX_FLAGS=${CMAKE_CXX_FLAGS}"
            "-DENGINE_EXE_LINKER_FLAGS=${CMAKE_EXE_LINKER_FLAGS}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/consumer/run_consumer_test.cmake"
    )
    add_test(
        NAME welllog.svg.package.consumer
        COMMAND
            "${CMAKE_COMMAND}"
            "-DENGINE_BUILD_DIR=${CMAKE_BINARY_DIR}"
            "-DCONSUMER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/tests/svg_consumer"
            "-DTEST_ROOT=${CMAKE_CURRENT_BINARY_DIR}/svg-package-consumer"
            "-DTEST_CONFIG=$<CONFIG>"
            "-DENGINE_GENERATOR=${CMAKE_GENERATOR}"
            "-DENGINE_GENERATOR_PLATFORM=${CMAKE_GENERATOR_PLATFORM}"
            "-DENGINE_GENERATOR_TOOLSET=${CMAKE_GENERATOR_TOOLSET}"
            "-DENGINE_CXX_COMPILER=${CMAKE_CXX_COMPILER}"
            "-DENGINE_CXX_FLAGS=${CMAKE_CXX_FLAGS}"
            "-DENGINE_EXE_LINKER_FLAGS=${CMAKE_EXE_LINKER_FLAGS}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/consumer/run_consumer_test.cmake"
    )
    if(WELLLOG_BUILD_QT_WIDGETS)
        add_test(
            NAME welllog.qt.package.consumer
            COMMAND
                "${CMAKE_COMMAND}"
                "-DENGINE_BUILD_DIR=${CMAKE_BINARY_DIR}"
                "-DCONSUMER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/tests/qt_consumer"
                "-DTEST_ROOT=${CMAKE_CURRENT_BINARY_DIR}/qt-package-consumer"
                "-DTEST_CONFIG=$<CONFIG>"
                "-DENGINE_GENERATOR=${CMAKE_GENERATOR}"
                "-DENGINE_GENERATOR_PLATFORM=${CMAKE_GENERATOR_PLATFORM}"
                "-DENGINE_GENERATOR_TOOLSET=${CMAKE_GENERATOR_TOOLSET}"
                "-DENGINE_CXX_COMPILER=${CMAKE_CXX_COMPILER}"
                "-DENGINE_CXX_FLAGS=${CMAKE_CXX_FLAGS}"
                "-DENGINE_EXE_LINKER_FLAGS=${CMAKE_EXE_LINKER_FLAGS}"
                -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/consumer/run_consumer_test.cmake"
        )
    endif()
    add_test(
        NAME welllog.core.dependency-boundary
        COMMAND
            "${CMAKE_COMMAND}"
            "-DCORE_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/include/welllog/core"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/cmake/check_core_boundary.cmake"
    )
endif()
