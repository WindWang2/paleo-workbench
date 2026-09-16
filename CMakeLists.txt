# Shared admission: see scripts/cpp-migration/Invoke-ResourceGate.ps1 (2 jobs,
# >=8 GiB free RAM, one heavy slot across the three migration worktrees).
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
    endif()
endif()
