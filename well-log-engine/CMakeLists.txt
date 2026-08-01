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
find_package(Threads REQUIRED)
find_package(ZLIB REQUIRED)

option(WELLLOG_BUILD_TESTS "Build WellLogEngine tests" ${BUILD_TESTING})
option(WELLLOG_BUILD_SHARED "Build WellLogEngine shared libraries" OFF)
option(WELLLOG_WARNINGS_AS_ERRORS "Treat WellLogEngine warnings as errors" OFF)
option(WELLLOG_BUILD_BENCHMARKS "Build WellLogEngine performance benchmarks" OFF)
option(
    WELLLOG_BUILD_QT_WIDGETS
    "Build the optional Qt Widgets/OpenGL adapter"
    OFF
)
option(
    WELLLOG_BUILD_PYTHON
    "Build the optional PySide6/Shiboken6 bindings"
    OFF
)
option(
    WELLLOG_BUILD_TEXT
    "Build the Unicode text pipeline (HarfBuzz/FreeType/ICU)"
    ON
)

if(WELLLOG_BUILD_TEXT)
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(HarfBuzz REQUIRED IMPORTED_TARGET harfbuzz)
    pkg_check_modules(FreeType REQUIRED IMPORTED_TARGET freetype2)
    pkg_check_modules(ICU_UC REQUIRED IMPORTED_TARGET icu-uc)
    pkg_check_modules(ICU_I18N REQUIRED IMPORTED_TARGET icu-i18n)
endif()

if(WELLLOG_BUILD_PYTHON)
    set(WELLLOG_BUILD_QT_WIDGETS ON)
    set(CMAKE_POSITION_INDEPENDENT_CODE ON)
endif()

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

if(WELLLOG_BUILD_BENCHMARKS AND NOT WELLLOG_BUILD_QT_WIDGETS)
    find_package(Qt6 6.8 REQUIRED COMPONENTS Gui)
endif()

