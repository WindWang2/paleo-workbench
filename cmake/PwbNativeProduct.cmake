# PwbNativeProduct.cmake — the native C++ product closure.
#
# The product closure is the composition contract of the Paleo Workbench
# native entry (pwb-platform): one configure switch that pulls in every
# stable C++ module the product actually links, fails closed when a hard
# dependency is absent, probes optional capabilities instead of silently
# dropping them, and reports the resulting link closure as a capability
# summary (configure output) plus a generated compile-time capability table
# consumed by `pwb-platform --capabilities`.
#
# Included unconditionally from the root CMakeLists (defines the capability
# vocabulary and the helpers); used in three roles:
#   pwb_native_product_imply()               — root, right after the option
#       block when PWB_BUILD_NATIVE_PRODUCT=ON: turns the implied
#       PWB_BUILD_* switches ON before any add_subdirectory observes them;
#   pwb_native_product_generate_capabilities() — apps/paleo_workbench_platform
#       (any configuration): emits generated/pwb/app/product_capabilities.hpp
#       reflecting THIS build's switches/targets and exports
#       PWB_GENERATED_INCLUDE_DIR for the targets that compile app sources;
#   pwb_native_product_summary()             — root, at the end of the
#       configure when PWB_BUILD_NATIVE_PRODUCT=ON: validates the hard
#       closure (fail-closed), prints the capability/link-closure summary
#       and wires the install skeleton.
#
# Hard closure (all-or-nothing; these are the modules the product binary
# already links in the integrated gate — never an experimental slice):
#   PLATFORM (QGIS shell) + DATA + SCIENCE + SEISMIC D/E/IO + MAPPING_KERNEL
#   + CONV-01 (地质因子图 pipeline) + CONV-07 (DAG workflow engine)
#   + CONV-16 (factor statistics HUD).
# Optional capabilities are probed and reported, never forced: the WLE
# well-log viewer adapter (needs the WLE SDK) is the only link-time
# optional today; kernel-only modules (prediction/geomodel/…) are reported
# by id without entering the link closure.

# ---- capability vocabulary ------------------------------------------------
# id|title-for-humans|cmake-probe|class
#   class hard     — required by the product closure (fail-closed at summary)
#   class optional — probed; wired into the app when present
#   class kernel   — merged kernel, NOT wired into the product yet (honest
#                    readiness reporting only; never a product dependency)
set(PWB_NATIVE_PRODUCT_CAPABILITIES
    "qgis_platform|QGIS 平台壳 QgsApplication+canvas+图层树|PWB_BUILD_PLATFORM|hard"
    "data_integration|工程/目录数据闭包 Pwb::Data|PWB_BUILD_DATA|hard"
    "science_kernels|科学计算内核 Pwb::Science/Workflow|PWB_BUILD_SCIENCE|hard"
    "seismic_viewer|地震切片视图 dock|PWB_BUILD_SEISMIC_VIEWER|hard"
    "seismic_attributes|地震属性内核|PWB_BUILD_SEISMIC_ATTRIBUTES|hard"
    "seismic_io|SEG-Y 读取/导入|PWB_BUILD_SEISMIC_IO|hard"
    "mapping_kernel|编图数值内核 插值/等值线/栅格分类|PWB_BUILD_MAPPING_KERNEL|hard"
    "factor_map_pipeline|地质因子图产品链 CONV-01|PWB_BUILD_CONV_01|hard"
    "workflow_engine|最小 DAG 工作流引擎 CONV-07|PWB_BUILD_CONV_07|hard"
    "factor_stats_hud|因子统计 HUD CONV-16|PWB_BUILD_CONV_16|hard"
    "well_log_viewer|WLE 测井 dock|Pwb::VisualizationWellLog|optional"
    "prediction_kernel|岩相预测内核 仅内核未接线|Pwb::Prediction|kernel"
    "geomodel_kernel|地质建模内核 仅内核未接线|Pwb::Geomodel|kernel"
    "well_science_kernel|井科学对比内核 仅内核未接线|Pwb::WellScience|kernel"
    "factor_fusion_kernel|因子融合内核 仅内核未接线|Pwb::FactorFusion|kernel"
    "ingest_kernel|资源解析内核 仅内核未接线|Pwb::Ingest|kernel"
    "interchange_kernel|交换/清单内核 仅内核未接线|Pwb::Interchange|kernel"
    "workflow_contracts_kernel|工作流契约内核 仅内核未接线|Pwb::WorkflowContracts|kernel"
)

function(pwb_native_product_imply)
    foreach(_cap IN LISTS PWB_NATIVE_PRODUCT_CAPABILITIES)
        string(REPLACE "|" ";" _fields "${_cap}")
        list(GET _fields 2 _probe)
        list(GET _fields 3 _class)
        if(NOT _class STREQUAL "hard")
            continue()
        endif()
        # Hard switches are plain PWB_BUILD_* options; TARGET probes cannot
        # be implied and are validated at summary time instead.
        if(NOT _probe MATCHES "^PWB_BUILD_")
            message(FATAL_ERROR
                "PwbNativeProduct: hard capability probe '${_probe}' must be a "
                "PWB_BUILD_* switch (internal consistency)")
        endif()
        if(NOT ${_probe})
            # Local view feeds the capability rows below; PARENT_SCOPE feeds
            # the later add_subdirectory blocks (both matter — the CONV-01/
            # CONV-16 options are declared later in the root file and would
            # otherwise default OFF inside this function).
            set(${_probe} ON)
            set(${_probe} ON PARENT_SCOPE)
            message(STATUS "native-product: implying ${_probe}=ON")
        endif()
    endforeach()
    # The integrated battery proves the closure end to end; the product
    # configuration carries it by default (fail-closed, same as the gate).
    if(NOT PWB_BUILD_INTEGRATION_TESTS AND BUILD_TESTING)
        set(PWB_BUILD_INTEGRATION_TESTS ON PARENT_SCOPE)
        message(STATUS "native-product: implying PWB_BUILD_INTEGRATION_TESTS=ON")
    endif()
