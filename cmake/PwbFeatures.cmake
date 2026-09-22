# PwbFeatures.cmake — declarative feature graph for the C++ migration.
#
# Purpose (branch: cpp-build-packaging-hardening — engineering hardening only,
# no business semantics change):
#
#   * declare every PWB_* switch *before* any add_subdirectory() consumes it, so
#     a slice can never be silently configured OFF because its option() was
#     declared further down the root CMakeLists.txt;
#   * record the implied/required edges between switches in one table instead of
#     scattering `set(X ON)` calls across 25 CONV blocks;
#   * validate the resolved graph (unknown switch, missing requirement, cycle)
#     and fail loudly rather than configuring a half-tree;
#   * print a feature summary so "what is actually on" is never guesswork.
#
# Every default matches the root CMakeLists.txt, so including this module with
# no -D flags resolves to the same graph as before; the later `option()` calls in
# the root file become no-ops because the cache entry already exists.
#
# Usage from the root CMakeLists.txt (once, before any add_subdirectory):
#   include(cmake/PwbFeatures.cmake)
#   pwb_resolve_feature_dependencies()
#   ... subdirectories ...
#   pwb_feature_summary()

include_guard(GLOBAL)

# Name list lives in directory scope (never in the cache, so reconfiguring does
# not append duplicates); per-feature properties live in the cache because they
# must survive into the summary call at the end of the root file.
if(NOT DEFINED PWB_FEATURE_NAMES)
    set(PWB_FEATURE_NAMES "")
endif()

function(pwb_feature_set_prop prop name value)
    set("PWB_FEAT_${prop}_${name}" "${value}" CACHE INTERNAL
        "PwbFeatures property ${prop} for ${name}")
endfunction()

function(pwb_feature_get_prop prop name out_var)
    set(${out_var} "${PWB_FEAT_${prop}_${name}}" PARENT_SCOPE)
endfunction()

# pwb_declare_feature(<NAME> <DOC> <DEFAULT> [IMPLIES a;b] [REQUIRES a;b])
#   IMPLIES  — turning NAME on turns these on as well (auto, logged).
#   REQUIRES — NAME=ON with any of these OFF is a configure error.
function(pwb_declare_feature name doc default)
    cmake_parse_arguments(PF "" "" "IMPLIES;REQUIRES" ${ARGN})

    option(${name} "${doc}" ${default})

    set(_names "${PWB_FEATURE_NAMES}")
    if(NOT name IN_LIST _names)
        list(APPEND _names "${name}")
        set(PWB_FEATURE_NAMES "${_names}" PARENT_SCOPE)
    else()
        set(PWB_FEATURE_NAMES "${_names}" PARENT_SCOPE)
    endif()

    pwb_feature_set_prop(DOC "${name}" "${doc}")
    pwb_feature_set_prop(DEFAULT "${name}" "${default}")
    pwb_feature_set_prop(IMPLIES "${name}" "${PF_IMPLIES}")
    pwb_feature_set_prop(REQUIRES "${name}" "${PF_REQUIRES}")

    pwb_feature_get_prop(REASON "${name}" _reason)
    if(NOT _reason)
        pwb_feature_set_prop(REASON "${name}" "declared")
    endif()
endfunction()

# --------------------------------------------------------------------------- #
# Declarations — hoisted ahead of every add_subdirectory()
# --------------------------------------------------------------------------- #

# Product lines
pwb_declare_feature(PWB_BUILD_PLATFORM
    "Build the CPP-A platform (QGIS app shell)" ON)
pwb_declare_feature(PWB_BUILD_DATA
    "Link the CPP-B data/project modules (fails when absent)" OFF)
pwb_declare_feature(PWB_BUILD_SCIENCE
    "Link the CPP-C algorithm/viz modules (fails when absent)" OFF)
pwb_declare_feature(PWB_BUILD_SEISMIC_VIEWER
    "Build the CPP-D seismic 2D viewer (fails when absent)" OFF
    IMPLIES PWB_BUILD_SEISMIC_ATTRIBUTES)
pwb_declare_feature(PWB_BUILD_SEISMIC_ATTRIBUTES
    "Build the CPP-E seismic attribute library (fails when absent)" OFF)
pwb_declare_feature(PWB_BUILD_SEISMIC_IO
    "Build the post-stack SEG-Y reader (libs/seismic_io)" OFF)
pwb_declare_feature(PWB_BUILD_SEISMIC_SERVICE
    "Build the native seismic volume service" OFF
    IMPLIES PWB_BUILD_SEISMIC_IO;PWB_BUILD_DATA)
