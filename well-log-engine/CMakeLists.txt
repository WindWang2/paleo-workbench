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

include(CTest)
include(CMakePackageConfigHelpers)
include(GNUInstallDirs)

option(WELLLOG_BUILD_TESTS "Build WellLogEngine tests" ${BUILD_TESTING})
option(WELLLOG_BUILD_SHARED "Build WellLogEngine shared libraries" OFF)
option(WELLLOG_WARNINGS_AS_ERRORS "Treat WellLogEngine warnings as errors" OFF)

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
target_link_libraries(welllog_session PUBLIC WellLog::Core)
target_include_directories(welllog_session
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
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

install(
    TARGETS welllog_core welllog_session welllog_io
    EXPORT WellLogTargets
    RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
    LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
    INCLUDES DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}"
)
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
        NAME welllog.core.dependency-boundary
        COMMAND
            "${CMAKE_COMMAND}"
            "-DCORE_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/include/welllog/core"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/cmake/check_core_boundary.cmake"
    )
endif()