endfunction()

# Emits ${CMAKE_BINARY_DIR}/generated/pwb/app/product_capabilities.hpp and
# exports PWB_GENERATED_INCLUDE_DIR in the caller's scope. Call from the
# app's CMakeLists (any configuration): switch entries reflect this build's
# PWB_BUILD_* values, TARGET probes resolve at generate time via
# $<TARGET_EXISTS> so the header is emitted before the targets exist and
# still mirrors the final link closure.
function(pwb_native_product_generate_capabilities)
    set(_rows "")
    foreach(_cap IN LISTS PWB_NATIVE_PRODUCT_CAPABILITIES)
        string(REPLACE "|" ";" _fields "${_cap}")
        list(GET _fields 0 _id)
        list(GET _fields 1 _title)
        list(GET _fields 2 _probe)
        list(GET _fields 3 _class)
        if(_probe MATCHES "^PWB_BUILD_")
            if(${_probe})
                set(_available true)
            else()
                set(_available false)
            endif()
        else()
            set(_available "$<IF:$<TARGET_EXISTS:${_probe}>,true,false>")
        endif()
        string(APPEND _rows
            "    {\"${_id}\", \"${_title}\", BuildClass::${_class}, ${_available}},\n")
    endforeach()
    set(_header_dir "${CMAKE_BINARY_DIR}/generated/pwb/app")
    file(GENERATE OUTPUT "${_header_dir}/product_capabilities.hpp" CONTENT
"// GENERATED by cmake/PwbNativeProduct.cmake — do not edit.
//
// Compile-time truth of this build tree's C++ product closure.
// \`pwb-platform --capabilities\` layers runtime probes on top of this
// table; the platform.capabilities ctest asserts both stay in sync with
// the configure-time summary.

#pragma once

#include <cstddef>

namespace pwb::app::capabilities {

enum class BuildClass : unsigned char {
    hard,      // required by the product closure (fail-closed at configure)
    optional,  // probed; wired when the module is in the build
    kernel,    // merged kernel, not yet wired into the product entry
};

struct BuildCapability {
    const char* id;
    const char* title;
    BuildClass cls;
    bool in_closure;
};

inline constexpr BuildCapability kBuildCapabilities[] = {
${_rows}};

inline constexpr std::size_t kBuildCapabilityCount =
    sizeof(kBuildCapabilities) / sizeof(kBuildCapabilities[0]);

}  // namespace pwb::app::capabilities
")
    set(PWB_GENERATED_INCLUDE_DIR "${CMAKE_BINARY_DIR}/generated" PARENT_SCOPE)
endfunction()

function(pwb_native_product_summary)
    # 1) Fail closed: every hard capability must be real in this build.
    set(_missing)
    foreach(_cap IN LISTS PWB_NATIVE_PRODUCT_CAPABILITIES)
        string(REPLACE "|" ";" _fields "${_cap}")
        list(GET _fields 0 _id)
        list(GET _fields 2 _probe)
        list(GET _fields 3 _class)
        if(NOT _class STREQUAL "hard")
            continue()
        endif()
        if(_probe MATCHES "^PWB_BUILD_")
            if(NOT ${_probe})
                list(APPEND _missing "${_id} (${_probe}=OFF)")
            endif()
        elseif(NOT TARGET ${_probe})
            list(APPEND _missing "${_id} (target ${_probe} absent)")
        endif()
    endforeach()
    if(_missing)
        list(JOIN _missing "\n  " _joined)
        message(FATAL_ERROR
            "PWB_BUILD_NATIVE_PRODUCT=ON but the hard product closure is "
            "incomplete:\n  ${_joined}\nA product configure never silently "
            "ships without these modules (fail-closed).")
    endif()

    # 2) Human-readable closure summary (configure log).
    message(STATUS "native-product closure:")
    foreach(_cap IN LISTS PWB_NATIVE_PRODUCT_CAPABILITIES)
        string(REPLACE "|" ";" _fields "${_cap}")
        list(GET _fields 0 _id)
        list(GET _fields 1 _title)
        list(GET _fields 2 _probe)
        list(GET _fields 3 _class)
        if(_probe MATCHES "^PWB_BUILD_")
            if(${_probe})
                set(_state "on")
            else()
                set(_state "off")
            endif()
        elseif(TARGET ${_probe})
            set(_state "linked")
        else()
            set(_state "probed-absent")
        endif()
        message(STATUS "  [${_class}] ${_id}: ${_state} — ${_title}")
    endforeach()

    # 3) Install skeleton: the executable plus the generated capability
    #    header. The runtime closure (Qt/QGIS/geo SOs, plugins, proj/gdal
    #    data) is assembled by scripts/cpp-migration/deploy-native-product.sh,
    #    which also smoke-verifies the deployed tree with --self-check.
    install(TARGETS pwb-platform RUNTIME DESTINATION bin)
    install(FILES "${CMAKE_BINARY_DIR}/generated/pwb/app/product_capabilities.hpp"
            DESTINATION include/pwb/app)
endfunction()