pwb_declare_feature(PWB_BUILD_MAPPING_KERNEL
    "Build the contouring+interpolator kernel ported from the Python mapping pipeline" OFF)
pwb_declare_feature(PWB_BUILD_INTEGRATION_TESTS
    "Register tests/cpp/integration (requires platform+data+science)" OFF
    REQUIRES PWB_BUILD_PLATFORM;PWB_BUILD_DATA;PWB_BUILD_SCIENCE)

# Conversion slices
pwb_declare_feature(PWB_BUILD_CONV_01
    "CONV-01 MainWindow geological factor map wiring" OFF
    REQUIRES PWB_BUILD_MAPPING_KERNEL;PWB_BUILD_PLATFORM)
pwb_declare_feature(PWB_BUILD_CONV_02
    "CONV-02 MapDocument/composition JSON kernel" OFF)
pwb_declare_feature(PWB_BUILD_CONV_03
    "CONV-03 layer-products slice" OFF
    IMPLIES PWB_BUILD_MAPPING_KERNEL)
pwb_declare_feature(PWB_BUILD_CONV_04
    "CONV-04 ring_ops kernel slice (bounded ring clip + repair)" OFF
    IMPLIES PWB_BUILD_MAPPING_KERNEL)
pwb_declare_feature(PWB_BUILD_CONV_05
    "CONV-05 constrained-IDW kernel + oracle test" OFF
    IMPLIES PWB_BUILD_MAPPING_KERNEL)
pwb_declare_feature(PWB_BUILD_CONV_06
    "CONV-06 workflow_spec DAG model/validator" OFF)
pwb_declare_feature(PWB_BUILD_CONV_07
    "CONV-07 in-memory DAG workflow engine" OFF
    IMPLIES PWB_BUILD_MAPPING_KERNEL;PWB_BUILD_CONV_06)
# BEGIN CLOSURE-AGENT (line 11) — agent/harness closure core. Declares the
# provider SDK switch in the graph (the legacy CONV-PROVIDERS option block
# below restates the same implications) so the resolver can chain
# CLOSURE_AGENT -> PROVIDERS -> DATA + MAPPING_KERNEL + CONV-02 up front;
# the closure_agent subdirectory is added after CONV-07 so its optional
# workflow adapter can link Pwb::WorkflowEngine. Lease registered in
# codex-coordination 11-line.json.
pwb_declare_feature(PWB_BUILD_PROVIDERS
    "CONV-PROVIDERS native provider SDK + builtins" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_MAPPING_KERNEL;PWB_BUILD_CONV_02)
pwb_declare_feature(PWB_BUILD_CLOSURE_AGENT
    "CLOSURE-AGENT agent/harness closure core (libs/closure_agent)" OFF
    IMPLIES PWB_BUILD_PROVIDERS)
# END CLOSURE-AGENT
pwb_declare_feature(PWB_BUILD_CONV_08
    "CONV-08 factor interpolation task host" OFF)
pwb_declare_feature(PWB_BUILD_CONV_09
    "CONV-09 well_science DTW kernel" OFF)
# NOTE: PWB_BUILD_CONV_10 is NOT declared here. It is owned by
# libs/mapping_kernel/CMakeLists.txt, which declares it with the same default
# (OFF) and consumes it locally. Hoisting a subdirectory-owned switch duplicates
# the declaration and is exactly the hazard that flipped PWB_BUILD_TOOLS when
# this module was first written; it is reported read-only instead.
pwb_declare_feature(PWB_BUILD_CONV_11
    "CONV-11 well-curve ops kernel" OFF)
pwb_declare_feature(PWB_BUILD_CONV_12
    "CONV-12 geomodel volume/thickness/section kernels" OFF)
pwb_declare_feature(PWB_BUILD_CONV_13
    "CONV-13 tiled ONNX inference geometry" OFF)
pwb_declare_feature(PWB_BUILD_CONV_14
    "CONV-14 interchange path-safety/manifest/preflight kernel" OFF
    # libs/interchange's exporters hard-require the ingest readers and the
    # SEGY inspector (#1444) — keep the resolver's view in sync with the
    # build's actual requirements.
    IMPLIES PWB_BUILD_CONV_19;PWB_BUILD_SEISMIC_IO)
pwb_declare_feature(PWB_BUILD_CONV_16
    "CONV-16 factor statistics HUD cluster" OFF
    REQUIRES PWB_BUILD_MAPPING_KERNEL)
pwb_declare_feature(PWB_BUILD_CONV_17
    "CONV-17 geometry-units/CRS-contract leaves" OFF
    IMPLIES PWB_BUILD_MAPPING_KERNEL)
