# data_suite — the standalone build entry for the CPP-B data kernel.
#
#   cmake -S libs/data_suite -B build/cpp-data -DBUILD_TESTING=ON
#
# Produces Pwb::Domain / Pwb::Project / Pwb::Workspace / Pwb::Catalog /
# Pwb::Data plus the pwb-inspect / pwb-migrate tools and the data.* tests.
cmake_minimum_required(VERSION 3.24)
project(PwbDataSuite LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(PWB_DATA_SUITE_ROOT ON CACHE INTERNAL "marks the standalone entry")
set(PWB_VENDOR_DIR_DEFAULT "${CMAKE_CURRENT_SOURCE_DIR}/third_party")

option(BUILD_TESTING "Build tests" ON)
option(PWB_BUILD_TOOLS "Build pwb-inspect / pwb-migrate" ON)

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/third_party)

# Target guards: when data_suite is reached from the root build (e.g.
# PWB_BUILD_NATIVE_PRODUCT + PWB_BUILD_CONV_22 both pull the data kernels)
# domain/project may already be defined by an earlier once-guarded add —
# skip our own instead of colliding on CMP0002 (same idiom as
# geo3d_viz/seismic_io/seismic_viewer).
if(NOT TARGET Pwb::Domain)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../domain
                     ${CMAKE_CURRENT_BINARY_DIR}/domain)
endif()
if(NOT TARGET Pwb::Project)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../project
                     ${CMAKE_CURRENT_BINARY_DIR}/project)
endif()
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../workspace
                 ${CMAKE_CURRENT_BINARY_DIR}/workspace)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../catalog
                 ${CMAKE_CURRENT_BINARY_DIR}/catalog)
# CONV-26: the ingest orchestration reuses the CONV-19 classifier tables
# (classify_import_path / preferred extensions) instead of duplicating them.
# Guarded so an integrated build that already added libs/ingest (root
# PWB_BUILD_CONV_19 block) does not double-add it.
if(BUILD_TESTING)
    # Must precede the ingest add below or its ingest.parsers test does not
    # register (enable_testing covers subdirectories added after the call).
    enable_testing()
endif()
if(NOT TARGET pwb_ingest)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../ingest
                     ${CMAKE_CURRENT_BINARY_DIR}/ingest)
endif()

add_library(pwb_data STATIC
    src/commit_coordinator.cpp
    src/facade.cpp
    src/run_coordinator.cpp
    src/session.cpp
)
add_library(Pwb::Data ALIAS pwb_data)
target_compile_features(pwb_data PUBLIC cxx_std_20)
target_link_libraries(pwb_data
    PUBLIC Pwb::Domain Pwb::Project Pwb::Workspace Pwb::Catalog
    PRIVATE Pwb::Ingest)  # implementation detail (classifier tables)
target_include_directories(pwb_data
    PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
           $<INSTALL_INTERFACE:include>)
target_compile_definitions(pwb_data PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
if(MSVC)
    target_compile_options(pwb_data PRIVATE /utf-8 /W4 /permissive-)
endif()

install(TARGETS pwb_data EXPORT PwbDataTargets ARCHIVE DESTINATION lib)
install(DIRECTORY include/pwb DESTINATION include)

if(PWB_BUILD_TOOLS)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tools/pwb-inspect
                     ${CMAKE_CURRENT_BINARY_DIR}/tools/pwb-inspect)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tools/pwb-migrate
                     ${CMAKE_CURRENT_BINARY_DIR}/tools/pwb-migrate)
endif()

# A-line consumption example (v3-contracts.md §9): the production-library
# loop A drives — open, base version, staged edit, run register, publish,
# close/reopen.
add_executable(pwb-data-loop examples/data_consumer_example.cpp)
target_compile_features(pwb-data-loop PRIVATE cxx_std_20)
target_link_libraries(pwb-data-loop PRIVATE Pwb::Data)
if(MSVC)
    target_compile_options(pwb-data-loop PRIVATE /utf-8 /W4 /permissive-)
endif()

# BEGIN CONV-26
# Ingest orchestration + entity identity resolution + save-as flow: new
# TUs only.
target_sources(pwb_data PRIVATE
    src/entity_identity.cpp
    src/ingest_plan.cpp
    src/ingest_exec.cpp
    src/save_as.cpp
)
# END CONV-26

# BEGIN PWB-V14-DATA-LINEAGE
# Role registry (project/roles.py parity), entity domain ops + link ordinal
# (entity_identity extension) and the entity workspace read model
# (catalog/entity_views.py parity).
target_sources(pwb_data PRIVATE
    src/role_registry.cpp
    src/entity_workspace.cpp
    src/lifecycle_enforcement.cpp
)
# END PWB-V14-DATA-LINEAGE

if(BUILD_TESTING)
    enable_testing()
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/data
                     ${CMAKE_CURRENT_BINARY_DIR}/tests/cpp/data)
endif()
