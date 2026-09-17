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

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../domain
                 ${CMAKE_CURRENT_BINARY_DIR}/domain)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../project
                 ${CMAKE_CURRENT_BINARY_DIR}/project)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../workspace
                 ${CMAKE_CURRENT_BINARY_DIR}/workspace)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../catalog
                 ${CMAKE_CURRENT_BINARY_DIR}/catalog)

add_library(pwb_data STATIC
    src/commit_coordinator.cpp
    src/facade.cpp
    src/run_coordinator.cpp
    src/session.cpp
)
add_library(Pwb::Data ALIAS pwb_data)
target_compile_features(pwb_data PUBLIC cxx_std_20)
target_link_libraries(pwb_data
    PUBLIC Pwb::Domain Pwb::Project Pwb::Workspace Pwb::Catalog)
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

if(BUILD_TESTING)
    enable_testing()
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/data
                     ${CMAKE_CURRENT_BINARY_DIR}/tests/cpp/data)
endif()