pwb_declare_feature(PWB_BUILD_CONV_18
    "CONV-18 factor-grid JSON envelope codec" OFF
    IMPLIES PWB_BUILD_MAPPING_KERNEL)
pwb_declare_feature(PWB_BUILD_CONV_19
    "CONV-19 ingest parser cores" OFF)
pwb_declare_feature(PWB_BUILD_CONV_20
    "CONV-20 optional pybind11 mapping_kernel facade" OFF
    REQUIRES PWB_BUILD_MAPPING_KERNEL)
pwb_declare_feature(PWB_BUILD_CONV_21
    "CONV-21 prediction contract cores" OFF
    IMPLIES PWB_BUILD_CONV_13;PWB_BUILD_CONV_14;PWB_BUILD_CONV_19)
pwb_declare_feature(PWB_BUILD_CONV_22
    "CONV-22 geomodel contract/export cores" OFF
    IMPLIES PWB_BUILD_CONV_12;PWB_BUILD_CONV_19)
pwb_declare_feature(PWB_BUILD_CONV_23
    "CONV-23 workflow contract layer" OFF
    IMPLIES PWB_BUILD_DATA)
pwb_declare_feature(PWB_BUILD_CONV_24
    "CONV-24 factor fusion kernels" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_CONV_08)
pwb_declare_feature(PWB_BUILD_CONV_25
    "CONV-25 workflow graph + evidence kernel" OFF
    IMPLIES PWB_BUILD_DATA)
pwb_declare_feature(PWB_BUILD_CONV_26
    "CONV-26 data lifecycle closure cores" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_CONV_19)
pwb_declare_feature(PWB_BUILD_CONV_26B
    "CONV-26B workflow runtime closure" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_MAPPING_KERNEL;PWB_BUILD_CONV_07;PWB_BUILD_CONV_08;PWB_BUILD_CONV_25)
pwb_declare_feature(PWB_BUILD_CONV_27
    "CONV-27 QGIS workbench UI closure" OFF
    REQUIRES PWB_BUILD_PLATFORM)
pwb_declare_feature(PWB_BUILD_CONV_27B
    "CONV-27b mapping document edit-session/snapshot/IO layer" OFF
    IMPLIES PWB_BUILD_CONV_02)
pwb_declare_feature(PWB_BUILD_CONV_27C
    "CONV-27c cartography style/template registry" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_CONV_02)
pwb_declare_feature(PWB_BUILD_CONV_28
    "CONV-28 native science service layer" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_MAPPING_KERNEL;PWB_BUILD_CONV_05;PWB_BUILD_CONV_17;PWB_BUILD_CONV_18;PWB_BUILD_CONV_08;PWB_BUILD_CONV_24;PWB_BUILD_CONV_09;PWB_BUILD_CONV_22)
pwb_declare_feature(PWB_BUILD_CONV_29
    "CONV-29 composer/layout/export C++ chain" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_PLATFORM;PWB_BUILD_CONV_02)
pwb_declare_feature(PWB_BUILD_CONV_30
    "CONV-30 async job runtime" ON
    IMPLIES PWB_BUILD_DATA)
pwb_declare_feature(PWB_BUILD_CONV_32
    "CONV-32 workflow interpretation core" OFF
    IMPLIES PWB_BUILD_CONV_25;PWB_BUILD_CONV_26B;PWB_BUILD_CONV_24)
pwb_declare_feature(PWB_BUILD_CONV_33
    "CONV-33 workflow orchestration surfaces" OFF
    IMPLIES PWB_BUILD_CONV_26B;PWB_BUILD_CONV_06)

# Product closure and product-adjacent lines. These declarations make the
# dependency graph resolve before any add_subdirectory() is evaluated.
pwb_declare_feature(PWB_BUILD_CPP_CLOSE_02
    "Build the workflow closure consumers" OFF
    IMPLIES PWB_BUILD_CONV_33;PWB_BUILD_CONV_32;PWB_BUILD_CONV_24;PWB_BUILD_CONV_30)
pwb_declare_feature(PWB_BUILD_CLOSURE_SCIENCE
    "Build the science/prediction product closure" OFF
    IMPLIES PWB_BUILD_CONV_28;PWB_BUILD_PREDICTION_RUNTIME)
pwb_declare_feature(PWB_BUILD_PREDICTION_RUNTIME
    "Build the native prediction runtime" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_CONV_21)
pwb_declare_feature(PWB_BUILD_GEO3D_VIZ
    "Build the native 3D geomodel viewer" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_CONV_22)
