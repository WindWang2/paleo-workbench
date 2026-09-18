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
# BEGIN CONV-03
# CONV-03 (swarm task 03): contour/facies GeoJSON layer products live in
# libs/mapping_kernel (layer_products.*). This switch implies the
# mapping_kernel build so the slice can be configured/verified without
# editing any existing block.
option(PWB_BUILD_CONV_03
    "Build the CONV-03 layer-products slice (implies PWB_BUILD_MAPPING_KERNEL)"
    OFF)
if(PWB_BUILD_CONV_03 AND NOT PWB_BUILD_MAPPING_KERNEL)
    set(PWB_BUILD_MAPPING_KERNEL ON)
endif()
# END CONV-03
# BEGIN CONV-05
# constrained-IDW (Haiyou) kernel port with frozen Python oracle; implies the
# mapping_kernel library it extends.
option(PWB_BUILD_CONV_05
    "CONV-05: constrained-IDW kernel + oracle test (extends mapping_kernel)" OFF)
if(PWB_BUILD_CONV_05)
    set(PWB_BUILD_MAPPING_KERNEL ON)
endif()
# END CONV-05

if(PWB_BUILD_MAPPING_KERNEL)
    add_subdirectory(libs/mapping_kernel)
endif()

# BEGIN CONV-01
# Swarm task 01: wire the frozen mapping_kernel into the platform's
# 地质因子图 action (well points -> interpolate -> contour/facies
# QgsVectorLayers). Requires the kernel (numeric core) and the platform
# closure (MainWindow wiring); fail closed instead of building a stub.
option(PWB_BUILD_CONV_01
    "Build the CONV-01 map-pipeline slice (MainWindow geological factor map)" OFF)
if(PWB_BUILD_CONV_01)
    if(NOT PWB_BUILD_MAPPING_KERNEL)
        message(FATAL_ERROR
            "PWB_BUILD_CONV_01=ON requires PWB_BUILD_MAPPING_KERNEL=ON "
            "(the frozen kernel is the numeric core of the slice)")
    endif()
    if(NOT PWB_BUILD_PLATFORM)
        message(FATAL_ERROR
            "PWB_BUILD_CONV_01=ON requires PWB_BUILD_PLATFORM=ON "
            "(the slice wires MainWindow + QgsVectorLayer)")
    endif()
endif()
# END CONV-01
# BEGIN CONV-02
# Qt-free MapDocument / MapCompositionDocument JSON kernel (swarm
# cpp-conv-02): data-contract port of mapping/layers.py +
# mapping/composer/models.py, frozen against the Python oracle.
option(PWB_BUILD_CONV_02
    "Build the MapDocument/composition JSON kernel ported from the Python mapping document model" OFF)
if(PWB_BUILD_CONV_02)
    add_subdirectory(libs/mapping_document)
endif()
# END CONV-02
# BEGIN CONV-06
# WorkflowSpec DAG pure model + validator (M7 leaf; Qt-free, QGIS-free).
# Requires Pwb::Domain (ordered JSON + sha256) from PWB_BUILD_DATA=ON.
option(PWB_BUILD_CONV_06
    "Build the workflow_spec DAG model/validator ported from workflow/dag" OFF)
if(PWB_BUILD_CONV_06)
    add_subdirectory(libs/workflow_spec)
endif()
# END CONV-06

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

# BEGIN CONV-04
# Task 04 (feat/cpp-conv-04-ring-clip-repair): bounded ring clip and
# closure/orientation repair kernel slice without shapely. Option declared
# here for discoverability; -DPWB_BUILD_CONV_04=ON gates the additions in
# libs/mapping_kernel. Existing CONV blocks and targets are untouched.
option(PWB_BUILD_CONV_04 "Build CONV-04 ring_ops kernel slice" OFF)
# END CONV-04