if(WELLLOG_BUILD_PYTHON)
    find_package(
        Python 3.12
        REQUIRED
        COMPONENTS Interpreter Development
    )
    if(Python_VERSION VERSION_GREATER_EQUAL 3.14)
        message(FATAL_ERROR "WellLog Python bindings support CPython 3.12 and 3.13")
    endif()
    execute_process(
        COMMAND
            "${Python_EXECUTABLE}"
            -c
            "import pathlib, PySide6, shiboken6, shiboken6_generator; print(pathlib.Path(PySide6.__file__).parent / 'lib' / 'cmake'); print(pathlib.Path(shiboken6.__file__).parent / 'lib' / 'cmake'); print(pathlib.Path(shiboken6_generator.__file__).parent / 'lib' / 'cmake')"
        RESULT_VARIABLE WELLLOG_PYTHON_PROFILE_RESULT
        OUTPUT_VARIABLE WELLLOG_PYTHON_CMAKE_PATHS
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    if(NOT WELLLOG_PYTHON_PROFILE_RESULT EQUAL 0)
        message(
            FATAL_ERROR
            "PySide6, shiboken6 and shiboken6_generator must be installed for the selected Python"
        )
    endif()
    string(REPLACE "\n" ";" WELLLOG_PYTHON_CMAKE_PATHS "${WELLLOG_PYTHON_CMAKE_PATHS}")
    list(PREPEND CMAKE_PREFIX_PATH ${WELLLOG_PYTHON_CMAKE_PATHS})
    find_package(Shiboken6 REQUIRED CONFIG)
    find_package(PySide6 REQUIRED CONFIG)
    find_package(
        Shiboken6Tools
        ${PySide6_VERSION}
        EXACT
        REQUIRED
        CONFIG
    )
    get_target_property(
        WELLLOG_SHIBOKEN_GENERATOR_RELEASE
        Shiboken6::shiboken6
        IMPORTED_LOCATION_RELEASE
    )
    if(
        CMAKE_BUILD_TYPE STREQUAL "Debug"
        AND WELLLOG_SHIBOKEN_GENERATOR_RELEASE
    )
        set_target_properties(
            Shiboken6::shiboken6
            PROPERTIES
                IMPORTED_LOCATION_DEBUG
                    "${WELLLOG_SHIBOKEN_GENERATOR_RELEASE}"
        )
    endif()
    if(NOT PySide6_VERSION VERSION_EQUAL Shiboken6_VERSION)
        message(
            FATAL_ERROR
            "PySide6 ${PySide6_VERSION} and Shiboken6 ${Shiboken6_VERSION} must match"
        )
    endif()
    if(NOT PySide6_VERSION VERSION_EQUAL Shiboken6Tools_VERSION)
        message(
            FATAL_ERROR
            "PySide6 ${PySide6_VERSION} and Shiboken6Tools ${Shiboken6Tools_VERSION} must match"
        )
    endif()
    if(NOT Qt6_VERSION VERSION_EQUAL PySide6_VERSION)
        message(
            FATAL_ERROR
            "Qt ${Qt6_VERSION} and PySide6 ${PySide6_VERSION} must use the same SDK profile"
        )
    endif()
    execute_process(
        COMMAND "${CMAKE_CXX_COMPILER}" -print-file-name=include
        OUTPUT_VARIABLE WELLLOG_COMPILER_BUILTIN_INCLUDE
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )
    set(
        WELLLOG_SHIBOKEN_COMPILER_OPTIONS
        "--compiler-path=${CMAKE_CXX_COMPILER}"
    )
    if(IS_DIRECTORY "${WELLLOG_COMPILER_BUILTIN_INCLUDE}")
        list(
            APPEND
            WELLLOG_SHIBOKEN_COMPILER_OPTIONS
            "-isystem${WELLLOG_COMPILER_BUILTIN_INCLUDE}"
        )
    endif()
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
    src/core/utf8.cpp
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

# Table Projection (ADR 0022, #154): a Qt-agnostic, virtualized projection of a
# WellLogDocument into per-Sampling-Axis curve tables. Depends only on Core
# (reads raw Curve buffers straight from the document). Qt-facing virtualization
# lives in the qtwidgets adapter.
add_library(welllog_table ${WELLLOG_LIBRARY_TYPE}
    src/table/table_projection.cpp
)
add_library(WellLog::Table ALIAS welllog_table)
set_target_properties(welllog_table PROPERTIES
    EXPORT_NAME Table
    OUTPUT_NAME welllog-table
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_table PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_table)
target_link_libraries(welllog_table PUBLIC WellLog::Core)
target_include_directories(welllog_table
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_table
        PRIVATE WELLLOG_TABLE_BUILD
        PUBLIC WELLLOG_TABLE_SHARED
    )
endif()

add_library(welllog_scene ${WELLLOG_LIBRARY_TYPE}
    src/scene/curve_lod.cpp
    src/scene/image_pyramid.cpp
    src/scene/scene.cpp
    src/scene/triangulate.cpp
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
    src/export_vector/pagination.cpp
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
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_export_vector
        PRIVATE WELLLOG_EXPORT_VECTOR_BUILD
        PUBLIC WELLLOG_EXPORT_VECTOR_SHARED
    )
endif()

# Table export backends (ADR 0022 / table-and-export.md §5-§7, §10, #155): CSV,
# versioned XML, and XLSX writers over a TableProjection. Depends only on Table
# (which pulls Core) — Qt stays in the adapter. XLSX adds PRIVATE ZLIB for the
# self-contained OOXML zip writer.
add_library(welllog_export_table ${WELLLOG_LIBRARY_TYPE}
    src/export_table/csv.cpp
    src/export_table/xml.cpp
    src/export_table/xlsx.cpp
    src/export_table/zip_writer.cpp
)
add_library(WellLog::ExportTable ALIAS welllog_export_table)
set_target_properties(welllog_export_table PROPERTIES
    EXPORT_NAME ExportTable
    OUTPUT_NAME welllog-export-table
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_export_table PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_export_table)
target_link_libraries(welllog_export_table
    PUBLIC WellLog::Table
    PRIVATE ZLIB::ZLIB
)
target_include_directories(welllog_export_table
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_export_table
        PRIVATE WELLLOG_EXPORT_TABLE_BUILD
        PUBLIC WELLLOG_EXPORT_TABLE_SHARED
    )
endif()

# PDF export backend (ADR: hand-rolled writer, #185; scene emission #187). No
# third-party PDF library; only zlib for FlateDecode stream compression.
add_library(welllog_export_pdf ${WELLLOG_LIBRARY_TYPE}
    src/export_vector/pdf.cpp
    src/export_vector/pdf_scene.cpp
)
add_library(WellLog::ExportPdf ALIAS welllog_export_pdf)
set_target_properties(welllog_export_pdf PROPERTIES
    EXPORT_NAME ExportPdf
    OUTPUT_NAME welllog-export-pdf
    VERSION "${PROJECT_VERSION}"
    SOVERSION "${PROJECT_VERSION_MAJOR}"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)
target_compile_features(welllog_export_pdf PUBLIC cxx_std_20)
welllog_enable_warnings(welllog_export_pdf)
target_link_libraries(welllog_export_pdf
    PUBLIC WellLog::Scene
    PRIVATE ZLIB::ZLIB
)
target_include_directories(welllog_export_pdf
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
if(WELLLOG_BUILD_SHARED)
    target_compile_definitions(
        welllog_export_pdf
        PRIVATE WELLLOG_EXPORT_PDF_BUILD
        PUBLIC WELLLOG_EXPORT_PDF_SHARED
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
target_link_libraries(
    welllog_session
    PUBLIC WellLog::Core WellLog::Scene
    PRIVATE Threads::Threads
)
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
    src/render_gl/raster.cpp
    src/render_gl/renderer.cpp
    src/render_gl/upload.cpp
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

if(WELLLOG_BUILD_TEXT)
    add_library(welllog_text ${WELLLOG_LIBRARY_TYPE}
        src/text/harfbuzz_text_engine.cpp
    )
    add_library(WellLog::Text ALIAS welllog_text)
    set_target_properties(welllog_text PROPERTIES
        EXPORT_NAME Text
        OUTPUT_NAME welllog-text
        VERSION "${PROJECT_VERSION}"
        SOVERSION "${PROJECT_VERSION_MAJOR}"
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN YES
    )
    target_compile_features(welllog_text PUBLIC cxx_std_20)
    welllog_enable_warnings(welllog_text)
    target_link_libraries(
        welllog_text
        PUBLIC WellLog::Scene
        PRIVATE
            PkgConfig::HarfBuzz
            PkgConfig::FreeType
            PkgConfig::ICU_UC
            PkgConfig::ICU_I18N
    )
    target_include_directories(welllog_text
        PUBLIC
            "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
            "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    if(WELLLOG_BUILD_SHARED)
        target_compile_definitions(
            welllog_text
            PRIVATE WELLLOG_TEXT_BUILD
            PUBLIC WELLLOG_TEXT_SHARED
        )
    endif()
endif()

if(WELLLOG_BUILD_QT_WIDGETS)
    qt_add_library(welllog_qtwidgets ${WELLLOG_LIBRARY_TYPE}
        src/qtwidgets/well_log_view.cpp
        src/qtwidgets/table_model.cpp
        include/welllog/qtwidgets/well_log_view.hpp
        include/welllog/qtwidgets/table_model.hpp
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
            WellLog::Table
            Qt6::OpenGLWidgets
            Qt6::Widgets
    )
    if(WELLLOG_BUILD_TEXT)
        target_link_libraries(welllog_qtwidgets PUBLIC WellLog::Text)
        target_compile_definitions(
            welllog_qtwidgets
            PRIVATE WELLLOG_WITH_TEXT
        )
    endif()
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

if(WELLLOG_BUILD_PYTHON)
    set(WELLLOG_PYTHON_GENERATED_SOURCES
        "${CMAKE_CURRENT_BINARY_DIR}/welllog/_QtWidgets/_qtwidgets_module_wrapper.cpp"
        "${CMAKE_CURRENT_BINARY_DIR}/welllog/_QtWidgets/welllog_wrapper.cpp"
        "${CMAKE_CURRENT_BINARY_DIR}/welllog/_QtWidgets/welllog_welllogview_wrapper.cpp"
    )
    set(FORCE_LIMITED_API OFF)
    shiboken_generator_create_binding(
        EXTENSION_TARGET _QtWidgets
        GENERATED_SOURCES ${WELLLOG_PYTHON_GENERATED_SOURCES}
        HEADERS "${CMAKE_CURRENT_SOURCE_DIR}/src/python/bindings.hpp"
        TYPESYSTEM_FILE
            "${CMAKE_CURRENT_SOURCE_DIR}/src/python/typesystem_welllog.xml"
        LIBRARY_TARGET welllog_qtwidgets
        QT_MODULES Core Gui Widgets OpenGLWidgets
        SHIBOKEN_EXTRA_OPTIONS
            "-I${CMAKE_CURRENT_SOURCE_DIR}/include"
            "-I${CMAKE_CURRENT_SOURCE_DIR}/src/python"
            "--language-level=c++20"
            ${WELLLOG_SHIBOKEN_COMPILER_OPTIONS}
    )
    target_sources(
        _QtWidgets
        PRIVATE
            src/python/numpy_bridge.cpp
            src/python/numpy_bridge.hpp
    )
    target_include_directories(
        _QtWidgets
        PRIVATE
            "${CMAKE_CURRENT_SOURCE_DIR}/include"
            "${CMAKE_CURRENT_SOURCE_DIR}/src/python"
    )
    set_target_properties(
        _QtWidgets
        PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY
                "${CMAKE_CURRENT_BINARY_DIR}/python/welllog"
            RUNTIME_OUTPUT_DIRECTORY
                "${CMAKE_CURRENT_BINARY_DIR}/python/welllog"
    )
    file(
        COPY
            "${CMAKE_CURRENT_SOURCE_DIR}/python/welllog/__init__.py"
            "${CMAKE_CURRENT_SOURCE_DIR}/python/welllog/errors.py"
        DESTINATION "${CMAKE_CURRENT_BINARY_DIR}/python/welllog"
    )
endif()

if(WELLLOG_BUILD_BENCHMARKS)
    add_executable(welllog_dense_curve_benchmark
        benchmarks/dense_curve_benchmark.cpp
    )
    target_compile_features(
        welllog_dense_curve_benchmark
        PRIVATE cxx_std_20
    )
    welllog_enable_warnings(welllog_dense_curve_benchmark)
    target_link_libraries(
        welllog_dense_curve_benchmark
        PRIVATE WellLog::RenderGL WellLog::Session Qt6::Gui
    )
    target_include_directories(
        welllog_dense_curve_benchmark
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
endif()

install(
    TARGETS
        welllog_core
        welllog_table
        welllog_scene
        welllog_export_vector
        welllog_export_pdf
        welllog_export_table
        welllog_session
        welllog_io
        welllog_render_gl
    EXPORT WellLogTargets
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    INCLUDES DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
)
if(WELLLOG_BUILD_TEXT)
    install(
        TARGETS welllog_text
        EXPORT WellLogTargets
        RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
        INCLUDES DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
    )
endif()
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
if(WELLLOG_BUILD_PYTHON)
    install(
        TARGETS _QtWidgets
        LIBRARY DESTINATION welllog COMPONENT Python
        RUNTIME DESTINATION welllog COMPONENT Python
    )
    install(
        FILES
            python/welllog/__init__.py
            python/welllog/__init__.pyi
            python/welllog/errors.py
            python/welllog/errors.pyi
            python/welllog/py.typed
        DESTINATION welllog
        COMPONENT Python
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
    add_executable(welllog_curve_lod_tests
        tests/scene/curve_lod_test.cpp
    )
    target_compile_features(welllog_curve_lod_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_curve_lod_tests)
    target_link_libraries(welllog_curve_lod_tests PRIVATE WellLog::Scene)
    add_test(NAME welllog.curve-lod COMMAND welllog_curve_lod_tests)

    add_executable(welllog_dense_curve_pipeline_tests
        tests/integration/dense_curve_pipeline_test.cpp
    )
    target_compile_features(
        welllog_dense_curve_pipeline_tests
        PRIVATE cxx_std_20
    )
    welllog_enable_warnings(welllog_dense_curve_pipeline_tests)
    target_link_libraries(
        welllog_dense_curve_pipeline_tests
        PRIVATE WellLog::RenderGL WellLog::Session
    )
    add_test(
        NAME welllog.dense-curve-pipeline
        COMMAND welllog_dense_curve_pipeline_tests
    )

    add_executable(welllog_session_tests
        tests/integration/session_submission_test.cpp
    )
    target_compile_features(welllog_session_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_session_tests)
    target_link_libraries(welllog_session_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.session COMMAND welllog_session_tests)

    add_executable(welllog_document_annotation_tests
        tests/integration/document_annotation_test.cpp
    )
    target_compile_features(
        welllog_document_annotation_tests
        PRIVATE cxx_std_20
    )
    welllog_enable_warnings(welllog_document_annotation_tests)
    target_link_libraries(
        welllog_document_annotation_tests
        PRIVATE WellLog::Session
    )
    add_test(
        NAME welllog.document-annotations
        COMMAND welllog_document_annotation_tests
    )

    add_executable(welllog_layer_preparation_tests
        tests/integration/layer_preparation_test.cpp
    )
    target_compile_features(
        welllog_layer_preparation_tests
        PRIVATE cxx_std_20
    )
    welllog_enable_warnings(welllog_layer_preparation_tests)
    target_link_libraries(
        welllog_layer_preparation_tests
        PRIVATE WellLog::Session
    )
    add_test(
        NAME welllog.layer-preparation
        COMMAND welllog_layer_preparation_tests
    )

    if(WELLLOG_BUILD_TEXT)
        add_executable(welllog_text_engine_tests
            tests/text/text_engine_test.cpp
        )
        target_compile_features(
            welllog_text_engine_tests
            PRIVATE cxx_std_20
        )
        welllog_enable_warnings(welllog_text_engine_tests)
        target_compile_definitions(
            welllog_text_engine_tests
            PRIVATE
                "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
        )
        target_link_libraries(
            welllog_text_engine_tests
            PRIVATE WellLog::Text
        )
        add_test(
            NAME welllog.text-engine
            COMMAND welllog_text_engine_tests
        )
    endif()

    if(WELLLOG_BUILD_TEXT)
        add_executable(welllog_text_scene_tests
            tests/integration/text_scene_test.cpp
        )
        target_compile_features(
            welllog_text_scene_tests
            PRIVATE cxx_std_20
        )
        welllog_enable_warnings(welllog_text_scene_tests)
        target_compile_definitions(
            welllog_text_scene_tests
            PRIVATE
                "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
        )
        target_link_libraries(
            welllog_text_scene_tests
            PRIVATE WellLog::Text WellLog::Session
        )
        add_test(
            NAME welllog.text-scene
            COMMAND welllog_text_scene_tests
        )

        add_executable(welllog_layer_svg_tests
            tests/integration/layer_svg_test.cpp
        )
        target_compile_features(
            welllog_layer_svg_tests
            PRIVATE cxx_std_20
        )
        welllog_enable_warnings(welllog_layer_svg_tests)
        target_compile_definitions(
            welllog_layer_svg_tests
            PRIVATE
                "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
        )
        target_link_libraries(
            welllog_layer_svg_tests
            PRIVATE WellLog::ExportVector WellLog::Text WellLog::Session
        )
        add_test(
            NAME welllog.layer-svg
            COMMAND welllog_layer_svg_tests
        )

        add_executable(welllog_scene_snapshot_tests
            tests/integration/scene_snapshot_test.cpp
        )
        target_compile_features(
            welllog_scene_snapshot_tests
            PRIVATE cxx_std_20
        )
        welllog_enable_warnings(welllog_scene_snapshot_tests)
        target_compile_definitions(
            welllog_scene_snapshot_tests
            PRIVATE
                "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
        )
        target_link_libraries(
            welllog_scene_snapshot_tests
            PRIVATE WellLog::Text WellLog::Session
        )
        add_test(
            NAME welllog.scene-snapshot
            COMMAND welllog_scene_snapshot_tests
        )
    endif()

    add_executable(welllog_multi_scale_tests
        tests/integration/multi_scale_track_test.cpp
    )
    target_compile_features(welllog_multi_scale_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_multi_scale_tests)
    target_compile_definitions(
        welllog_multi_scale_tests
        PRIVATE
            "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
    )
    target_link_libraries(
        welllog_multi_scale_tests
        PRIVATE WellLog::ExportVector WellLog::RenderGL WellLog::Text WellLog::Session
    )
    add_test(
        NAME welllog.multi-scale-track
        COMMAND welllog_multi_scale_tests
    )

    add_executable(welllog_crossover_fill_tests
        tests/integration/crossover_fill_test.cpp
    )
    target_compile_features(welllog_crossover_fill_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_crossover_fill_tests)
    target_link_libraries(
        welllog_crossover_fill_tests
        PRIVATE WellLog::ExportVector WellLog::RenderGL WellLog::Session
    )
    add_test(
        NAME welllog.crossover-fill
        COMMAND welllog_crossover_fill_tests
    )

    add_executable(welllog_image_layer_tests
        tests/integration/image_layer_test.cpp
    )
    target_compile_features(welllog_image_layer_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_image_layer_tests)
    target_include_directories(
        welllog_image_layer_tests
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(
        welllog_image_layer_tests
        PRIVATE WellLog::ExportVector WellLog::Session
    )
    add_test(
        NAME welllog.image-layer
        COMMAND welllog_image_layer_tests
    )

    add_executable(welllog_custom_layer_tests
        tests/integration/custom_layer_test.cpp
    )
    target_compile_features(welllog_custom_layer_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_custom_layer_tests)
    target_include_directories(
        welllog_custom_layer_tests
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(
        welllog_custom_layer_tests
        PRIVATE WellLog::ExportVector WellLog::RenderGL WellLog::Session
    )
    add_test(
        NAME welllog.custom-layer
        COMMAND welllog_custom_layer_tests
    )

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

    add_executable(welllog_paginated_svg_tests
        tests/integration/paginated_svg_test.cpp
    )
    target_compile_features(welllog_paginated_svg_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_paginated_svg_tests)
    target_link_libraries(
        welllog_paginated_svg_tests
        PRIVATE WellLog::ExportVector WellLog::Session
    )
    add_test(NAME welllog.paginated-svg COMMAND welllog_paginated_svg_tests)

    add_executable(welllog_pdf_spike_tests
        tests/integration/pdf_spike_test.cpp
    )
    target_compile_features(welllog_pdf_spike_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_pdf_spike_tests)
    target_link_libraries(
        welllog_pdf_spike_tests
        PRIVATE WellLog::ExportPdf ZLIB::ZLIB
    )
    add_test(NAME welllog.pdf-spike COMMAND welllog_pdf_spike_tests)

    add_executable(welllog_pdf_scene_tests
        tests/integration/pdf_scene_test.cpp
    )
    target_compile_features(welllog_pdf_scene_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_pdf_scene_tests)
    target_compile_definitions(
        welllog_pdf_scene_tests
        PRIVATE
            "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
    )
    target_link_libraries(
        welllog_pdf_scene_tests
        PRIVATE WellLog::ExportPdf WellLog::Text WellLog::Session ZLIB::ZLIB
    )
    add_test(NAME welllog.pdf-scene COMMAND welllog_pdf_scene_tests)

    add_executable(welllog_pdf_scene_full_tests
        tests/integration/pdf_scene_full_test.cpp
    )
    target_compile_features(welllog_pdf_scene_full_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_pdf_scene_full_tests)
    target_compile_definitions(
        welllog_pdf_scene_full_tests
        PRIVATE
            "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
    )
    target_include_directories(
        welllog_pdf_scene_full_tests
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(
        welllog_pdf_scene_full_tests
        PRIVATE WellLog::ExportPdf WellLog::Scene WellLog::Text WellLog::Session ZLIB::ZLIB
    )
    add_test(NAME welllog.pdf-scene-full COMMAND welllog_pdf_scene_full_tests)

    add_executable(welllog_export_parity_tests
        tests/integration/export_parity_test.cpp
    )
    target_compile_features(welllog_export_parity_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_export_parity_tests)
    target_compile_definitions(
        welllog_export_parity_tests
        PRIVATE
            "WELLLOG_TEST_FONT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/tests/assets/fonts\""
    )
    target_include_directories(
        welllog_export_parity_tests
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(
        welllog_export_parity_tests
        PRIVATE WellLog::ExportVector WellLog::ExportPdf WellLog::Scene WellLog::Text WellLog::Session ZLIB::ZLIB
    )
    add_test(NAME welllog.export-parity COMMAND welllog_export_parity_tests)

    add_executable(welllog_table_projection_tests
        tests/integration/table_projection_test.cpp
    )
    target_compile_features(welllog_table_projection_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_table_projection_tests)
    target_link_libraries(welllog_table_projection_tests PRIVATE WellLog::Table)
    add_test(NAME welllog.table-projection COMMAND welllog_table_projection_tests)

    # CSV table-export writer (ADR 0022 / table-and-export.md §7, #155).
    # Headless: links only ExportTable (Core+Table); no GL or Qt.
    add_executable(welllog_csv_table_export_tests
        tests/integration/csv_table_export_test.cpp
    )
    target_compile_features(welllog_csv_table_export_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_csv_table_export_tests)
    target_link_libraries(welllog_csv_table_export_tests PRIVATE WellLog::ExportTable)
    add_test(NAME welllog.csv-table-export COMMAND welllog_csv_table_export_tests)

    # Composite/Chained BufferView (#196, foundation for #162 append). Headless;
    # core-only — the type lives in core beside BufferView.
    add_executable(welllog_composite_buffer_view_tests
        tests/integration/composite_buffer_view_test.cpp
    )
    target_compile_features(welllog_composite_buffer_view_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_composite_buffer_view_tests)
    target_link_libraries(welllog_composite_buffer_view_tests PRIVATE WellLog::Core)
    add_test(NAME welllog.composite-buffer-view COMMAND welllog_composite_buffer_view_tests)

    # Composite-buffer consumer migration (#197): a multi-segment curve flows
    # through LOD + table projection/exporters identically to single-block.
    add_executable(welllog_composite_curve_migration_tests
        tests/integration/composite_curve_migration_test.cpp
    )
    target_compile_features(welllog_composite_curve_migration_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_composite_curve_migration_tests)
    target_link_libraries(
        welllog_composite_curve_migration_tests
        PRIVATE WellLog::Scene WellLog::Table WellLog::ExportTable
    )
    target_include_directories(
        welllog_composite_curve_migration_tests
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    add_test(NAME welllog.composite-curve-migration COMMAND welllog_composite_curve_migration_tests)

    # Versioned XML table-export writer (§6, #155). Headless; ExportTable only.
    add_executable(welllog_xml_table_export_tests
        tests/integration/xml_table_export_test.cpp
    )
    target_compile_features(welllog_xml_table_export_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_xml_table_export_tests)
    target_link_libraries(welllog_xml_table_export_tests PRIVATE WellLog::ExportTable)
    add_test(NAME welllog.xml-table-export COMMAND welllog_xml_table_export_tests)

    # Self-contained XLSX (OOXML+zlib) table export (§5, #155). Headless; reads
    # the archive back via ZLIB inflate (no Excel dependency).
    add_executable(welllog_xlsx_table_export_tests
        tests/integration/xlsx_table_export_test.cpp
    )
    target_compile_features(welllog_xlsx_table_export_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_xlsx_table_export_tests)
    target_link_libraries(
        welllog_xlsx_table_export_tests
        PRIVATE WellLog::ExportTable ZLIB::ZLIB
    )
    add_test(NAME welllog.xlsx-table-export COMMAND welllog_xlsx_table_export_tests)

    add_executable(welllog_viewport_tests
        tests/integration/viewport_interaction_test.cpp
    )
    target_compile_features(welllog_viewport_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_viewport_tests)
    target_link_libraries(welllog_viewport_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.viewport COMMAND welllog_viewport_tests)

    # Shared semantic Selection Set in WellLogSession (ADR 0024, #154 Phase B).
    # Headless: selection maps Reference Depth Range ↔ row span and remaps/
    # invalidates on document replacement; no GL or Qt needed.
    add_executable(welllog_session_selection_tests
        tests/integration/session_selection_test.cpp
    )
    target_compile_features(welllog_session_selection_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_session_selection_tests)
    target_link_libraries(welllog_session_selection_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.session-selection COMMAND welllog_session_selection_tests)

    # AppendBatchCommand (#198, ADR 0031): atomic curve tail-append producing a
    # new Document Revision, with no copy of the old data blocks; rejects
    # out-of-order/backfill tails and non-monotonic revisions. Headless.
    add_executable(welllog_append_batch_tests
        tests/integration/append_batch_test.cpp
    )
    target_compile_features(welllog_append_batch_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_append_batch_tests)
    target_link_libraries(welllog_append_batch_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.append-batch COMMAND welllog_append_batch_tests)

    # Incremental LOD tail-extension (#199, ADR 0031): extend_tail reuses the
    # unchanged earlier region's summaries and re-derives only the tail, with
    # parity to a full rebuild. Headless; Scene only.
    add_executable(welllog_incremental_lod_tests
        tests/integration/incremental_lod_test.cpp
    )
    target_compile_features(welllog_incremental_lod_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_incremental_lod_tests)
    target_link_libraries(welllog_incremental_lod_tests PRIVATE WellLog::Scene)
    add_test(NAME welllog.incremental-lod COMMAND welllog_incremental_lod_tests)

    # Session append-incremental LOD (#199): a session that appends a tail
    # (incremental extend_tail worker) produces a Prepared Scene LOD-identical
    # to a session that directly submits the full curve (full build). Headless;
    # Session only (dense curve drives the async worker).
    add_executable(welllog_append_incremental_session_tests
        tests/integration/append_incremental_session_test.cpp
    )
    target_compile_features(welllog_append_incremental_session_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_append_incremental_session_tests)
    target_link_libraries(welllog_append_incremental_session_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.append-incremental-session COMMAND welllog_append_incremental_session_tests)

    # Session append viewport mode (#200): Fixed preserves the viewport across
    # an append, Follow-Latest advances the bottom to the new tail depth. Head.
    add_executable(welllog_append_viewport_mode_tests
        tests/integration/append_viewport_mode_test.cpp
    )
    target_compile_features(welllog_append_viewport_mode_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_append_viewport_mode_tests)
    target_link_libraries(welllog_append_viewport_mode_tests PRIVATE WellLog::Session)
    add_test(NAME welllog.append-viewport-mode COMMAND welllog_append_viewport_mode_tests)

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

    add_executable(welllog_raster_tests
        tests/render_gl/raster_test.cpp
    )
    target_compile_features(welllog_raster_tests PRIVATE cxx_std_20)
    welllog_enable_warnings(welllog_raster_tests)
    target_include_directories(
        welllog_raster_tests
        PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src"
    )
    target_link_libraries(welllog_raster_tests PRIVATE WellLog::RenderGL)
    add_test(NAME welllog.render-raster COMMAND welllog_raster_tests)

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

        # Virtualized table-model adapter test (ADR 0022, #154). No GL needed
        # (a table model has no OpenGL) — runs under the minimal platform.
        qt_add_executable(welllog_qt_table_model_tests
            tests/qt/table_model_test.cpp
        )
        welllog_enable_warnings(welllog_qt_table_model_tests)
        target_link_libraries(
            welllog_qt_table_model_tests
            PRIVATE WellLog::QtWidgets Qt6::Test
        )
        add_test(NAME welllog.qt-table-model COMMAND welllog_qt_table_model_tests)
        set_tests_properties(
            welllog.qt-table-model
            PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=minimal"
        )

        # Bidirectional graphics↔table selection sync (ADR 0024, #154 Phase B).
        # No GL needed — a TableModel + headless session only.
        qt_add_executable(welllog_qt_table_selection_sync_tests
            tests/qt/table_selection_sync_test.cpp
        )
        welllog_enable_warnings(welllog_qt_table_selection_sync_tests)
        target_link_libraries(
            welllog_qt_table_selection_sync_tests
            PRIVATE WellLog::QtWidgets WellLog::Session WellLog::Table Qt6::Test
        )
        add_test(
            NAME welllog.qt-table-selection-sync
            COMMAND welllog_qt_table_selection_sync_tests
        )
        set_tests_properties(
            welllog.qt-table-selection-sync
            PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=minimal"
        )
    endif()
    if(WELLLOG_BUILD_PYTHON)
        add_test(
            NAME welllog.python.qt-embedding
            COMMAND
                "${CMAKE_COMMAND}" -E env
                "PYTHONPATH=${CMAKE_CURRENT_BINARY_DIR}/python"
                "QT_QPA_PLATFORM=minimal"
                "${Python_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tests/python/test_qt_embedding.py"
        )
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