pwb_declare_feature(PWB_BUILD_VIZ_B
    "Build the cross-well correlation and well-tie visualization cores" ON)
pwb_declare_feature(PWB_BUILD_BENCH
    "Build the native benchmark tool" OFF
    IMPLIES PWB_BUILD_DATA;PWB_BUILD_CONV_13;PWB_BUILD_SEISMIC_IO)
pwb_declare_feature(PWB_BUILD_NATIVE_PRODUCT
    "Build the formal native C++ product closure" OFF
    IMPLIES
        PWB_BUILD_PLATFORM
        PWB_BUILD_DATA
        PWB_BUILD_SCIENCE
        PWB_BUILD_SEISMIC_VIEWER
        PWB_BUILD_SEISMIC_ATTRIBUTES
        PWB_BUILD_SEISMIC_IO
        PWB_BUILD_SEISMIC_SERVICE
        PWB_BUILD_MAPPING_KERNEL
        PWB_BUILD_CONV_01
        PWB_BUILD_CONV_07
        PWB_BUILD_CONV_16
        PWB_BUILD_CONV_26
        PWB_BUILD_CONV_26B
        PWB_BUILD_CONV_27
        PWB_BUILD_CONV_27B
        PWB_BUILD_CONV_27C
        PWB_BUILD_CONV_29
        PWB_BUILD_CONV_30
        PWB_BUILD_CONV_32
        PWB_BUILD_PROVIDERS
        PWB_BUILD_CLOSURE_SCIENCE
        PWB_BUILD_GEO3D_VIZ
        PWB_BUILD_VIZ_B)

# Switches owned by a *subdirectory* (they are consumed only inside the library
# that declares them, so root ordering cannot bite). They must NOT be re-declared
# here: `option()` never overwrites an existing cache entry, so hoisting them
# with a guessed default would silently flip the real default (PWB_BUILD_TOOLS
# and the science/seismic test switches default to ON where they live). They are
# listed for reporting only, and the summary reads their resolved value.
set(PWB_FEATURE_REPORT_ONLY
    "PWB_BUILD_TOOLS"
    "PWB_BUILD_CONV_10"
    "PWB_SCIENCE_BUILD_TESTS"
    "PWB_SCIENCE_BUILD_VIEWER"
    "PWB_SCIENCE_VIEWER_TESTS"
    "PWB_SCIENCE_VIEWER_EXAMPLE"
    "PWB_SEISMIC_ATTRIBUTES_BUILD_TESTS"
    "PWB_SEISMIC_VIEWER_BUILD_TESTS"
    CACHE INTERNAL "subdirectory-owned switches shown in the feature summary")

# Packaging (branch cpp-build-packaging-hardening): opt-in native install/
# package skeleton. OFF by default so the other six worktrees keep their
# build graphs byte-for-byte identical; cmake/PwbInstall.cmake registers zero
# install rules unless this is explicitly turned on.
pwb_declare_feature(PWB_ENABLE_PACKAGING
    "Install/package the native product (opt-in, OFF by default)" OFF)

# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

function(pwb_apply_implications feature)
    pwb_feature_get_prop(IMPLIES "${feature}" _implies)
    foreach(dep IN LISTS _implies)
        if(NOT ${dep})
            set(${dep} ON CACHE BOOL "implied by ${feature}" FORCE)
            pwb_feature_set_prop(REASON "${dep}" "implied-by:${feature}")
            message(STATUS "PwbFeatures: ${feature}=ON implies ${dep}=ON")
        endif()
    endforeach()
endfunction()

