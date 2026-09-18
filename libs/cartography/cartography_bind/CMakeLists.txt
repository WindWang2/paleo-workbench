# CONV-27: optional pybind11 facade `pwb_cartography` over the Qt-free
# cartography registries (Pwb::Cartography), consumed by the thin
# try/except facade paleo_workbench/mapping/cartography_native.py.
# OFF by default; never part of the integrated gate (same discipline as
# CONV-20). pybind11 headers (BSD-3) are vendored by CONV-20 at
# libs/mapping_bind/_vendor/pybind11 — reused, not duplicated.
option(PWB_BUILD_CONV_27_BIND
    "Build the optional pybind11 cartography facade (requires CONV-27 + Python dev headers)" OFF)

if(PWB_BUILD_CONV_27_BIND)
    find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

    set(PYBIND11_INCLUDE_DIR
        "${CMAKE_CURRENT_SOURCE_DIR}/../mapping_bind/_vendor/pybind11/include"
        CACHE PATH "pybind11 headers (vendored for CONV-20)")
    if(NOT EXISTS "${PYBIND11_INCLUDE_DIR}/pybind11/pybind11.h")
        message(FATAL_ERROR
            "pybind11 headers not found at ${PYBIND11_INCLUDE_DIR} "
            "(vendored under libs/mapping_bind/_vendor/pybind11/include)")
    endif()

    # The static libs were created without PIC; linking them into a MODULE
    # .so requires PIC objects (same build-system-only change as CONV-20
    # decision D15 — no library source is touched).
    set_property(TARGET pwb_cartography PROPERTY POSITION_INDEPENDENT_CODE ON)
    if(TARGET pwb_mapping_document)
        set_property(TARGET pwb_mapping_document
            PROPERTY POSITION_INDEPENDENT_CODE ON)
    endif()
    if(TARGET pwb_domain)
        set_property(TARGET pwb_domain PROPERTY POSITION_INDEPENDENT_CODE ON)
    endif()

    Python3_add_library(cartography_bind_module MODULE WITH_SOABI
        "${CMAKE_CURRENT_SOURCE_DIR}/cartography_bind/cartography_bind.cpp")
    set_target_properties(cartography_bind_module PROPERTIES
        OUTPUT_NAME pwb_cartography)
    target_include_directories(cartography_bind_module PRIVATE
        "${PYBIND11_INCLUDE_DIR}")
    target_compile_features(cartography_bind_module PRIVATE cxx_std_20)
    target_compile_definitions(cartography_bind_module PRIVATE
        PWB_CARTOGRAPHY_BIND_VERSION="${PWB_CARTOGRAPHY_BIND_VERSION}")
    target_link_libraries(cartography_bind_module PRIVATE
        Pwb::Cartography Pwb::MappingDocument)
endif()
