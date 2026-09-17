# Shared admission: see scripts/cpp-migration/Invoke-ResourceGate.ps1 and its
# POSIX port invoke-resource-gate.sh (2 jobs, >=8 GiB free RAM, one heavy
# slot across the migration worktrees).
cmake_minimum_required(VERSION 3.27)

project(paleo_workbench_cpp
    VERSION 0.1.0
    DESCRIPTION "Paleo Workbench C++20/Qt/QGIS platform (CPP-A track)"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
    # Sources carry Chinese reason strings and comments: force UTF-8 parsing.
    add_compile_options(/utf-8 /EHsc /W3 /bigobj)
endif()

# ---------------------------------------------------------------- options ----
option(PWB_BUILD_PLATFORM "Build the CPP-A platform (QGIS app shell)" ON)
option(PWB_BUILD_DATA "Link the CPP-B data/project modules (fails when absent)" OFF)
option(PWB_BUILD_SCIENCE "Link the CPP-C algorithm/viz modules (fails when absent)" OFF)
option(PWB_BUILD_SEISMIC_VIEWER
    "Build the CPP-D seismic 2D viewer (fails when absent)" OFF)
option(PWB_BUILD_SEISMIC_ATTRIBUTES
    "Build the CPP-E seismic attribute library (fails when absent)" OFF)
option(PWB_BUILD_SEISMIC_IO
    "Build the post-stack SEG-Y reader (libs/seismic_io)" OFF)
option(PWB_BUILD_MAPPING_KERNEL
    "Build the contouring+interpolator kernel ported from the Python mapping pipeline" OFF)
option(PWB_BUILD_INTEGRATION_TESTS
    "Register tests/cpp/integration (requires platform+data+science)" OFF)
include(CTest)

# ------------------------------------------------- B/C integration switches --
# ON must mean the module is really there; a missing module is a configure
# error, never a silent skip (protocol: independent validation).
if(PWB_BUILD_DATA)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/data_suite/CMakeLists.txt")
        message(FATAL_ERROR "PWB_BUILD_DATA=ON but libs/data_suite is not merged on this branch")
    endif()
    add_subdirectory(libs/data_suite)
endif()
if(PWB_BUILD_SCIENCE)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/science_suite/CMakeLists.txt")
        message(FATAL_ERROR "PWB_BUILD_SCIENCE=ON but libs/science_suite is not merged on this branch")
    endif()
    add_subdirectory(libs/science_suite)
endif()

# ---------------------------------------------------- D/E fail-closed gates --
# D (libs/seismic_viewer) and E (libs/seismic_attributes) are separate
# lines; until their owners deliver, the switches exist but cannot be ON.
if(PWB_BUILD_SEISMIC_VIEWER)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/seismic_viewer/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_SEISMIC_VIEWER=ON but libs/seismic_viewer is not "
            "delivered on this branch (CPP-D line). A test double must never "
            "stand in for the production viewer.")
    endif()
    add_subdirectory(libs/seismic_viewer)
endif()
if(PWB_BUILD_SEISMIC_ATTRIBUTES)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/seismic_attributes/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_SEISMIC_ATTRIBUTES=ON but libs/seismic_attributes is "
            "not delivered on this branch (CPP-E line). Kernels are NOT "
            "duplicated into the platform.")
    endif()
    add_subdirectory(libs/seismic_attributes)
endif()
if(PWB_BUILD_SEISMIC_IO)
    add_subdirectory(libs/seismic_io)
    if(BUILD_TESTING)
        add_subdirectory(libs/seismic_io/seismic_io_tests)
    endif()
endif()
if(PWB_BUILD_MAPPING_KERNEL)
    add_subdirectory(libs/mapping_kernel)
endif()

# The integrated configuration is all-or-nothing by definition: the app's
# real link closure must contain B and C, and the integration tests prove
# it (no substitutes). Fail loudly when the combo is impossible.
if(PWB_BUILD_INTEGRATION_TESTS)
    foreach(_required PWB_BUILD_PLATFORM PWB_BUILD_DATA PWB_BUILD_SCIENCE)
        if(NOT ${_required})
            message(FATAL_ERROR
                "PWB_BUILD_INTEGRATION_TESTS=ON requires ${_required}=ON "
                "(integrated closure, no substitutes)")
        endif()
    endforeach()
endif()

if(PWB_BUILD_PLATFORM)
    include(cmake/PwbQgisSdk.cmake)
    add_subdirectory(libs/tool_policy)
    add_subdirectory(libs/qgis)
    add_subdirectory(libs/application)
    add_subdirectory(libs/ui)
    add_subdirectory(apps/paleo_workbench_platform)
    if(BUILD_TESTING)
        enable_testing()
        add_subdirectory(tests/cpp/platform)
        if(PWB_BUILD_INTEGRATION_TESTS
           AND TARGET Pwb::Data AND TARGET Pwb::Science)
            add_subdirectory(tests/cpp/integration)
        endif()
    endif()
endif()

# BEGIN CONV-16
# conv-16 UI panel cluster, first slice: the read-only factor statistics HUD
# (apps/paleo_workbench_platform/factor_stats_dock.*) and its ctest target.
# The dock is a Qt Widgets HUD over pwb::mapping::GridStatistics — no QGIS —
# so the test exists in the same PLATFORM=OFF configuration the conversion
# gates use here (single definition; the app binary wires the dock through
# its CONV-16 block in apps/paleo_workbench_platform/CMakeLists.txt when the
# platform is built).
option(PWB_BUILD_CONV_16 "Build conv-16 factor statistics HUD cluster" OFF)
if(PWB_BUILD_CONV_16)
    if(NOT TARGET Pwb::MappingKernel)
        message(FATAL_ERROR "PWB_BUILD_CONV_16=ON requires PWB_BUILD_MAPPING_KERNEL=ON")
    endif()
    find_package(Qt6 6.8 REQUIRED COMPONENTS Widgets)
    if(BUILD_TESTING AND NOT TARGET platform_factor_hud)
        add_executable(platform_factor_hud
            tests/cpp/platform/factor_hud_test.cpp
            apps/paleo_workbench_platform/factor_stats_dock.cpp)
        set_target_properties(platform_factor_hud PROPERTIES AUTOMOC ON)
        target_compile_features(platform_factor_hud PRIVATE cxx_std_20)
        target_include_directories(platform_factor_hud PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/apps/paleo_workbench_platform)
        target_link_libraries(platform_factor_hud PRIVATE
            Qt6::Widgets Pwb::MappingKernel)
        target_compile_definitions(platform_factor_hud PRIVATE
            PWB_FACTOR_HUD_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/tests/cpp/platform/fixtures/factor_hud/oracle.json")
        add_test(NAME platform.factor_hud COMMAND platform_factor_hud)
        set_tests_properties(platform.factor_hud PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
            TIMEOUT 120)
    endif()
endif()
# END CONV-16