# pwb_resolve_feature_dependencies()
#   Bounded fixpoint expansion of IMPLIES edges (so a malformed table can never
#   hang configuration), then validation of every REQUIRES edge.
function(pwb_resolve_feature_dependencies)
    set(_max_rounds 16)
    set(_round 0)
    set(_stabilised FALSE)
    while(_round LESS _max_rounds)
        math(EXPR _round "${_round} + 1")
        set(_changed FALSE)
        foreach(feature IN LISTS PWB_FEATURE_NAMES)
            if(${feature})
                pwb_feature_get_prop(IMPLIES "${feature}" _implies)
                foreach(dep IN LISTS _implies)
                    if(NOT ${dep})
                        set(_changed TRUE)
                    endif()
                endforeach()
                pwb_apply_implications(${feature})
            endif()
        endforeach()
        if(NOT _changed)
            set(_stabilised TRUE)
            break()
        endif()
    endwhile()

    if(NOT _stabilised)
        message(FATAL_ERROR
            "PwbFeatures: the implication graph did not stabilise within "
            "${_max_rounds} rounds. Either there is a cycle in the IMPLIES table "
            "in cmake/PwbFeatures.cmake, or an implication chain is deeper than "
            "${_max_rounds}; raise _max_rounds only after checking for a cycle.")
    endif()

    # Unknown switches on either edge type are typos that would otherwise make
    # the edge silently do nothing.
    foreach(feature IN LISTS PWB_FEATURE_NAMES)
        pwb_feature_get_prop(IMPLIES "${feature}" _implies)
        pwb_feature_get_prop(REQUIRES "${feature}" _requires)
        foreach(dep IN LISTS _implies)
            if(NOT dep IN_LIST PWB_FEATURE_NAMES)
                message(FATAL_ERROR
                    "PwbFeatures: ${feature} implies unknown switch ${dep}")
            endif()
        endforeach()
        foreach(dep IN LISTS _requires)
            if(NOT dep IN_LIST PWB_FEATURE_NAMES)
                message(FATAL_ERROR
                    "PwbFeatures: ${feature} requires unknown switch ${dep}")
            endif()
        endforeach()
    endforeach()

    foreach(feature IN LISTS PWB_FEATURE_NAMES)
        if(NOT ${feature})
            continue()
        endif()
        pwb_feature_get_prop(REQUIRES "${feature}" _requires)
        foreach(dep IN LISTS _requires)
            if(NOT ${dep})
                message(FATAL_ERROR
                    "PwbFeatures: ${feature}=ON requires ${dep}=ON but ${dep} is "
                    "OFF. Enable it explicitly (or let the implication table do "
                    "it) instead of building a substitute.")
            endif()
        endforeach()
    endforeach()
endfunction()

# --------------------------------------------------------------------------- #
# Guards and reporting
# --------------------------------------------------------------------------- #

# pwb_add_subdirectory_once(<dir>) — idempotent add_subdirectory().
# libs/well_science is reached from two CONV slices (09 and 11); without this
# guard the second add_subdirectory() re-enters the directory and redefines the
# same targets.
function(pwb_add_subdirectory_once dir)
    string(MAKE_C_IDENTIFIER "${dir}" _key)
    string(TOUPPER "${_key}" _key)
    if(PWB_SUBDIR_ADDED_${_key})
        message(STATUS "PwbFeatures: ${dir} already added; skipping duplicate")
        return()
    endif()
    # Deliberately NOT a cache entry: a cached guard would survive across
    # reconfigures, so switching the owning slices off and on again in the same
    # build tree would skip the directory and silently build nothing.
    # Directory-scope is exactly the right lifetime for "within this configure".
    set(PWB_SUBDIR_ADDED_${_key} TRUE PARENT_SCOPE)
    add_subdirectory(${dir})
endfunction()

# pwb_feature_summary() — print the resolved graph (ON switches + why).
function(pwb_feature_summary)
    string(REPEAT "-" 76 _rule)
    message(STATUS "${_rule}")
    message(STATUS "PwbFeatures — resolved feature graph")
    message(STATUS "${_rule}")
    set(_off 0)
    foreach(feature IN LISTS PWB_FEATURE_NAMES)
        if(${feature})
            pwb_feature_get_prop(REASON "${feature}" _reason)
            message(STATUS "  ON   ${feature}  [${_reason}]")
        else()
            math(EXPR _off "${_off} + 1")
        endif()
    endforeach()
    message(STATUS "  (${_off} switch(es) OFF; reconfigure with "
                   "-DPWB_FEATURE_VERBOSE=1 for the full list)")
    if(PWB_FEATURE_VERBOSE)
        foreach(feature IN LISTS PWB_FEATURE_NAMES)
            if(NOT ${feature})
                message(STATUS "  off  ${feature}")
            endif()
        endforeach()
    endif()

    # Subdirectory-owned switches: shown so nobody has to grep for them, but
    # reported as they resolved rather than as this module might have declared.
    set(_lines "")
    foreach(feature IN LISTS PWB_FEATURE_REPORT_ONLY)
        if(DEFINED ${feature})
            list(APPEND _lines "  ${feature} = ${${feature}}  [subdirectory-owned]")
        else()
            list(APPEND _lines
                "  ${feature} = <unset: owning subdirectory not configured>")
        endif()
    endforeach()
    if(_lines)
        message(STATUS "PwbFeatures — subdirectory-owned switches")
        foreach(line IN LISTS _lines)
            message(STATUS "${line}")
        endforeach()
    endif()
    message(STATUS "${_rule}")
endfunction()
