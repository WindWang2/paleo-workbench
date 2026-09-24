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
    # math constants (M_PI and friends) are guarded behind this feature
    # macro on MSVC; the Linux builds get them from glibc's math.h by
    # default (V14-THREE-STAGE-UX: fresh-configure parity).
    add_compile_definitions(_USE_MATH_DEFINES)
endif()

# ------------------------------------------------------------ feature graph --
# Every PWB_* switch is declared here (once, before any add_subdirectory can
# read it), the implied/required edges are expanded to a fixpoint, and the
# resolved graph is validated. The per-slice option()/set() calls further down
# still work: they now only restate what this table already resolved.
include(cmake/PwbFeatures.cmake)
pwb_resolve_feature_dependencies()

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
option(PWB_BUILD_SEISMIC_SERVICE
    "Build the native seismic volume service (libs/seismic_service; implies seismic_io + Visualization headers)" OFF)
if(PWB_BUILD_SEISMIC_SERVICE)
    set(PWB_BUILD_SEISMIC_IO ON)
endif()
option(PWB_BUILD_MAPPING_KERNEL
    "Build the contouring+interpolator kernel ported from the Python mapping pipeline" OFF)
# BEGIN CONV-08
option(PWB_BUILD_CONV_08
    "Build the factor interpolation task host (fingerprint / evaluation / plan structs, libs/factor_host)" OFF)
# END CONV-08
option(PWB_BUILD_INTEGRATION_TESTS
    "Register tests/cpp/integration (requires platform+data+science)" OFF)
include(CTest)

# BEGIN native-product closure
# The product-level integrated configuration: one switch pulling the stable
# C++ product closure (see cmake/PwbNativeProduct.cmake for the capability
# vocabulary, the fail-closed validation and the generated capability
# table behind `pwb-platform --capabilities`). The module is included
# unconditionally — the capability header is generated for every platform
# build — while the imply/summary pair only runs for the product switch.
include(cmake/PwbNativeProduct.cmake)
option(PWB_BUILD_NATIVE_PRODUCT
    "Build the native C++ product closure (platform+data+science+seismic+mapping; fail-closed)" OFF)
if(PWB_BUILD_NATIVE_PRODUCT)
    pwb_native_product_imply()
endif()
# END native-product closure

# BEGIN CONV-18
# Task 18 — FactorGridResult JSON envelope codec (workflow/factor_grid_result.py
# serialization surface). The codec lives in libs/mapping_kernel next to the
# ported numerical cores; Pwb::Domain (nlohmann JSON) is required, so set
# PWB_BUILD_DATA=ON as well when enabling this option directly.
option(PWB_BUILD_CONV_18
    "Build the CONV-18 factor-grid JSON envelope codec + oracle test" OFF)
if(PWB_BUILD_CONV_18 AND NOT PWB_BUILD_MAPPING_KERNEL)
    message(STATUS "CONV-18: enabling PWB_BUILD_MAPPING_KERNEL for the grid envelope codec")
    set(PWB_BUILD_MAPPING_KERNEL ON)
endif()
# END CONV-18

# BEGIN CONV-PROVIDERS — native capability-provider runtime (SDK + builtins):
# the provider/plugin/extension contract, registry, and typed invocation
# pipeline ported from paleo_workbench/providers/* (frozen against
# provider_oracle.json), plus the native factor-stats and map-thumbnail
# providers. Needs Pwb::Domain (PWB_BUILD_DATA), the mapping kernel
# (factor dataset adapter) and the mapping document kernel (thumbnail
# render input); the implied switches land BEFORE the kernel/data/CONV-02
# subdirectory blocks below.
option(PWB_BUILD_PROVIDERS
    "Build the native provider SDK + builtins (libs/providers; implies PWB_BUILD_DATA + PWB_BUILD_MAPPING_KERNEL + CONV-02)" OFF)
if(PWB_BUILD_PROVIDERS)
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_MAPPING_KERNEL ON)
    set(PWB_BUILD_CONV_02 ON)
endif()
# END CONV-PROVIDERS
# BEGIN CONV-23 — workflow/contracts pure contract layer (M7): pydantic-lite
# contract models, the 14 generated module declarations, registry +
# consistency validation, metadata-only readiness evaluation and the two
# deterministic markdown reports — inside libs/workflow_contracts, frozen
# against the Python oracle. Needs Pwb::Domain (ordered JSON); declared
# BEFORE the PWB_BUILD_DATA block so the implied switch lands in time.
option(PWB_BUILD_CONV_23
    "Build the CONV-23 workflow contract layer (libs/workflow_contracts; implies PWB_BUILD_DATA)" OFF)
if(PWB_BUILD_CONV_23)
    set(PWB_BUILD_DATA ON)
    add_subdirectory(libs/workflow_contracts)
endif()
# END CONV-23
# BEGIN CONV-24 — factor_fusion + factor_units pure kernels (M7 tail):
# Normalization/evidence/rule/model contracts, weighted + rule_based fusion,
# sensitivity reports, and the factor-unit lookup/validation tables — in
# libs/factor_fusion, frozen against the Python oracle. Needs Pwb::Domain
# (PWB_BUILD_DATA) and Pwb::FactorHost (python_repr_double for the
# fingerprint encoder), so the implied switches land BEFORE the data and
# CONV-08 subdirectory blocks below.
option(PWB_BUILD_CONV_24
    "Build the CONV-24 factor fusion kernel (libs/factor_fusion; implies PWB_BUILD_DATA + CONV-08)" OFF)
if(PWB_BUILD_CONV_24)
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_CONV_08 ON)
endif()
# END CONV-24
# BEGIN CPP-CLOSE-02 (option block — declared BEFORE the CONV-33 block so
# the full workflow cascade (CONV_33 -> 26B -> 07/08/25/06, CONV_32,
# CONV_24, CONV_30) lands in time; the subdirectory itself is added after
# the CONV-32 block) — workflow orchestration / versioning / recompute
# closure consumers (libs/closure_workflow): the map_product catalog OUTPUT
# orchestration + integrated compilation fusion consumers CONV-33 findings
# A3 left to the consuming line, the file-backed provenance store (reopen
# recovery), the scheduler face (submit_to_scheduler + synced cancel,
# completing the CONV-32 deferral at closure level), the cache-run
# provenance rail, and the typed UI host bindings.
option(PWB_BUILD_CPP_CLOSE_02
    "Build the cpp-close-02 workflow closure consumers (libs/closure_workflow; implies CONV_33 + CONV_32 + CONV_24 + CONV_30)" OFF)
if(PWB_BUILD_CPP_CLOSE_02)
    set(PWB_BUILD_CONV_33 ON)
    set(PWB_BUILD_CONV_32 ON)
    set(PWB_BUILD_CONV_24 ON)
    set(PWB_BUILD_CONV_30 ON)
endif()
# END CPP-CLOSE-02 (option half)
# BEGIN CONV-33 (option block — declared BEFORE the CONV-26B block so the
# runtime closure's own implied switches (DATA / MAPPING_KERNEL / CONV-07/
# 08/25) cascade from it; the slice adds no new subdirectory: its TUs are
# appended to the EXISTING libs/workflow_engine + libs/workflow_runtime +
# libs/project targets — CONV-32 incremental-TU precedent).
# Workflow top-level orchestration slice: recipe (portable
# *.paleo-workflow.json), service/orchestrator (home step-status authority
# + headless cursor), qc + map_qa_rules (basic & extended QA), versioning
# (expert finalize) + the project version-lifecycle models it builds on.
option(PWB_BUILD_CONV_33
    "Build the CONV-33 workflow orchestration surfaces (increments libs/workflow_engine + libs/workflow_runtime + libs/project; implies CONV-26B + CONV-06)" OFF)
if(PWB_BUILD_CONV_33)
    set(PWB_BUILD_CONV_06 ON)
    set(PWB_BUILD_CONV_26B ON)
endif()
# END CONV-33
# BEGIN CONV-26 — workflow runtime closure (M7 tail): freshness /
# current-context, recompute planning + executor, constraint version
# lifecycle, provenance graph, node adapter bridge + resource model, and
# the WorkflowRuntimeService composing them — in libs/workflow_runtime,
# frozen against the Python oracle. Implies the workflow cores it builds
# on: CONV-25 (graph), CONV-07 (engine + mapping ops), CONV-08
# (canonical_json encoder) — the implied switches land BEFORE the data /
# engine / factor_host subdirectory blocks below; the subdirectory itself
# is added after those blocks.
option(PWB_BUILD_CONV_26B
    "Build the CONV-26B workflow runtime closure (libs/workflow_runtime; implies PWB_BUILD_DATA + CONV-07/08/25)" OFF)
if(PWB_BUILD_CONV_26B)
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_MAPPING_KERNEL ON)
    set(PWB_BUILD_CONV_07 ON)
    set(PWB_BUILD_CONV_08 ON)
    set(PWB_BUILD_CONV_25 ON)
endif()
# END CONV-26B

# BEGIN CONV-25 — workflow dependency graph + evidence selectors (M7 tail):
# the catalog-lineage DAG (dependency_graph.py) and the typed evidence
# selector/resolution contract (interpretation/evidence.py) — in
# libs/workflow_graph, frozen against the Python oracle. Needs Pwb::Domain
# (ordered JSON); declared BEFORE the PWB_BUILD_DATA block so the implied
# switch lands in time.
option(PWB_BUILD_CONV_25
    "Build the CONV-25 workflow graph + evidence kernel (libs/workflow_graph; implies PWB_BUILD_DATA)" OFF)
if(PWB_BUILD_CONV_25)
    set(PWB_BUILD_DATA ON)
    # BEGIN V14-COMPILATION-PUBLISH — the once-guard so the UI-14-IMPLY
    # block's pwb_add_subdirectory_once(libs/workflow_graph) does not
    # collide with this raw add (a configure error that blocked every
    # PWB_BUILD_CPP_CLOSE_02=ON configuration, reproduced on a clean
    # main@412d8baf worktree).
    pwb_add_subdirectory_once(libs/workflow_graph)
    # END V14-COMPILATION-PUBLISH
endif()
# END CONV-25
# BEGIN CLOSURE-SCIENCE — line-03 science/prediction product loop: the
# catalog payload source + envelope publisher for the science services, the
# native inference job service (run lifecycle + provider dispatch), the
# demo/tiled-ONNX providers, the prediction task journal, and the Qt
# binding that installs the production hooks into the ui_wellseis
# prediction pages. Implies CONV-28 (science service layer) +
# PREDICTION_RUNTIME (native ONNX runtime), so a standalone
# -DPWB_BUILD_CLOSURE_SCIENCE=ON configure really builds the loop.
option(PWB_BUILD_CLOSURE_SCIENCE
    "Build the line-03 science/prediction product closure (libs/closure_science; implies CONV-28 + PREDICTION_RUNTIME)" OFF)
if(PWB_BUILD_CLOSURE_SCIENCE)
    set(PWB_BUILD_CONV_28 ON)
    set(PWB_BUILD_PREDICTION_RUNTIME ON)
endif()
# END CLOSURE-SCIENCE

# BEGIN CONV-28 — native science service layer (science closure direction):
# typed + cancelable + resource-guarded service envelopes over the frozen
# Qt-free kernels (mapping extract/normalize/interpolate/constrained-IDW/
# layer products/representative facies, well curve ops + DTW, factor fusion,
# geomodel build/section/fault/export), IAlgorithm adapters for TaskRuntime,
# and the local-persistence envelope publisher — inside libs/science_service,
# frozen against tools/oracle/generate_science_service_fixtures.py. Turning
# it on implies every kernel slice it composes (link targets resolve at
# generate time; the flags must land before the subdirectory blocks below).
option(PWB_BUILD_CONV_28
    "Build the CONV-28 native science service layer (libs/science_service)" OFF)
if(PWB_BUILD_CONV_28)
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_MAPPING_KERNEL ON)
    set(PWB_BUILD_CONV_05 ON)   # constrained IDW engine
    set(PWB_BUILD_CONV_10 ON)   # representative facies / point-to-surface
    set(PWB_BUILD_CONV_17 ON)   # crs_contract + geometry_units
    set(PWB_BUILD_CONV_18 ON)   # factor grid envelope codec
    set(PWB_BUILD_CONV_08 ON)   # factor host (fingerprints)
    set(PWB_BUILD_CONV_24 ON)   # factor fusion + units
    set(PWB_BUILD_CONV_09 ON)   # well science (DTW + curve ops)
    set(PWB_BUILD_CONV_22 ON)   # geomodel contracts (implies 12 + 19)
    if(PWB_BUILD_SCIENCE AND NOT TARGET pwb_science)
        add_subdirectory(libs/science_suite)
    elseif(NOT TARGET pwb_science)
        add_subdirectory(libs/algorithms)
    endif()
    if(NOT TARGET pwb_workflow)
        add_subdirectory(libs/workflow)
    endif()
    add_subdirectory(libs/science_service)
endif()
# END CONV-28

# BEGIN PREDICTION-RUNTIME — native prediction runtime closure (M9): the
# production ONNX Runtime session (dynamic loading), the model package /
# input-contract runtime, the tiled pipeline with bounded outputs +
# deterministic summary, the task service and the workflow/catalog seams.
# Implies PWB_BUILD_DATA + CONV-21 (contracts), so a standalone
# -DPWB_BUILD_PREDICTION_RUNTIME=ON configure really builds the closure.
# The ONNX Runtime library itself stays a runtime discovery: set
# -DPWB_ONNXRUNTIME_LIBRARY=<path> to bake a hint for tests/production.
# Declared BEFORE the data and CONV-13/21 blocks so the implied switches
# land in time.
option(PWB_BUILD_PREDICTION_RUNTIME
    "Build the native prediction runtime (implies PWB_BUILD_DATA + CONV-21; ONNX Runtime loaded at run time)" OFF)
if(PWB_BUILD_PREDICTION_RUNTIME)
    # Set the whole chain here as normal variables: option() does nothing
    # when the variable is already set (CMP0077), so the later CONV blocks
    # keep these values.
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_CONV_21 ON)
    set(PWB_BUILD_CONV_13 ON)
    set(PWB_BUILD_CONV_14 ON)
    set(PWB_BUILD_CONV_19 ON)
endif()
# END PREDICTION-RUNTIME

# BEGIN LINE-14 — pwb-bench: Qt-free native benchmark harness
# (tools/pwb-bench) for the performance-audit line. Measures the merged
# native user-flow cores (catalog load/page, tiled inference + model gate,
# seismic slice/tile-cache, project save/reopen) with fixed samples,
# median/p95, peak RSS, /proc/self/io deltas and a heap-allocation counter.
# Implies the library closure it links; the ONNX Runtime stays a runtime
# discovery — the bench never fabricates a session it cannot open.
option(PWB_BUILD_BENCH
    "Build the pwb-bench native benchmark tool (implies PWB_BUILD_DATA + CONV-13 + SEISMIC_IO)" OFF)
if(PWB_BUILD_BENCH)
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_CONV_13 ON)
    set(PWB_BUILD_SEISMIC_IO ON)
endif()
# END LINE-14

# BEGIN CONV-29 — composer/layout/export C++ closure: the Qt-free
# layout-export behavior kernel (build_layout_spec, hybrid classification,
# legend mirror gates, pixel budget, report, screen/export parity) in
# libs/layout_export, the composition export service + shared wire-spec
# executor wired into libs/qgis, and the platform export dialog upgrade.
# Requires the CONV-02 composition document kernel and Pwb::Domain, so the
# implied switches land BEFORE the CONV-02 and PWB_BUILD_DATA blocks below.
option(PWB_BUILD_CONV_29
    "Build the CONV-29 composer/layout/export C++ chain (libs/layout_export + libs/qgis service + app wiring; implies PWB_BUILD_CONV_02 + PWB_BUILD_DATA + PWB_BUILD_PLATFORM)" OFF)
if(PWB_BUILD_CONV_29)
    if(NOT PWB_BUILD_DATA)
        message(STATUS "CONV-29: enabling PWB_BUILD_DATA (Pwb::Domain closure)")
        set(PWB_BUILD_DATA ON)
    endif()
    if(NOT PWB_BUILD_CONV_02)
        message(STATUS "CONV-29: enabling PWB_BUILD_CONV_02 (composition document kernel)")
        set(PWB_BUILD_CONV_02 ON)
    endif()
    if(NOT PWB_BUILD_PLATFORM)
        message(FATAL_ERROR
            "PWB_BUILD_CONV_29=ON requires PWB_BUILD_PLATFORM=ON "
            "(the slice wires CompositionLayoutService into the platform)")
    endif()
endif()
# END CONV-29

# BEGIN CONV-27C — cartography style/template/symbol/ramp registry (the
# early-excluded cartography surfaces): Qt-free style value types + color
# ramp registry + geological symbol V2 registry + style libraries + scalar
# classification kernels + componentized map template library + QGIS bridge
# payload adapter, in libs/cartography, frozen against the Python oracle.
# Builds on Pwb::Domain (ordered JSON) and the CONV-02 composition/document
# models, so the implied switches land BEFORE the data and CONV-02 blocks.
# Flag renamed from the branch's PWB_BUILD_CONV_27: that option is already
# claimed by the qgis-ui-workbench slice (Pwb::UiWorkbench).
option(PWB_BUILD_CONV_27C
    "Build the cartography style/template/symbol/ramp registry (libs/cartography; implies PWB_BUILD_DATA + CONV-02)" OFF)
if(PWB_BUILD_CONV_27C)
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_CONV_02 ON)
endif()
if(PWB_BUILD_CONV_27C)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/cartography/CMakeLists.txt")
        message(FATAL_ERROR "PWB_BUILD_CONV_27C=ON but libs/cartography is not present on this branch")
    endif()
endif()
# END CONV-27C

# BEGIN CONV-GEO3D — native 3D geomodel viewer (libs/geo3d_viz): the C++
# replacement of the pyqtgraph 3D visualization runtime (scene model +
# geological scene adapter + Qt6 OpenGL viewport + workspace controller).
# Consumes the pwb::geomodel contract kernels, so it implies CONV-22 (and
# through it CONV-12/19) and Pwb::Domain (PWB_BUILD_DATA). Declared BEFORE
# the PWB_BUILD_DATA block so the implied switches land in time; the
# subdirectory itself joins after the CONV-12 geomodel kernels.
option(PWB_BUILD_GEO3D_VIZ
    "Build the CONV-GEO3D native 3D geomodel viewer (implies CONV-22 + data)" OFF)
if(PWB_BUILD_GEO3D_VIZ)
    set(PWB_BUILD_CONV_22 ON)
    set(PWB_BUILD_DATA ON)
endif()
# END CONV-GEO3D

# BEGIN CONV-30 — async jobs / threading / progress / cancellation runtime:
# the bounded job scheduler (libs/job_runtime, Qt-free core + Qt queued
# event bridge) replacing the Python TaskScheduler / OwnedWorkerJob /
# DetachedJobKeeper surfaces. The core builds with no Qt; the Qt bridge and
# the platform app wiring appear only when Qt6::Core is really there
# (find below is QUIET — Qt-less configurations still get the core).
option(PWB_BUILD_CONV_30 "Build the CONV-30 job runtime (libs/job_runtime)" ON)
if(PWB_BUILD_CONV_30)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/job_runtime/CMakeLists.txt")
        message(FATAL_ERROR "PWB_BUILD_CONV_30=ON but libs/job_runtime is not merged on this branch")
    endif()
    # The policy oracle test replays the frozen ladder through the domain
    # JSON conventions (Pwb::Domain), same implication shape as CONV-18/23.
    if(NOT PWB_BUILD_DATA)
        set(PWB_BUILD_DATA ON)
        message(STATUS "CONV-30: enabling PWB_BUILD_DATA for the domain JSON closure")
    endif()
    find_package(Qt6 6.8 QUIET COMPONENTS Core)
    add_subdirectory(libs/job_runtime)
endif()
# END CONV-30

# ------------------------------------------------- B/C integration switches --
# ON must mean the module is really there; a missing module is a configure
# error, never a silent skip (protocol: independent validation).
# BEGIN CONV-26
# Data / workspace / catalog / project lifecycle closure (conv-26): SQL-level
# paged catalog reads, ingest plan build+execute orchestration (import_raw
# parity, chunked idempotent transactions), project save-as relocation,
# workspace membership write ops, and the metadata-scale sanity suite inside
# libs/{catalog,data_suite,project,workspace} + tests/cpp/data. Turning it on
# implies the data kernel and the ingest parser cores (classifier reuse).
# Declared BEFORE the PWB_BUILD_DATA block so the implied switch lands in
# time (CONV-23 precedent).
option(PWB_BUILD_CONV_26
    "Build the data lifecycle closure cores (implies PWB_BUILD_DATA/CONV-19)" OFF)
if(PWB_BUILD_CONV_26)
    set(PWB_BUILD_DATA ON)
    set(PWB_BUILD_CONV_19 ON)
endif()
# END CONV-26
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
    if(NOT TARGET pwb_science)
        add_subdirectory(libs/science_suite)
    endif()
endif()

# ---------------------------------------------------- D/E fail-closed gates --
# D (libs/seismic_viewer) and E (libs/seismic_attributes) are separate
# lines; until their owners deliver, the switches exist but cannot be ON.
# BEGIN VIZ-D — the viewer's crossplot core reuses the frozen single-trace
# attribute kernels, so the viewer line now implies the attributes line
# (same pattern as PWB_BUILD_SEISMIC_SERVICE implying seismic_io below).
if(PWB_BUILD_SEISMIC_VIEWER)
    set(PWB_BUILD_SEISMIC_ATTRIBUTES ON)
endif()
# END VIZ-D
if(PWB_BUILD_SEISMIC_VIEWER)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/seismic_viewer/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_SEISMIC_VIEWER=ON but libs/seismic_viewer is not "
            "delivered on this branch (CPP-D line). A test double must never "
            "stand in for the production viewer.")
    endif()
    add_subdirectory(libs/seismic_viewer)
endif()
# Native seismic volume service (S line): inspect/tile-cache backend for the
# viewer; requires the Visualization contract headers and seismic_io.
if(PWB_BUILD_SEISMIC_SERVICE)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/seismic_service/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_SEISMIC_SERVICE=ON but libs/seismic_service is not "
            "delivered on this branch (S line).")
    endif()
    add_subdirectory(libs/seismic_service)
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
# BEGIN CONV-17 — task 17: geometry_units + crs_contract leaves beside
# crs_policy (mapping_kernel). The leaves live inside libs/mapping_kernel;
# turning this on implies the kernel build. Declared BEFORE the kernel
# subdirectory is added so a standalone -DPWB_BUILD_CONV_17=ON configure
# really produces the targets (ON must mean it is really there). OFF
# leaves the tree identical to main.
option(PWB_BUILD_CONV_17
    "Build CONV-17 geometry-units/CRS-contract leaves and their oracle test" OFF)
if(PWB_BUILD_CONV_17 AND NOT PWB_BUILD_MAPPING_KERNEL)
    set(PWB_BUILD_MAPPING_KERNEL ON)
endif()
# END CONV-17

# NOTE: libs/mapping_kernel is mounted AFTER the UI-14-IMPLY block below.
# UI-14 (platform+data) implies the kernel for the controller pages, and
# the kernel's only mount point used to sit above that implication — so
# any configure that did not pass PWB_BUILD_MAPPING_KERNEL=ON by hand
# reached the CONV-07 workflow_engine block with the flag ON but the
# Pwb::MappingKernel target missing (generate failure; the presets masked
# it by passing the flag explicitly) (#1444).

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
# BEGIN UI-10-IMPLY — the UI-10 sequence/factor/visualization pages cluster
# (libs/ui_seqviz) binds the composition document/session kernels
# (CONV-02 mapping_document), the composition template cartography
# (CONV-27C), the layout-export kernel (CONV-29) and the well-curve
# operation kernels (CONV-11 well_science). UI slices carry no per-slice
# option — they gate under PWB_BUILD_PLATFORM (taskbook §2: no new
# option(), no flag preemption) — so a platform+data configure implies the
# kernel closure the pages need, exactly like the UI-04 block implies
# CONV-22 for libs/ui_workers.
if(PWB_BUILD_PLATFORM AND PWB_BUILD_DATA)
    foreach(_ui10_kernel CONV_02 CONV_27C CONV_29 CONV_11)
        if(NOT PWB_BUILD_${_ui10_kernel})
            set(PWB_BUILD_${_ui10_kernel} ON)
            message(STATUS
                "UI-10: implying PWB_BUILD_${_ui10_kernel}=ON — "
                "libs/ui_seqviz binds the seqviz page kernels")
        endif()
    endforeach()
endif()
# END UI-10-IMPLY

# BEGIN UI-14-IMPLY — the UI-14 root controllers (libs/ui_controllers) bind
# the workflow-runtime closure (CONV-26B recompute planner) and the
# prediction contract cores (CONV-21 → CONV-13/14/19). UI slices carry no
# per-slice option (taskbook §2), so a platform+data configure implies the
# kernel closure the controllers need — the UI-04/UI-10 precedent.
if(PWB_BUILD_PLATFORM AND PWB_BUILD_DATA)
    foreach(_ui14_kernel CONV_26B CONV_21)
        if(NOT PWB_BUILD_${_ui14_kernel})
            set(PWB_BUILD_${_ui14_kernel} ON)
            message(STATUS
                "UI-14: implying PWB_BUILD_${_ui14_kernel}=ON — "
                "libs/ui_controllers binds the controller kernels")
        endif()
    endforeach()
    # CONV-26B's own imply-if ran earlier (its option block sits above
    # this point), so land the downstream switches it would have set.
    # CONV-06/07 option blocks still lie ahead — normal-variable sets
    # shadow them (CMP0077) and their subdirectory adds run on time.
    # CONV-25's add_subdirectory already passed, so mount it directly.
    # V14-THREE-STAGE-UX: CONV-26B also sets PWB_BUILD_MAPPING_KERNEL —
    # without it the CONV-07 option block below fatals on any fresh
    # PLATFORM+DATA configure that did not pass the kernel flag by hand
    # (the presets masked this by passing it explicitly).
    set(PWB_BUILD_MAPPING_KERNEL ON)
    set(PWB_BUILD_CONV_06 ON)
    set(PWB_BUILD_CONV_07 ON)
    set(PWB_BUILD_CONV_08 ON)
    set(PWB_BUILD_CONV_25 ON)
    pwb_add_subdirectory_once(libs/workflow_graph)
endif()
# END UI-14-IMPLY

# The kernel mount, now after every imply-block that can turn it on
# (CONV-03/05/17 above, UI-14-IMPLY above) and before every consumer
# (CONV-02 mapping_document, CONV-07 workflow_engine, factor_host, …).
if(PWB_BUILD_MAPPING_KERNEL)
    add_subdirectory(libs/mapping_kernel)
endif()

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
# BEGIN CONV-29
# The layout-export behavior kernel consumes Pwb::MappingDocument, so the
# subdirectory lands right after the CONV-02 one.
if(PWB_BUILD_CONV_29)
    add_subdirectory(libs/layout_export)
endif()
# END CONV-29

# BEGIN CONV-27B
# Map document / composition behavior layer over the CONV-02 data kernel
# (swarm cpp-map-document-edit-session): CompositionEditSession +
# MapDocumentEditSession undo/redo, unified data/style/layout revisions and
# dirty state, immutable document snapshots, document_io feature
# normalization and atomic file IO with recovery. Qt-free, QGIS-free;
# frozen against the Python oracle.
# Flag renamed from the branch's PWB_BUILD_CONV_27: that option is already
# claimed by the qgis-ui-workbench slice (Pwb::UiWorkbench), and sharing it
# would force PWB_BUILD_PLATFORM onto this Qt-free layer's standalone
# configure.
option(PWB_BUILD_CONV_27B
    "Build the CONV-27b mapping_document edit-session/snapshot/IO behavior layer" OFF)
if(PWB_BUILD_CONV_27B AND NOT PWB_BUILD_CONV_02)
    set(PWB_BUILD_CONV_02 ON)
endif()
if(PWB_BUILD_CONV_27B AND NOT TARGET pwb_mapping_document)
    add_subdirectory(libs/mapping_document)
endif()
# END CONV-27B
# CONV-PROVIDERS subdirectory — placed after the mapping kernel/document
# blocks so Pwb::MappingKernel and Pwb::MappingDocument exist (ALIAS targets
# must be defined when referenced).
if(PWB_BUILD_PROVIDERS)
    add_subdirectory(libs/providers)
endif()
# BEGIN CONV-06
# WorkflowSpec DAG pure model + validator (M7 leaf; Qt-free, QGIS-free).
# Requires Pwb::Domain (ordered JSON + sha256) from PWB_BUILD_DATA=ON.
option(PWB_BUILD_CONV_06
    "Build the workflow_spec DAG model/validator ported from workflow/dag" OFF)
if(PWB_BUILD_CONV_06)
    add_subdirectory(libs/workflow_spec)
endif()
# END CONV-06
# BEGIN CONV-07
# In-memory DAG workflow engine (full-conversion plan M7 executor slice):
# topological order, failure short-circuit, cooperative cancel, per-node
# stdout logging; node ops wrap the mapping_kernel extract/interpolate
# kernels, so the kernels must be on.
option(PWB_BUILD_CONV_07
    "Build the in-memory DAG workflow engine (libs/workflow_engine)" OFF)
if(PWB_BUILD_CONV_07)
    if(NOT PWB_BUILD_MAPPING_KERNEL)
        message(FATAL_ERROR
            "PWB_BUILD_CONV_07=ON requires PWB_BUILD_MAPPING_KERNEL=ON "
            "(node ops wrap the mapping kernels)")
    endif()
    if(NOT PWB_BUILD_CONV_06)
        message(FATAL_ERROR
            "PWB_BUILD_CONV_07=ON requires PWB_BUILD_CONV_06=ON "
            "(CONV-32 store/run_engine persist the workflow_spec DTOs)")
    endif()
    add_subdirectory(libs/workflow_engine)
endif()
# END CONV-07
# BEGIN CLOSURE-AGENT (line 11) subdirectory — guarded agent/harness
# execution core: ActionSpec/registry/executor port, agent session state
# machine, intent+DAG planner, session checkpoint/recovery, event stream,
# chat-model transport seam. Consumes Pwb::Providers (line-10 tool
# interface) — no provider registry rebuilt. Placed after the CONV-06/07
# blocks so the optional workflow adapter can link Pwb::WorkflowEngine.
if(PWB_BUILD_CLOSURE_AGENT AND PWB_BUILD_PROVIDERS AND TARGET pwb_providers)
    add_subdirectory(libs/closure_agent)
endif()
# END CLOSURE-AGENT
# BEGIN CONV-08
if(PWB_BUILD_CONV_08)
    add_subdirectory(libs/factor_host)
endif()
# END CONV-08
# CONV-24 subdirectory — placed after CONV-08 so Pwb::FactorHost exists.
if(PWB_BUILD_CONV_24)
    add_subdirectory(libs/factor_fusion)
endif()
# CONV-26B subdirectory — after the CONV-07/08/25 blocks so the engine,
# factor_host and graph targets exist.
if(PWB_BUILD_CONV_26B)
    add_subdirectory(libs/workflow_runtime)
endif()
# BEGIN CONV-27C (subdirectory) — added after the data, CONV-02 and
# CONV-26B blocks so Pwb::Domain + Pwb::MappingDocument +
# Pwb::WorkflowRuntime + Pwb::MappingKernel exist when the library
# configures (the §14 cartographic QA rule set consumes the workflow_runtime
# delegate inputs/make_issue/catalog seams).
if(PWB_BUILD_CONV_27C)
    add_subdirectory(libs/cartography)
endif()
# END CONV-27C (subdirectory)
# BEGIN CONV-32
# Workflow interpretation domain spine (Qt-free, M7 interpretation core):
# constraint capabilities + algorithm registry, factor products +
# summaries, constraint products + interpretation revisions, integrated
# interpretation + compilation input sets. Requires the graph / runtime /
# fusion cores from CONV-25/26B/24.
option(PWB_BUILD_CONV_32
    "Build the CONV-32 workflow interpretation core (libs/workflow_interpretation; implies PWB_BUILD_CONV_25 + CONV_26B + CONV_24)" OFF)
if(PWB_BUILD_CONV_32)
    foreach(_conv32_req CONV_25 CONV_26B CONV_24)
        if(NOT PWB_BUILD_${_conv32_req})
            message(FATAL_ERROR
                "PWB_BUILD_CONV_32=ON requires PWB_BUILD_${_conv32_req}=ON")
        endif()
    endforeach()
    add_subdirectory(libs/workflow_interpretation)
endif()
# END CONV-32
# CPP-CLOSE-02 subdirectory — after the CONV-32 block so the workflow
# interpretation, runtime, engine, fusion and job targets exist.
if(PWB_BUILD_CPP_CLOSE_02)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/closure_workflow/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_CPP_CLOSE_02=ON but libs/closure_workflow is not "
            "delivered on this branch (cpp-close-02 line).")
    endif()
    add_subdirectory(libs/closure_workflow)
endif()
# END CPP-CLOSE-02
# BEGIN CONV-09
# M8 first slice: DTW well-log matcher kernel (viz/dtw_log_matcher.py port),
# Qt-free, frozen against the Python oracle. Tests need Pwb::Domain
# (configure with -DPWB_BUILD_DATA=ON).
option(PWB_BUILD_CONV_09
    "Build the CONV-09 well_science DTW kernel (M8 first slice)" OFF)
if(PWB_BUILD_CONV_09)
    # TARGET guard, not just the once-guard: with the WLE viewer stack on,
    # science_suite (added at the NATIVE_PRODUCT imply block, before this
    # line) already pulls libs/well_science for the well-log adapter — the
    # once-guard's bookkeeping cannot see that add (same idiom as CONV-11).
    if(NOT TARGET pwb_well_science)
        pwb_add_subdirectory_once(libs/well_science)
    endif()
endif()
# END CONV-09
# BEGIN CONV-11
# Well-curve interpretation kernels (curve_operations/well_science port,
# swarm task 11). Independent of every other CONV-* block.
option(PWB_BUILD_CONV_11
    "Build the well-curve ops kernel port (libs/well_science, swarm CONV-11)" OFF)
if(PWB_BUILD_CONV_11)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/well_science/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_CONV_11=ON but libs/well_science is not "
            "delivered on this branch")
    endif()
    if(NOT TARGET pwb_well_science)
        pwb_add_subdirectory_once(libs/well_science)
    endif()
endif()
# END CONV-11
# BEGIN UI-04-IMPLY — the UI-04 page-worker ports (libs/ui_workers) bind
# the CONV-22 geomodel contract cores (advisor rules, V2 exporters,
# DomainObject). UI slices carry no per-slice option — they gate under
# PWB_BUILD_PLATFORM (taskbook §2: no new option(), no flag preemption) —
# so a platform configure implies the kernel closure they need, exactly
# like CONV-28 / CONV-GEO3D imply CONV-22 for their consumers. DATA is
# part of the implication because CONV-22 links Pwb::Domain. Kernel-only
# configures (conversion-kernel) set -DPWB_BUILD_CONV_22=ON directly;
# configures without DATA keep the Python workers as the production path.
if(PWB_BUILD_PLATFORM AND PWB_BUILD_DATA AND NOT PWB_BUILD_CONV_22)
    set(PWB_BUILD_CONV_22 ON)
    message(STATUS
        "UI-04: implying PWB_BUILD_CONV_22=ON — libs/ui_workers binds "
        "the geomodel contract cores (advisor/export/DomainObject)")
endif()
# END UI-04-IMPLY
# BEGIN CONV-22 — geomodel contract/writer cores (M8): domain object
# contracts, QC ladder + export gate, the five export writers + read-back
# validators + provenance sidecars, advisor rules, lithology tables, and the
# pure builders constructors — inside libs/geomodel, frozen against the
# Python oracle. The slice needs the geomodel kernels (CONV-12) and the
# ingest XML/py_compat cores (CONV-19); turning it on implies both (and the
# test needs Pwb::Domain, i.e. PWB_BUILD_DATA=ON). Declared BEFORE the
# CONV-12 subdirectory is added.
option(PWB_BUILD_CONV_22
    "Build the CONV-22 geomodel contract/export cores (implies CONV-12/19)" OFF)
if(PWB_BUILD_CONV_22)
    set(PWB_BUILD_CONV_12 ON)
    set(PWB_BUILD_CONV_19 ON)
endif()
# END CONV-22
# BEGIN CONV-12
# geomodel geometric kernels (CONV-12): faithful C++ port of the Python viz
# formation-volume stack — paleo_workbench/viz/formation_volume.py,
# horizon_sculpting.py, fault_displacement.py and the pure-geometry halves of
# viz/geomodel/{builders,measurements,section,qc}. Qt-free, Python-free,
# numpy-free; frozen against tools/oracle/generate_geomodel_volume_fixtures.py.
option(PWB_BUILD_CONV_12
    "Build the geomodel volume/thickness/section kernel ported from the Python viz stack (CONV-12)" OFF)
if(PWB_BUILD_CONV_12)
    add_subdirectory(libs/geomodel)
endif()
# END CONV-12
# BEGIN CONV-21 — prediction contract cores (M9): pure halves of
# prediction/{postprocess,spatial_result,input_contract,model_package}
# inside libs/prediction, frozen against the Python oracle. The slice needs
# the prediction lib (CONV-13), the interchange Unicode leaves (CONV-14)
# and the ingest parse/py_compat cores (CONV-19); turning it on implies
# all three so a standalone -DPWB_BUILD_CONV_21=ON configure really builds.
# Declared BEFORE those subdirectories are added.
option(PWB_BUILD_CONV_21
    "Build the CONV-21 prediction contract cores (implies CONV-13/14/19)" OFF)
if(PWB_BUILD_CONV_21)
    set(PWB_BUILD_CONV_13 ON)
    set(PWB_BUILD_CONV_14 ON)
    set(PWB_BUILD_CONV_19 ON)
endif()
# END CONV-21

# BEGIN CONV-13 — prediction tiled inference geometry (M9 first slice).
# Qt-free core: tile/halo/center-crop-fusion contract from
# paleo_workbench/prediction/tiled_onnx.py, frozen against the Python
# stub oracle (ctest target prediction.tiled_stub). libonnxruntime is
# NOT required — the inference session is a seam with a CPU stub.
option(PWB_BUILD_CONV_13
    "Build the tiled ONNX inference core ported from paleo_workbench/prediction (libs/prediction)" OFF)
if(PWB_BUILD_CONV_13)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/prediction/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_CONV_13=ON but libs/prediction is not merged on this branch")
    endif()
    add_subdirectory(libs/prediction)
endif()
# END CONV-13
# BEGIN CONV-14-DEPS — libs/interchange's exporters hard-require the
# ingest CSV/XML readers and the SEGY inspector (fail-closed inside
# libs/interchange/CMakeLists.txt). CONV-14 can be turned on below this
# point by the CONV-21 imply chain (UI-14 platform+data), so resolve the
# dependency implication HERE — after every writer of PWB_BUILD_CONV_14
# and before the ingest/interchange mounts — and mount seismic_io late
# when this chain pulled it in after its early block passed (#1444).
if(PWB_BUILD_CONV_14)
    if(NOT PWB_BUILD_CONV_19)
        set(PWB_BUILD_CONV_19 ON)
        message(STATUS
            "CONV-14: implying PWB_BUILD_CONV_19=ON — interchange "
            "exporters need the ingest readers")
    endif()
    if(NOT PWB_BUILD_SEISMIC_IO)
        set(PWB_BUILD_SEISMIC_IO ON)
        message(STATUS
            "CONV-14: implying PWB_BUILD_SEISMIC_IO=ON — interchange "
            "exporters need the SEGY inspector")
    endif()
    if(PWB_BUILD_SEISMIC_IO AND NOT TARGET pwb_seismic_io)
        add_subdirectory(libs/seismic_io)
        if(BUILD_TESTING AND TARGET pwb_seismic_io)
            add_subdirectory(libs/seismic_io/seismic_io_tests)
        endif()
    endif()
endif()
# END CONV-14-DEPS
# BEGIN CONV-19
# Resource-scan / well-tops / well-location-XML / preview parse cores
# (libs/ingest), ported from paleo_workbench.resources and frozen against the
# Python oracle. Requires the domain kernel for JSON/SHA-256 conventions.
option(PWB_BUILD_CONV_19
    "Build the ingest parser cores ported from resources/ (libs/ingest)" OFF)
if(PWB_BUILD_CONV_19)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/ingest/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_CONV_19=ON but libs/ingest is not present on this branch")
    endif()
    # CONV-26: PWB_BUILD_DATA may already have added libs/ingest (data_suite
    # links Pwb::Ingest); the guard keeps a combined configure single-add.
    if(NOT TARGET pwb_ingest)
        add_subdirectory(libs/ingest)
    endif()
endif()
# END CONV-19
# BEGIN CONV-14
option(PWB_BUILD_CONV_14
    "Build the interchange path-safety/manifest/preflight kernel (conv-14)" OFF)
if(PWB_BUILD_CONV_14)
    add_subdirectory(libs/interchange)
endif()
# END CONV-14
# BEGIN LINE-14 — mount the bench tool only when its library closure
# resolved (fail-closed like the D/E gates; never a stub bench).
if(PWB_BUILD_BENCH)
    if(TARGET Pwb::Prediction AND TARGET Pwb::Catalog
       AND TARGET Pwb::SeismicIo AND TARGET Pwb::Project)
        add_subdirectory(tools/pwb-bench)
    else()
        message(FATAL_ERROR
            "PWB_BUILD_BENCH=ON but the bench library closure is missing "
            "(needs Pwb::Prediction + Pwb::Catalog + Pwb::SeismicIo + "
            "Pwb::Project)")
    endif()
endif()
# END LINE-14
# BEGIN CONV-GEO3D
# Added after the CONV-12 geomodel kernels and the CONV-19 ingest cores so
# the sibling targets exist and the lib's standalone guards all skip.
if(PWB_BUILD_GEO3D_VIZ)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/libs/geo3d_viz/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_BUILD_GEO3D_VIZ=ON but libs/geo3d_viz is not "
            "delivered on this branch")
    endif()
    add_subdirectory(libs/geo3d_viz)
endif()
# END CONV-GEO3D
# BEGIN CONV-20
# Optional pybind11 facade (branch feat/cpp-conv-20-pybind-facade): exposes
# the Qt-free mapping_kernel cores to Python as module `pwb_mapping_kernel`,
# consumed by the thin try/except facade
# paleo_workbench/mapping/geological_pipeline/native_bind.py. OFF by default;
# never part of the integrated gate. Requires the kernel and Pwb::Domain
# (the extract core links Json).
option(PWB_BUILD_CONV_20
    "Build the optional pybind11 mapping_kernel facade (libs/mapping_bind)" OFF)
if(PWB_BUILD_CONV_20)
    if(NOT PWB_BUILD_MAPPING_KERNEL)
        message(FATAL_ERROR
            "PWB_BUILD_CONV_20=ON requires PWB_BUILD_MAPPING_KERNEL=ON "
            "(the facade wraps the mapping_kernel cores)")
    endif()
    add_subdirectory(libs/mapping_bind)
endif()
# END CONV-20

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
    # QGIS-PLOT — QgsPlotCanvas-based scientific 2D plot infrastructure
    # (docs/development/qgis-native-plot-convergence/).
    add_subdirectory(libs/qgis_plot)

# BEGIN PROMPT-7
# QGIS-native Python runtime (qgispython / PyQGIS / console / plugins).
# OFF by default: existing builds stay byte-identical until the vendored QGIS
# closure actually carries src/python and python/ (see
# docs/development/qgis-native-python-runtime/03-qgispython-bootstrap.md §7).
if(PALEO_WITH_QGIS_PYTHON)
    add_subdirectory(libs/qgis_python)
endif()
# END PROMPT-7
    add_subdirectory(libs/application)
    add_subdirectory(libs/ui)
    add_subdirectory(libs/platform_services)
    add_subdirectory(libs/ui_widgets)
    add_subdirectory(libs/ui_shell)
    add_subdirectory(libs/ui_data_core)
    # UI-05 — qgs-map slice: QGIS-backed map surfaces + Qt panels
    # (map canvas panel, work-area widget, layer tree, document/chrome
    # panels, dock manager, constrained mapping-page shell).
    add_subdirectory(libs/ui_map)
    add_subdirectory(libs/ui_pages_preview)
    # QGIS Processing convergence: provider + runner + QgsTaskManager bridge.
    # (After ui_pages_preview: the well_head_scatter adapter links
    # Pwb::UiPagesPreview, whose target is defined there.)
    add_subdirectory(libs/qgis_processing)
    add_subdirectory(libs/ui_pages_data)
    # UI-08 — qt-mapedit slice: map-edit page cluster (scene/view/toolbar,
    # attribute/topology/reference/boundary panels, factor shelf, inspector)
    # over the ui_data_core edit stack.
    add_subdirectory(libs/ui_pages_mapedit)
    # UI-12 — workstation shell slice: dock composition frame + panel
    # widgets over the UI-01 shell substrate (pages stay injected).
    add_subdirectory(libs/ui_workstation)
    # V14-THREE-STAGE-UX — stage presentation projection (snapshot/layout
    # profiles/preference codec + unified surface state model) with a Qt
    # controller shell; authority stays in ProjectSession/tool_policy.
    add_subdirectory(libs/ui_stageflow)
    # BEGIN UI-18 — Ribbon 五工作区 chrome (libs/ui_ribbon): Qt-free core
    # (five-workspace registry, data-driven command group table, three-mode
    # state machine, host-injected disabled-reason channel) + RibbonBar Qt
    # shell. M1 only — not wired into the app shell; the composition root
    # (ribbon_install.cpp) lands with the later milestones. No new option:
    # the core joins every configuration that resolved Pwb::ToolPolicy, the
    # _qt target the ones with Qt6::Widgets + the shell slices it binds.
    add_subdirectory(libs/ui_ribbon)
    # END UI-18
    # UI-13 — workstation-composite slice: Qt-free composite-editor
    # cores (vector layers/edit sessions, topology, merge, CRS gate,
    # snapping, map tools, controller) + Qt/QGIS shells as they land.
    add_subdirectory(libs/ui_composite)
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

# BEGIN VIZ-C — store concurrency regression (#1380/#1381). Tests
# degrade out when the store closure is absent (kernel-only configure);
# never a hard dependency.
if(BUILD_TESTING AND TARGET Pwb::Application)
    add_subdirectory(tests/cpp/viz_c)
endif()
# END VIZ-C

# BEGIN VIZ-D — advanced seismic display tests (CONV-VIZ V5 D-line):
# frozen-Python replay (display/horizon/crossplot/isosurface/wellhead
# oracles), Qt widget integration and the preview presenter replay. Only
# the viewer library is required; the preview replay additionally needs
# Pwb::UiPagesPreview (PLATFORM family) and registers only when present.
if(BUILD_TESTING AND TARGET Pwb::SeismicViewer)
    add_subdirectory(tests/cpp/viz_d)
endif()
# END VIZ-D

# BEGIN UI-04 — core page-worker ports (libs/ui_workers): the Qt-free C++
# halves of the seven PySide6 worker modules in paleo_workbench/ui/pages.
# No new switch: the library joins every configuration that resolves the
# kernels the ports bind — under PWB_BUILD_PLATFORM whenever the CONV-22
# geomodel contracts, Pwb::Domain and the CONV-30 job runtime are present
# (the platform/native-product and kernel closures pull them in), and in
# kernel-closure configures like conversion-kernel so the oracle replay
# tests run without the QGIS weight. Configs without those slices keep
# the Python workers as the production path.
if(PWB_BUILD_CONV_22 AND TARGET Pwb::GeoModel AND TARGET Pwb::Domain
   AND TARGET Pwb::JobContracts)
    add_subdirectory(libs/ui_workers)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "UI-04: libs/ui_workers skipped — enable PWB_BUILD_CONV_22 "
        "(geomodel contracts) for the worker ports; the Python workers "
        "remained the production path until the 2026-09 Python retirement)")
endif()
# END UI-04

# BEGIN UI-09 — qt-well-seismic slice (libs/ui_wellseis): Qt-free semantic
# cores + thin Qt Widgets shells + the QGIS well-map surface for the
# well/seismic page cluster. Same gating model as UI-04: no per-slice
# option; the library joins platform configures that already resolved
# Pwb::UiWorkers (the CONV-22 implication above) and pulls in the CONV-11
# well_science leaf (depth-unit vocabulary for the cursor gates) when the
# kernel slices left it out. The QGIS surface target only exists where
# Pwb::Qgis was admitted; the Qt target needs Qt6::Widgets from the
# platform block. Configures without those keep the Python pages as the
# production path.
if(PWB_BUILD_PLATFORM AND TARGET Pwb::UiWorkers AND TARGET Qt6::Widgets)
    if(NOT TARGET pwb_well_science)
        pwb_add_subdirectory_once(libs/well_science)
    endif()
    add_subdirectory(libs/ui_wellseis)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "UI-09: libs/ui_wellseis skipped — needs Pwb::UiWorkers "
        "(PWB_BUILD_DATA + implied PWB_BUILD_CONV_22) and Qt6::Widgets; "
        "the Python pages remained the production path until the 2026-09 Python retirement)")
endif()
# END UI-09

# BEGIN CLOSURE-SEISMIC (07) — app install, post-hoc. Pwb::UiWellseisQt
# only exists after the UI-09 mount above, and apps/ is processed before
# UI-09 — the in-app TARGET gate could never fire, so the seismic
# prediction page binding never compiled into the product (the TU only
# lived in the viz_d.closure test target) (#1444).
if(TARGET Pwb::SeismicViewer AND TARGET Pwb::SeismicService
        AND TARGET Pwb::SeismicAttributes AND TARGET Pwb::UiWellseisQt
        AND TARGET pwb-platform)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicService
                                               Pwb::SeismicAttributes
                                               Pwb::Science)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CLOSURE_SEISMIC=1)
    # algorithm_exec.cpp (phase 4): the paleo-named kernel executor the
    # section-attribute path (and the crossplot resolver seam) uses; it
    # needs the Science + SeismicAttributes include/link closure.
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/algorithm_exec.cpp
        apps/paleo_workbench_platform/closure_seismic_install.cpp)
endif()
# END CLOSURE-SEISMIC

# BEGIN UI-11 — qt-review-gov slice (libs/ui_review): Qt-free semantic
# cores + thin Qt Widgets shells for the review/governance cluster
# (review export page, governance metadata, catalog health, lineage
# explorer, impact preview, version workbench, ingest plan, relink,
# AI-check advisor, QC issue table, workflow contract panel) plus the
# non-production composite prototype on the _qgis target. Same gating
# model as UI-09: no per-slice option; the library joins platform
# configures that already resolved the data closure (Pwb::Data —
# PWB_BUILD_DATA, which also supplies Pwb::Catalog via libs/data_suite)
# and the QGIS task bridge (Pwb::QgisProcessing — worker-backed dialogs).
# CONV-23's workflow_contracts leaf is pulled in when the
# kernel slices left it out (UI-09 well_science precedent).
# task_panel_base / prediction_evidence / prediction_task panels are NOT
# re-ported — hosts reuse UI-09's pwb::ui_wellseis::qt widgets.
if(PWB_BUILD_PLATFORM AND TARGET Pwb::Data AND TARGET Pwb::QgisProcessing
   AND TARGET Qt6::Widgets)
    if(NOT TARGET Pwb::WorkflowContracts)
        pwb_add_subdirectory_once(libs/workflow_contracts)
    endif()
    add_subdirectory(libs/ui_review)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "UI-11: libs/ui_review skipped — needs Pwb::Data "
        "(PWB_BUILD_DATA) + Pwb::QgisProcessing (QGIS SDK admission) + "
        "Qt6::Widgets; the Python pages remained the production path until the 2026-09 Python retirement)")
endif()
# END UI-11

# BEGIN CLOSURE-REVIEW — line 09 (审核治理、质量规则与可验证发布):
# libs/closure_review carries the Qt-free QC/versioning/export cores over
# the portable project JSON tree plus the ProjectReviewActions backend
# (ui_review::IReviewActions). Joins platform configures that already
# resolved the review page cluster (Pwb::UiReview — the UI-11 block above),
# the project document stack (Pwb::Project via PWB_BUILD_DATA) and the
# geometry kernels it delegates to (Pwb::UiDataCore validate_ring,
# Pwb::MappingKernel centroid). The app-side install is gated separately in
# apps/paleo_workbench_platform (PWB_WITH_CLOSURE_REVIEW).
if(PWB_BUILD_PLATFORM AND TARGET Pwb::UiReview AND TARGET Pwb::Project
   AND TARGET Pwb::UiDataCore AND TARGET Pwb::MappingKernel)
    add_subdirectory(libs/closure_review)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "CLOSURE-REVIEW: libs/closure_review skipped — needs Pwb::UiReview "
        "(UI-11 block) + Pwb::Project (PWB_BUILD_DATA) + Pwb::UiDataCore + "
        "Pwb::MappingKernel; the review page keeps its honest unbound state")
endif()

# App-side install wiring: this runs after add_subdirectory(apps/...), so
# the guard sees the backend target resolved above (post-hoc target_sources
# like the VIZ-A block). The installer joins the app link closure and turns
# the main_window named blocks on; without the backend the app compiles
# with the review page's honest unbound state.
if(TARGET Pwb::ClosureReview AND TARGET pwb-platform)
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/closure_review_install.cpp
        apps/paleo_workbench_platform/closure_review_install.hpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::ClosureReview)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CLOSURE_REVIEW=1
        # M5: the validation gaps install + the closure_review-backed
        # review-record persistence (both ride this link closure).
        PWB_WITH_M5_VALIDATION=1 PWB_WITH_M5_CLOSURE_REVIEW=1)
endif()
# END CLOSURE-REVIEW

# BEGIN UI-10 — sequence/factor/visualization pages cluster
# (libs/ui_seqviz): Qt-free page state/view models + Qt Widgets shells for
# the 16 taskbook pages. Binds the UI-04 worker contracts (libs/ui_workers)
# plus the UI-03 preview/data core, the CONV-30 job runtime, the
# mapping-document composition session and the well-science curve kernels.
# Joins every configuration that resolves those targets; configs without
# them keep the Python pages as the production path.
if(TARGET Pwb::UiWorkers AND TARGET Pwb::UiDataCore
   AND TARGET Pwb::MappingDocument AND TARGET Pwb::WellScience
   AND TARGET Pwb::JobContracts AND TARGET Pwb::Domain)
    add_subdirectory(libs/ui_seqviz)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "UI-10: libs/ui_seqviz skipped — enable PWB_BUILD_CONV_22 "
        "(worker ports) plus the platform/data/mapping/well slices for "
        "the seqviz pages; the Python pages remained the production path until the 2026-09 Python retirement)")
endif()
# END UI-10

# BEGIN UI-14 — root-controllers slice (libs/ui_controllers): Qt-free
# cores of the six paleo_workbench/ui root controllers (selection bus +
# view coordination, map actions, data lifecycle, project lifecycle +
# three-phase save worker, cross-page workflow) plus thin Qt Widgets
# shells (JobOwner-backed workers, stock-dialog binds). Same gating
# model as UI-09/10/11: no per-slice option; the library joins platform
# configures that already resolved the data catalog (Pwb::Catalog via
# libs/data_suite or libs/catalog), the project document stack
# (Pwb::Project), the UI-04 worker contracts (Pwb::UiWorkers), the UI-01
# shell substrate + UI-03 data core (Pwb::UiShell + Pwb::UiDataCore),
# the recompute planner (Pwb::WorkflowRuntime), the spatial-result gate
# (Pwb::Prediction) and the tool registries (Pwb::ToolPolicy +
# Pwb::UiWorkstation). Application-shell wiring stays a later
# integration slice — these targets only expose the seams it binds.
if(PWB_BUILD_PLATFORM AND TARGET Pwb::UiWorkers AND TARGET Pwb::UiDataCore
   AND TARGET Pwb::UiShell AND TARGET Pwb::UiWorkstation
   AND TARGET Pwb::Catalog AND TARGET Pwb::Project
   AND TARGET Pwb::WorkflowRuntime AND TARGET Pwb::Prediction
   AND TARGET Pwb::ToolPolicy)
    add_subdirectory(libs/ui_controllers)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "UI-14: libs/ui_controllers skipped — needs Pwb::UiWorkers + "
        "Pwb::UiDataCore + Pwb::UiShell + Pwb::UiWorkstation + "
        "Pwb::Catalog + Pwb::Project + Pwb::WorkflowRuntime + "
        "Pwb::Prediction + Pwb::ToolPolicy; the Python controllers "
        "remained the production path until the 2026-09 Python retirement)")
endif()
# END UI-14

# BEGIN cpp-close-01-test — the data.catalog_closure acceptance test.
# tests/cpp/data/CMakeLists.txt probes for Pwb::UiControllers at the
# data-suite mount, which sits ABOVE this line: the probe always evaluated
# before libs/ui_controllers existed and the test silently never joined
# any configuration (the same ordering trap the apps slice hit and fixed
# by relocating post-hoc — see the cpp-close-01 block below). Register it
# here instead, once its targets are guaranteed to exist.
if(BUILD_TESTING AND PWB_BUILD_CATALOG_CLOSURE
        AND TARGET Pwb::UiControllers AND TARGET Pwb::UiDataCore
        AND TARGET Pwb::Catalog AND TARGET Pwb::Project
        AND NOT TARGET data_catalog_closure)
    add_executable(data_catalog_closure
        tests/cpp/data/catalog_closure_test.cpp
        tests/cpp/data/test_main.cpp
        apps/paleo_workbench_platform/closure_catalog_service.cpp
        apps/paleo_workbench_platform/closure_catalog_install.cpp)
    target_compile_features(data_catalog_closure PRIVATE cxx_std_20)
    target_include_directories(data_catalog_closure PRIVATE
        tests/cpp/data
        apps/paleo_workbench_platform
        libs/ui_review/include)
    target_link_libraries(data_catalog_closure PRIVATE
        Pwb::Data Pwb::Catalog Pwb::Project Pwb::Workspace Pwb::Domain
        Pwb::UiControllers Pwb::UiDataCore)
    if(MSVC)
        target_compile_options(data_catalog_closure PRIVATE /utf-8 /W4 /permissive-)
    endif()
    add_test(NAME data.catalog_closure COMMAND data_catalog_closure)
    set_tests_properties(data.catalog_closure PROPERTIES TIMEOUT 300)
endif()
# END cpp-close-01-test

# BEGIN UI-13/14 seam — linked_workspace panel, post-hoc. The gate inside
# libs/ui_composite (processed at the UI-13 mount, far above) can never see
# Pwb::UiControllersQt because that target is only created by the UI-14
# mount right above — so the panel never compiled and the smoke test's
# PWB_HAVE_LINKED_WORKSPACE half was silently skipped (#1444).
if(TARGET pwb_ui_composite_qt AND TARGET Pwb::UiControllersQt)
    target_sources(pwb_ui_composite_qt PRIVATE
        libs/ui_composite/src/linked_workspace.cpp
        libs/ui_composite/include/pwb/ui_composite/linked_workspace.hpp)
    target_link_libraries(pwb_ui_composite_qt PUBLIC
        Pwb::UiControllersQt)
    if(TARGET ui_composite.qt_widgets_smoke)
        target_compile_definitions(ui_composite.qt_widgets_smoke
            PRIVATE PWB_HAVE_LINKED_WORKSPACE=1)
    endif()
endif()
# END UI-13/14 seam

# BEGIN UI-16 — visual-QA slice (libs/ui_visualqa): Qt-free check/state/
# snapshot cores + thin Qt Widgets shells for the visual_qa_v{6..11}.py
# harness semantics + the non-production dual-volume overlay prototype.
# Same gating model as UI-09..14: no per-slice option; the library joins
# platform configures that already resolved the widget libraries the V11
# builders reuse (Pwb::UiShellQt command palette, Pwb::UiWellseisQt task/
# seismic panels, Pwb::UiWorkstationQt inspector/task center,
# Pwb::UiWidgets state surfaces, Pwb::PlatformServices theme service) —
# the Python harness remains the production path without them. Heavy
# host surfaces (AppShell / DataPage / MappingStageBar+Panel) stay
# injected seams — the slice never fakes them.
if(PWB_BUILD_PLATFORM AND TARGET Qt6::Widgets
   AND TARGET Pwb::UiShellQt AND TARGET Pwb::UiWellseisQt
   AND TARGET Pwb::UiWorkstationQt AND TARGET Pwb::UiWidgets
   AND TARGET Pwb::PlatformServices AND TARGET Pwb::ToolPolicy
   AND TARGET Pwb::Domain)
    add_subdirectory(libs/ui_visualqa)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "UI-16: libs/ui_visualqa skipped — needs Qt6::Widgets + "
        "Pwb::UiShellQt + Pwb::UiWellseisQt + Pwb::UiWorkstationQt + "
        "Pwb::UiWidgets + Pwb::PlatformServices + Pwb::ToolPolicy + "
        "Pwb::Domain; the Python visual-QA harness remains the "
        "production path")
endif()
# END UI-16

# BEGIN UI-15 — root-canvas slice (libs/ui_canvas): Qt-free semantic
# cores (render-backend contract/helpers, layer scene, layer tree,
# properties payload, symbology request/result, export spec, snapshot
# encoder) + Qt Widgets shells (UnifiedMapCanvas, NativeMapCanvas +
# raster controller, NativeLayerTree, properties dialog, export worker,
# preview dialog) + the QGIS-coupled surfaces (snapshot codec,
# QgisSnapshotRenderBackend, symbology bridge over the vendored bridge
# TUs). Same gating model as UI-09/10/11/14: no per-slice option; the
# library joins platform configures that already resolved the map/
# widgets/preview/job closures. The CONV-27C cartography leaf is pulled
# in when the kernel slices left it out (UI-09 well_science precedent).
# The application shell stays unwired — the targets only expose the
# seams it binds.
if(PWB_BUILD_PLATFORM AND TARGET Pwb::UiMap AND TARGET Pwb::UiWidgets
   AND TARGET Pwb::UiPagesPreviewQt AND TARGET Pwb::QgisProcessing)
    if(NOT TARGET Pwb::Cartography)
        pwb_add_subdirectory_once(libs/cartography)
    endif()
    add_subdirectory(libs/ui_canvas)
elseif(PWB_BUILD_PLATFORM)
    message(STATUS
        "UI-15: libs/ui_canvas skipped — needs Pwb::UiMap + "
        "Pwb::UiWidgets + Pwb::UiPagesPreviewQt + Pwb::QgisProcessing "
        "(QGIS SDK admission); the Python canvases remain the "
        "production path")
endif()
# END UI-15
# BEGIN VIZ-B
# Cross-well correlation / well-tie viz cores (completion-plan §V3):
# Qt-free tops/picks models, auto-section planner, seismic tie tables,
# wavelet/synthetic/calibration/auto-tie numeric kernels in
# libs/visualization/src/{cross_well,well_tie} + their Qt Widgets halves
# where Qt6::Widgets already resolved. The option is a plain switch so an
# OFF configuration works everywhere (ON/OFF configure parity is part of
# this line's acceptance); the app-side wiring additionally requires
# Pwb::UiWorkers + Pwb::UiWellseisQt (apps/.../CMakeLists.txt VIZ-B
# block, PWB_WITH_VIZ_B).
option(PWB_BUILD_VIZ_B
    "Build the cross-well correlation & well-tie viz cores (line B)" ON)
if(PWB_BUILD_VIZ_B)
    if(NOT TARGET Pwb::Domain)
        pwb_add_subdirectory_once(libs/domain)
    endif()
    # well_tie first: the cross-well core links Pwb::VisualizationWellTie.
    add_subdirectory(libs/visualization/src/well_tie)
    add_subdirectory(libs/visualization/src/cross_well)
endif()

# VIZ-B app-side dock wiring lives HERE (root, after the viz cores) — the
# apps/paleo_workbench_platform subdirectory is processed before the
# cross_well/well_tie/ui_workers/ui_wellseis slices exist, so a TARGET-gated
# block inside it could never fire. Same post-slices pattern as UI-17 below.
if(TARGET pwb-platform
   AND TARGET Pwb::VisualizationCrossWellQt
   AND TARGET Pwb::VisualizationWellTieQt
   AND TARGET Pwb::UiWorkers AND TARGET Pwb::UiWellseisQt)
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/viz_b_cross_well_dock.cpp)
    target_link_libraries(pwb-platform PRIVATE
        Pwb::VisualizationCrossWellQt Pwb::VisualizationWellTieQt
        Pwb::UiWorkers Pwb::UiWellseisQt)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_VIZ_B=1)
endif()
# END VIZ-B

# BEGIN 05 (LAS real-load path) — post-hoc: Pwb::UiWorkersWleLoad exists
# only after the ui_workers slice above; the apps-local gate could never
# fire, keeping the cross-well dock's real LAS loading permanently in the
# "LAS 解析内核未接入" degraded state (#1444).
if(TARGET Pwb::UiWorkersWleLoad AND TARGET Pwb::IngestLasWle
        AND TARGET pwb-platform)
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/viz_b_well_source.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::UiWorkersWleLoad)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_VIZ_B_LAS=1)
endif()
# END 05

# BEGIN UI-17 — W5 application-shell wiring
# (apps/paleo_workbench_platform/app_shell.*): the page-navigation
# composition root — WorkstationFrame + CompositeDocument hosting the
# session canvas + the hub page stack + palette/status bar — joins the
# platform binary only when every UI slice target it consumes is in the
# build closure. Evaluated HERE (after all libs/ui_* add_subdirectory
# blocks) because apps/paleo_workbench_platform is added before the
# wellseis/review/seqviz slices. Without them the window keeps the direct
# session-canvas central widget — an honest reduced shell, never a
# partially-faked AppShell.
if(TARGET pwb-platform
   AND TARGET Pwb::UiWorkstationQt AND TARGET Pwb::UiCompositeQt
   AND TARGET Pwb::UiShellQt AND TARGET Pwb::UiPagesDataQt
   AND TARGET Pwb::UiMapQgis AND TARGET Pwb::UiReviewQt
   AND TARGET Pwb::UiSeqvizQt AND TARGET Pwb::UiWellseisQt
   AND TARGET Pwb::UiRibbonQt)
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/app_shell.cpp
        apps/paleo_workbench_platform/validation_workspace_page.cpp
        apps/paleo_workbench_platform/factor_atlas_panel.cpp
        apps/paleo_workbench_platform/compilation_layer_panel.cpp
        apps/paleo_workbench_platform/profile_settings_panel.cpp
        apps/paleo_workbench_platform/reference_legend_panel.cpp
        apps/paleo_workbench_platform/factor_reference_strip.cpp
        apps/paleo_workbench_platform/workspace_compose.cpp
        apps/paleo_workbench_platform/ribbon_command_install.cpp
        apps/paleo_workbench_platform/comparison_view.cpp
        apps/paleo_workbench_platform/review_disposition_panel.cpp
        apps/paleo_workbench_platform/m5_validation_install.cpp
        apps/paleo_workbench_platform/layout_compose_panel.cpp
        apps/paleo_workbench_platform/layout_compose_panel.hpp
        apps/paleo_workbench_platform/m5_compose_install.cpp
        apps/paleo_workbench_platform/data_lineage_panel.cpp
        apps/paleo_workbench_platform/m5_data_install.cpp
        apps/paleo_workbench_platform/factor_method_config.cpp
        apps/paleo_workbench_platform/factor_method_dialogs.cpp
        apps/paleo_workbench_platform/factor_method_dialogs.hpp)
    target_link_libraries(pwb-platform PRIVATE
        Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
        Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt Pwb::UiSeqvizQt
        Pwb::UiWellseisQt Pwb::UiRibbonQt Pwb::UiWidgets
        Pwb::Visualization)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_APP_SHELL=1)
    # BEGIN PWB-V14-THREE-STAGE — product wiring. This is PRODUCTION
    # surface, not test surface: a BUILD_TESTING=OFF release configure
    # must still ship the three-stage workbench (it used to nest inside
    # if(BUILD_TESTING) below and silently vanish) (#1444).
    if(TARGET Pwb::UiStageflowQt)
        target_sources(pwb-platform PRIVATE
            apps/paleo_workbench_platform/stage_flow_install.cpp
            apps/paleo_workbench_platform/constraint_authoring.cpp)
        target_link_libraries(pwb-platform PRIVATE Pwb::UiStageflowQt)
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_STAGE_FLOW=1)
        if(TARGET Pwb::UiControllersQt)
            target_link_libraries(pwb-platform PRIVATE
                Pwb::UiControllers Pwb::UiControllersQt)
            target_compile_definitions(pwb-platform PRIVATE
                PWB_WITH_UI_CONTROLLERS=1)
        endif()
    endif()
    # END PWB-V14-THREE-STAGE (product wiring; test battery below)
    if(BUILD_TESTING)
        # App-shell wiring battery: the full shell path compiles the real
        # MainWindow + AppShell with the same define the app gets — the
        # reduced direct-canvas fallback stays covered by the other
        # MainWindow tests (they compile without PWB_WITH_APP_SHELL).
        add_executable(platform_app_shell
            tests/cpp/platform/test_app_shell.cpp
            apps/paleo_workbench_platform/main_window.cpp
            apps/paleo_workbench_platform/app_context.cpp
            apps/paleo_workbench_platform/diagnostics.cpp
            apps/paleo_workbench_platform/app_shell.cpp
            apps/paleo_workbench_platform/validation_workspace_page.cpp
            apps/paleo_workbench_platform/factor_atlas_panel.cpp
            apps/paleo_workbench_platform/compilation_layer_panel.cpp
            apps/paleo_workbench_platform/profile_settings_panel.cpp
            apps/paleo_workbench_platform/reference_legend_panel.cpp
            apps/paleo_workbench_platform/factor_reference_strip.cpp
            apps/paleo_workbench_platform/workspace_compose.cpp
            apps/paleo_workbench_platform/ribbon_command_install.cpp
            apps/paleo_workbench_platform/comparison_view.cpp
            apps/paleo_workbench_platform/review_disposition_panel.cpp
            apps/paleo_workbench_platform/m5_validation_install.cpp
            apps/paleo_workbench_platform/data_lineage_panel.cpp
            apps/paleo_workbench_platform/m5_data_install.cpp)
        if(COMMAND pwb_link_job_runtime)
            pwb_link_job_runtime(platform_app_shell)
        endif()
        set_target_properties(platform_app_shell PROPERTIES AUTOMOC ON)
        target_compile_features(platform_app_shell PRIVATE cxx_std_20)
        target_include_directories(platform_app_shell PRIVATE
            tests/cpp/platform
            apps/paleo_workbench_platform
            ${CMAKE_BINARY_DIR}/generated)
        target_link_libraries(platform_app_shell PRIVATE
    Pwb::QgisProcessing
            Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
            Pwb::PlatformServices
            Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
            Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt
            Pwb::UiSeqvizQt Pwb::UiWellseisQt Pwb::UiRibbonQt
            Pwb::Visualization
            Pwb::UiWidgets)
            target_compile_definitions(platform_app_shell PRIVATE
            PWB_WITH_APP_SHELL=1
            PWB_TEST_SRC_DIR="${CMAKE_SOURCE_DIR}/tests/cpp/platform")
        if(PWB_BUILD_CONV_27)
            target_link_libraries(platform_app_shell PRIVATE Pwb::UiWorkbench)
            target_compile_definitions(platform_app_shell PRIVATE
                PWB_WITH_CONV_27=1)
        endif()
        # Pwb::Application exports PWB_WITH_DATA_INTEGRATION PUBLIC once the
        # B/C closure exists; main_window.cpp then references the
        # shell_project_actions symbols (same gate as
        # platform_three_stage_flow below).
        if(TARGET Pwb::Data AND TARGET Pwb::Science
           AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
            target_sources(platform_app_shell PRIVATE
                apps/paleo_workbench_platform/shell_project_actions.cpp
                apps/paleo_workbench_platform/constraint_authoring.cpp)
        endif()
        add_test(NAME platform.app_shell COMMAND platform_app_shell)
        set_tests_properties(platform.app_shell PROPERTIES
            ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
            TIMEOUT 300)

        # BEGIN PWB-V14-THREE-STAGE — integration battery. The PRODUCT
        # wiring (sources + PWB_WITH_STAGE_FLOW for pwb-platform) now
        # lives above, outside if(BUILD_TESTING); this half is the test
        # executable only.
        if(TARGET Pwb::UiStageflowQt)
            # Integration battery: the full shell WITH the stage-flow
            # install compiled in, same defines as the app.
            add_executable(platform_three_stage_flow
                tests/cpp/platform/test_three_stage_flow.cpp
                apps/paleo_workbench_platform/main_window.cpp
                apps/paleo_workbench_platform/app_context.cpp
                apps/paleo_workbench_platform/diagnostics.cpp
                apps/paleo_workbench_platform/app_shell.cpp
                apps/paleo_workbench_platform/stage_flow_install.cpp
                apps/paleo_workbench_platform/validation_workspace_page.cpp
                apps/paleo_workbench_platform/factor_atlas_panel.cpp
                apps/paleo_workbench_platform/compilation_layer_panel.cpp
                apps/paleo_workbench_platform/profile_settings_panel.cpp
                apps/paleo_workbench_platform/reference_legend_panel.cpp
                apps/paleo_workbench_platform/factor_reference_strip.cpp
                apps/paleo_workbench_platform/workspace_compose.cpp
                apps/paleo_workbench_platform/ribbon_command_install.cpp
                apps/paleo_workbench_platform/comparison_view.cpp
                apps/paleo_workbench_platform/review_disposition_panel.cpp
                apps/paleo_workbench_platform/m5_validation_install.cpp
                apps/paleo_workbench_platform/data_lineage_panel.cpp
                apps/paleo_workbench_platform/m5_data_install.cpp)
            if(COMMAND pwb_link_job_runtime)
                pwb_link_job_runtime(platform_three_stage_flow)
            endif()
            set_target_properties(platform_three_stage_flow
                PROPERTIES AUTOMOC ON)
            target_compile_features(platform_three_stage_flow
                PRIVATE cxx_std_20)
            target_include_directories(platform_three_stage_flow PRIVATE
                tests/cpp/platform
                apps/paleo_workbench_platform
                ${CMAKE_BINARY_DIR}/generated)
            target_link_libraries(platform_three_stage_flow PRIVATE
    Pwb::QgisProcessing
                Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
                Pwb::PlatformServices Pwb::UiStageflowQt
                Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
                Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt
                Pwb::UiSeqvizQt Pwb::UiWellseisQt Pwb::UiRibbonQt
                Pwb::Visualization
                Pwb::UiWidgets Pwb::FactorHost)
                target_compile_definitions(platform_three_stage_flow PRIVATE
                PWB_WITH_APP_SHELL=1
                PWB_WITH_STAGE_FLOW=1
                PWB_TEST_SRC_DIR="${CMAKE_SOURCE_DIR}/tests/cpp/platform")
            if(TARGET Pwb::UiControllersQt)
                target_link_libraries(platform_three_stage_flow PRIVATE
                    Pwb::UiControllers Pwb::UiControllersQt)
                target_compile_definitions(platform_three_stage_flow
                    PRIVATE PWB_WITH_UI_CONTROLLERS=1)
            endif()
            # Mirror pwb_application's own adapter condition exactly: the
            # data-integration surface (PwbDataStore::open, project store)
            # compiles only with the full B/C closure; a reduced configure
            # keeps the test honest rather than link-broken.
            if(TARGET Pwb::Data AND TARGET Pwb::Science
               AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
                target_link_libraries(platform_three_stage_flow PRIVATE
                    Pwb::Data)
                target_compile_definitions(platform_three_stage_flow
                    PRIVATE PWB_WITH_DATA_INTEGRATION=1)
                # main_window.cpp references the 12-line project actions
                # once the data closure is in (platform_app_shell parity).
                target_sources(platform_three_stage_flow PRIVATE
                    apps/paleo_workbench_platform/shell_project_actions.cpp
                    apps/paleo_workbench_platform/constraint_authoring.cpp)
            endif()
            add_test(NAME platform.three_stage_flow
                     COMMAND platform_three_stage_flow)

        # V14 constraint authoring chain regression (#1446): create →
        # digitize → harvest → document truth, through the real window.
        add_executable(platform_constraint_authoring
            tests/cpp/platform/test_constraint_authoring.cpp
            apps/paleo_workbench_platform/main_window.cpp
            apps/paleo_workbench_platform/app_context.cpp
            apps/paleo_workbench_platform/diagnostics.cpp
            apps/paleo_workbench_platform/app_shell.cpp
            apps/paleo_workbench_platform/stage_flow_install.cpp
            apps/paleo_workbench_platform/constraint_authoring.cpp
            apps/paleo_workbench_platform/validation_workspace_page.cpp
            apps/paleo_workbench_platform/factor_atlas_panel.cpp
            apps/paleo_workbench_platform/compilation_layer_panel.cpp
            apps/paleo_workbench_platform/profile_settings_panel.cpp
            apps/paleo_workbench_platform/reference_legend_panel.cpp
            apps/paleo_workbench_platform/factor_reference_strip.cpp
            apps/paleo_workbench_platform/workspace_compose.cpp
            apps/paleo_workbench_platform/ribbon_command_install.cpp
            apps/paleo_workbench_platform/comparison_view.cpp
            apps/paleo_workbench_platform/review_disposition_panel.cpp
            apps/paleo_workbench_platform/m5_validation_install.cpp
            apps/paleo_workbench_platform/data_lineage_panel.cpp
            apps/paleo_workbench_platform/m5_data_install.cpp)
        if(COMMAND pwb_link_job_runtime)
            pwb_link_job_runtime(platform_constraint_authoring)
        endif()
        set_target_properties(platform_constraint_authoring
            PROPERTIES AUTOMOC ON)
        target_compile_features(platform_constraint_authoring
            PRIVATE cxx_std_20)
        target_include_directories(platform_constraint_authoring PRIVATE
            tests/cpp/platform
            apps/paleo_workbench_platform
            ${CMAKE_BINARY_DIR}/generated)
        target_link_libraries(platform_constraint_authoring PRIVATE
    Pwb::QgisProcessing
            Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
            Pwb::PlatformServices Pwb::UiStageflowQt
            Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
            Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt
            Pwb::UiSeqvizQt Pwb::UiWellseisQt Pwb::UiRibbonQt
            Pwb::Visualization
            Pwb::UiWidgets Pwb::FactorHost)
            target_compile_definitions(platform_constraint_authoring PRIVATE
            PWB_WITH_APP_SHELL=1
            PWB_WITH_STAGE_FLOW=1
            PWB_TEST_SRC_DIR="${CMAKE_SOURCE_DIR}/tests/cpp/platform")
        if(TARGET Pwb::UiControllersQt)
            target_link_libraries(platform_constraint_authoring PRIVATE
                Pwb::UiControllers Pwb::UiControllersQt)
            target_compile_definitions(platform_constraint_authoring
                PRIVATE PWB_WITH_UI_CONTROLLERS=1)
        endif()
        if(TARGET Pwb::Data AND TARGET Pwb::Science
           AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
            target_link_libraries(platform_constraint_authoring PRIVATE
                Pwb::Data)
            target_compile_definitions(platform_constraint_authoring
                PRIVATE PWB_WITH_DATA_INTEGRATION=1)
            target_sources(platform_constraint_authoring PRIVATE
                apps/paleo_workbench_platform/shell_project_actions.cpp)
        endif()
        add_test(NAME platform.constraint_authoring
                 COMMAND platform_constraint_authoring)
        set_tests_properties(platform.constraint_authoring PROPERTIES
            ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
            TIMEOUT 300)

            set_tests_properties(platform.three_stage_flow PROPERTIES
                ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
                ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
                TIMEOUT 300)
        endif()
        # END PWB-V14-THREE-STAGE

        # BEGIN CLOSURE-REVIEW (line 09)
        # Review/publish closure install battery: the real MainWindow +
        # AppShell path WITH the closure installer compiled in
        # (PWB_WITH_CLOSURE_REVIEW turns the main_window named blocks on),
        # plus the document save seam and a reopen traceability round.
        # Needs the project-data closure (Pwb::Data) for the store.
        if(TARGET Pwb::ClosureReview AND TARGET Pwb::Data)
            # BEGIN V14-COMPILATION-PUBLISH — baseline link fix (same shape
            # as platform_closure_mapping above): main_window.cpp references
            # shell_project_actions (12-line #1421) but this target's source
            # list never carried the TU.
            add_executable(platform_closure_review_install
                tests/cpp/platform/test_closure_review_install.cpp
                apps/paleo_workbench_platform/main_window.cpp
                apps/paleo_workbench_platform/app_context.cpp
                apps/paleo_workbench_platform/diagnostics.cpp
                apps/paleo_workbench_platform/app_shell.cpp
                apps/paleo_workbench_platform/shell_project_actions.cpp
                apps/paleo_workbench_platform/closure_review_install.cpp
                apps/paleo_workbench_platform/validation_workspace_page.cpp
                apps/paleo_workbench_platform/factor_atlas_panel.cpp
                apps/paleo_workbench_platform/compilation_layer_panel.cpp
                apps/paleo_workbench_platform/profile_settings_panel.cpp
                apps/paleo_workbench_platform/reference_legend_panel.cpp
                apps/paleo_workbench_platform/factor_reference_strip.cpp
                apps/paleo_workbench_platform/workspace_compose.cpp
                apps/paleo_workbench_platform/ribbon_command_install.cpp
                apps/paleo_workbench_platform/comparison_view.cpp
                apps/paleo_workbench_platform/review_disposition_panel.cpp
                apps/paleo_workbench_platform/m5_validation_install.cpp
                apps/paleo_workbench_platform/data_lineage_panel.cpp
                apps/paleo_workbench_platform/m5_data_install.cpp
                apps/paleo_workbench_platform/factor_method_config.cpp
                apps/paleo_workbench_platform/factor_method_dialogs.cpp
                apps/paleo_workbench_platform/factor_method_dialogs.hpp
                apps/paleo_workbench_platform/job_center.cpp)
            # END V14-COMPILATION-PUBLISH
            if(COMMAND pwb_link_job_runtime)
                pwb_link_job_runtime(platform_closure_review_install)
            endif()
            set_target_properties(platform_closure_review_install
                PROPERTIES AUTOMOC ON)
            target_compile_features(platform_closure_review_install
                PRIVATE cxx_std_20)
            target_include_directories(platform_closure_review_install PRIVATE
                tests/cpp/platform
                apps/paleo_workbench_platform
                ${CMAKE_BINARY_DIR}/generated)
            target_link_libraries(platform_closure_review_install PRIVATE
                Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
                Pwb::PlatformServices Pwb::Data Pwb::ClosureReview
                Pwb::QgisProcessing
                Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
                Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt
                Pwb::UiSeqvizQt Pwb::UiWellseisQt Pwb::UiRibbonQt
                Pwb::Visualization
                Pwb::UiWidgets)
                target_compile_definitions(platform_closure_review_install PRIVATE
                PWB_WITH_APP_SHELL=1
                PWB_WITH_CLOSURE_REVIEW=1
                PWB_WITH_M5_VALIDATION=1
                PWB_WITH_M5_CLOSURE_REVIEW=1
                PWB_TEST_SRC_DIR="${CMAKE_SOURCE_DIR}/tests/cpp/platform")
            add_test(NAME platform.closure_review_install
                     COMMAND platform_closure_review_install)
            set_tests_properties(platform.closure_review_install PROPERTIES
                ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
                ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
                TIMEOUT 300)
        endif()
        # END CLOSURE-REVIEW
    endif()
elseif(PWB_BUILD_PLATFORM AND TARGET pwb-platform)
    message(STATUS
        "UI-17: app_shell skipped — needs Pwb::UiWorkstationQt + "
        "Pwb::UiCompositeQt + Pwb::UiShellQt + Pwb::UiPagesDataQt + "
        "Pwb::UiMapQgis + Pwb::UiReviewQt + Pwb::UiSeqvizQt + "
        "Pwb::UiWellseisQt + Pwb::UiRibbonQt; the direct-canvas shell "
        "remains")
endif()

# END UI-17

# BEGIN CLOSURE-SCIENCE — line-03 assembly (runs after UI-17 so the app
# target and every page target exist). Adds libs/closure_science (+Qt
# binding) and installs the production prediction-page binding into the
# platform binary via the main_window BEGIN/END CLOSURE-SCIENCE block.
# Write lease: 03-line.json named_block_leases (12 assembles).
if(PWB_BUILD_CLOSURE_SCIENCE)
    if(NOT TARGET pwb_closure_science)
        add_subdirectory(libs/closure_science)
    endif()
    if(TARGET pwb-platform AND TARGET pwb_closure_science_qt
       AND TARGET Pwb::UiWellseisQt)
        target_link_libraries(pwb-platform PRIVATE Pwb::ClosureScienceQt)
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_CLOSURE_SCIENCE=1)
    endif()
    if(BUILD_TESTING AND TARGET pwb_closure_science_qt
       AND TARGET platform_app_shell)
        target_link_libraries(platform_app_shell PRIVATE
            Pwb::ClosureScienceQt)
        target_compile_definitions(platform_app_shell PRIVATE
            PWB_WITH_CLOSURE_SCIENCE=1)
    endif()
endif()
# END CLOSURE-SCIENCE

# BEGIN CPP-CLOSE-12 — shell project-actions integration slice.
# apps/paleo_workbench_platform/shell_project_actions.* carries the
# production bodies for the AppShell app-bar surfaces (save / open-sample /
# properties). It needs the data closure (the same Pwb::Data presence that
# defines PWB_WITH_DATA_INTEGRATION on Pwb::Application) — without it the
# window keeps its honest reduced surface. The preview-settings surface
# additionally needs the UI-07/UI-15 Qt closure (Pwb::UiCanvas pulls
# Pwb::UiPagesPreviewQt).
if(TARGET pwb-platform)
    # V14-THREE-STAGE-UX: Pwb::Data alone does NOT imply
    # PWB_WITH_DATA_INTEGRATION (that define lands on Pwb::Application only
    # with the full B/C adapter closure); mirror the adapter condition or
    # shell_project_actions.cpp references surfaces the reduced build never
    # declared.
    if(TARGET Pwb::Data AND TARGET Pwb::Science AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
        target_sources(pwb-platform PRIVATE
            apps/paleo_workbench_platform/shell_project_actions.cpp)
    endif()
    if(TARGET Pwb::UiCanvas)
        target_link_libraries(pwb-platform PRIVATE Pwb::UiCanvas)
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_UI_PAGES_PREVIEW_QT=1)
    endif()
endif()
if(TARGET platform_app_shell)
    if(TARGET Pwb::Data AND TARGET Pwb::Science AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
        target_sources(platform_app_shell PRIVATE
            apps/paleo_workbench_platform/shell_project_actions.cpp)
    endif()
    if(TARGET Pwb::UiCanvas)
        target_link_libraries(platform_app_shell PRIVATE Pwb::UiCanvas)
        target_compile_definitions(platform_app_shell PRIVATE
            PWB_WITH_UI_PAGES_PREVIEW_QT=1)
    endif()
    # cpp-close-12 — shell project-actions battery: the four deferred
    # surfaces against a real store (save/reopen roundtrip, sample
    # bootstrap through the run lifecycle, properties summary). Needs the
    # full B/C adapter closure (the store surface under test).
    if(BUILD_TESTING AND TARGET Pwb::Data AND TARGET Pwb::Science
       AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
        add_executable(platform_shell_project_actions
            tests/cpp/platform/test_shell_project_actions.cpp
            apps/paleo_workbench_platform/main_window.cpp
            apps/paleo_workbench_platform/app_context.cpp
            apps/paleo_workbench_platform/diagnostics.cpp)
        if(TARGET Pwb::Data AND TARGET Pwb::Science AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
            target_sources(platform_shell_project_actions PRIVATE
                apps/paleo_workbench_platform/shell_project_actions.cpp)
        endif()
        if(COMMAND pwb_link_job_runtime)
            pwb_link_job_runtime(platform_shell_project_actions)
        endif()
        set_target_properties(platform_shell_project_actions PROPERTIES
            AUTOMOC ON)
        target_compile_features(platform_shell_project_actions PRIVATE
            cxx_std_20)
        target_include_directories(platform_shell_project_actions PRIVATE
            tests/cpp/platform
            apps/paleo_workbench_platform
            ${CMAKE_BINARY_DIR}/generated)
        target_link_libraries(platform_shell_project_actions PRIVATE
            Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
            Pwb::PlatformServices Pwb::Data Pwb::Catalog)
        if(TARGET Pwb::UiCanvas)
            target_link_libraries(platform_shell_project_actions PRIVATE
                Pwb::UiCanvas)
            target_compile_definitions(platform_shell_project_actions
                PRIVATE PWB_WITH_UI_PAGES_PREVIEW_QT=1)
        endif()
        target_compile_definitions(platform_shell_project_actions PRIVATE
            PWB_TEST_SRC_DIR="${CMAKE_SOURCE_DIR}/tests/cpp/platform")
        add_test(NAME platform.shell_project_actions
                 COMMAND platform_shell_project_actions)
        set_tests_properties(platform.shell_project_actions PROPERTIES
            ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
            TIMEOUT 300)
    endif()
endif()
# END CPP-CLOSE-12

# BEGIN VIZ-A — line-A (LAS/WLE convergence + well-log drawing
# differentials). This block runs after science_suite (:327), the platform
# app (:703) and ui_workers (:725), so every guard below sees the real
# target set regardless of which earlier block added a library.
#
# (a) Bridge-ordering heal: when PWB_BUILD_DATA pulled libs/ingest in early
#     (data_suite adds it at :322 BEFORE science_suite introduces
#     WellLog::IO), the ingest VIZ-A bridge target could not exist yet.
#     Re-enter the directory in bridge-only mode to build it now.
if(TARGET pwb_ingest AND TARGET WellLog::IO AND NOT TARGET pwb_ingest_las_wle)
    set(VIZ_A_LATE_BRIDGE ON)
    add_subdirectory(libs/ingest ${CMAKE_CURRENT_BINARY_DIR}/ingest-late-bridge)
    unset(VIZ_A_LATE_BRIDGE)
endif()
#
# (b) App production wiring: preview provider + JobCenter-backed LAS loads
#     (apps/paleo_workbench_platform/viz_a_install.* guarded by
#     PWB_WITH_VIZ_A in main_window.cpp). The app target exists only under
#     PWB_BUILD_PLATFORM; compile-covered by run-viz-a-gate.sh step 7.
if(TARGET pwb-platform AND TARGET Pwb::IngestLasWle
   AND TARGET Pwb::UiWorkersWleLoad AND TARGET Pwb::QgisProcessing)
    target_sources(pwb-platform PRIVATE apps/paleo_workbench_platform/viz_a_install.cpp)
    target_link_libraries(pwb-platform PRIVATE
        Pwb::IngestLasWle Pwb::UiWorkersWleLoad Pwb::QgisProcessing)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_VIZ_A=1)
endif()
#
# (c) Line-A acceptance tests.
if(BUILD_TESTING AND TARGET Pwb::Ingest AND TARGET Pwb::UiWorkers)
    enable_testing()
    add_subdirectory(tests/cpp/viz_a)
endif()
# END VIZ-A

# BEGIN VIZ-C-host — joint well-seismic host wiring (plan V4). Runs AFTER
# UI-09: the host implements the #1394 JointHostController seam from
# Pwb::UiWellseisQt, which joins the build later than
# apps/paleo_workbench_platform — an existence check inside the app
# directory would silently skip the host (never a fake seam).
if(TARGET pwb-platform AND TARGET Pwb::Geo3DViz
   AND TARGET Pwb::SeismicService AND TARGET Pwb::UiWellseisQt)
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/viz_c_joint_host.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::UiWellseisQt)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_UI_WELLSEIS=1)

    # BEGIN JOINT-ANALYSIS (geoviz final closure) — the 井震联合 3D page
    # analysis hooks. Nested TARGET gate (fail-closed): every kernel lib
    # the hooks call must exist, AND the AppShell composition must be in
    # (the install consumes app_shell->geomodel_page()); otherwise the TU
    # stays out and PWB_WITH_JOINT_ANALYSIS stays undefined so
    # main_window.cpp compiles the page's honest 未接入 fallbacks instead
    # of referencing symbols that would not link (round-1 review: a
    # reduced SEISMIC_VIEWER=OFF configure linked-failed before the
    # define existed).
    if(TARGET Pwb::UiWorkers AND TARGET Pwb::SeismicViewer AND
       TARGET Pwb::GeoModel AND
       TARGET Pwb::UiWorkstationQt AND TARGET Pwb::UiCompositeQt AND
       TARGET Pwb::UiShellQt AND TARGET Pwb::UiPagesDataQt AND
       TARGET Pwb::UiMapQgis AND TARGET Pwb::UiReviewQt AND
       TARGET Pwb::UiSeqvizQt AND
       TARGET Pwb::VisualizationWellTie AND TARGET Pwb::VisualizationCrossWell)
        # Auto-tie runs the real well_tie log-tie kernel on the VIZ-B
        # workspace's LAS curves (cross_well WellColumnData snapshot).
        target_sources(pwb-platform PRIVATE
            apps/paleo_workbench_platform/joint_analysis_install.cpp
            apps/paleo_workbench_platform/horizon_interpretation_io.cpp)
        target_link_libraries(pwb-platform PRIVATE
            Pwb::UiWorkers Pwb::SeismicViewer Pwb::GeoModel Pwb::Interchange
            Pwb::VisualizationWellTie Pwb::VisualizationCrossWell)
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_JOINT_ANALYSIS=1)
    endif()
    # END JOINT-ANALYSIS

    # Runnable production seam: real PWBVOL1 through the tiled service
    # into the joint scene (frozen seismic_io oracle fixture; override by
    # passing a volume path).
    set(VIZ_C_EXAMPLE_VOLUME
        "${CMAKE_CURRENT_SOURCE_DIR}/libs/seismic_io/seismic_io_tests/fixtures/io_oracle_bins.sgy")
    if(EXISTS "${VIZ_C_EXAMPLE_VOLUME}")
        message(STATUS "VIZ-C: joint example volume fixture found")
        add_executable(viz_c_joint_example
            apps/paleo_workbench_platform/examples/viz_c_joint_example.cpp
            apps/paleo_workbench_platform/viz_c_joint_host.cpp
            apps/paleo_workbench_platform/job_center.cpp
            apps/paleo_workbench_platform/viz_c_joint_volume.cpp
            apps/paleo_workbench_platform/viz_c_time_map.cpp)
        if(UNIX AND NOT APPLE)
            # Soft X11 probe (broken-GLX hosts install an X error guard);
            # a missing SDK only drops that guard, never the build.
            find_package(X11)
            if(X11_FOUND)
                target_link_libraries(viz_c_joint_example PRIVATE X11::X11)
                target_compile_definitions(viz_c_joint_example PRIVATE
                    VIZ_C_HAVE_X11=1)
            endif()
        endif()
        set_target_properties(viz_c_joint_example PROPERTIES AUTOMOC ON)
        target_compile_features(viz_c_joint_example PRIVATE cxx_std_20)
        target_link_libraries(viz_c_joint_example PRIVATE
            Pwb::Geo3DViz Pwb::SeismicService Pwb::UiWellseisQt
            Pwb::QgisProcessing Pwb::Visualization Pwb::SeismicIo
            Qt6::Widgets)
        target_include_directories(viz_c_joint_example PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/apps/paleo_workbench_platform)
        target_compile_definitions(viz_c_joint_example PRIVATE
            VIZ_C_EXAMPLE_VOLUME="${VIZ_C_EXAMPLE_VOLUME}"
            PWB_WITH_UI_WELLSEIS=1)
        if(MSVC)
            target_compile_options(viz_c_joint_example PRIVATE /utf-8 /W3)
        else()
            target_compile_options(viz_c_joint_example PRIVATE
                -Wall -Wextra)
        endif()

        # 06 closure — joint3d closure tests (async prep pipeline,
        # multi-fence management, project-scoped state, the product
        # binder over REAL fixture files). Registered here because the
        # targets it needs (Pwb::UiWellseisQt) exist only after the
        # ui_wellseis subdirectory above — the tests/cpp/viz_c block is
        # processed earlier and would silently skip (never a silent test
        # drop).
        add_executable(viz_c_joint3d_closure
            tests/cpp/viz_c/joint3d_closure_test.cpp
            tests/cpp/viz_c/test_main.cpp
            apps/paleo_workbench_platform/viz_c_joint_host.cpp
            apps/paleo_workbench_platform/viz_c_joint_volume.cpp
            apps/paleo_workbench_platform/viz_c_time_map.cpp
            apps/paleo_workbench_platform/closure_joint3d_install.cpp
            apps/paleo_workbench_platform/job_center.cpp)
        set_target_properties(viz_c_joint3d_closure PROPERTIES AUTOMOC ON)
        target_compile_features(viz_c_joint3d_closure PRIVATE cxx_std_20)
        target_link_libraries(viz_c_joint3d_closure PRIVATE
            Pwb::Geo3DViz Pwb::SeismicService Pwb::UiWellseisQt
            Pwb::QgisProcessing Pwb::Visualization Pwb::SeismicIo
            Pwb::Data Pwb::Catalog Qt6::Widgets)
        target_include_directories(viz_c_joint3d_closure PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/cpp/viz_c
            ${CMAKE_CURRENT_SOURCE_DIR}/apps/paleo_workbench_platform)
        target_compile_definitions(viz_c_joint3d_closure PRIVATE
            JOINT3D_FIXTURE_VOLUME="${VIZ_C_EXAMPLE_VOLUME}"
            JOINT3D_REALDATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/realdata"
            PWB_WITH_UI_WELLSEIS=1)
        if(MSVC)
            target_compile_options(viz_c_joint3d_closure PRIVATE /utf-8 /W3)
        else()
            target_compile_options(viz_c_joint3d_closure PRIVATE
                -Wall -Wextra)
        endif()
        add_test(NAME viz_c.joint3d_closure COMMAND viz_c_joint3d_closure)
        set_tests_properties(viz_c.joint3d_closure PROPERTIES TIMEOUT 300
            ENVIRONMENT "MALLOC_CHECK_=3;QT_QPA_PLATFORM=offscreen")

        # geoviz final closure — joint-analysis install tests (hook
        # contract: sidecar persistence, RGB overlay, demo stratal path,
        # real-log auto-tie on the fixture volume).
        if(TARGET Pwb::UiWorkers AND TARGET Pwb::SeismicViewer AND
           TARGET Pwb::GeoModel AND TARGET Pwb::VisualizationWellTie AND
           TARGET Pwb::VisualizationCrossWell)
            add_executable(viz_c_joint_analysis
                tests/cpp/viz_c/joint_analysis_test.cpp
                tests/cpp/viz_c/test_main.cpp
                apps/paleo_workbench_platform/joint_analysis_install.cpp
                apps/paleo_workbench_platform/horizon_interpretation_io.cpp
                apps/paleo_workbench_platform/job_center.cpp
                apps/paleo_workbench_platform/viz_c_joint_host.cpp
                apps/paleo_workbench_platform/viz_c_joint_volume.cpp
                apps/paleo_workbench_platform/viz_c_time_map.cpp)
            set_target_properties(viz_c_joint_analysis PROPERTIES AUTOMOC ON)
            target_compile_features(viz_c_joint_analysis PRIVATE cxx_std_20)
            target_link_libraries(viz_c_joint_analysis PRIVATE
                Pwb::Geo3DViz Pwb::UiWellseisQt Pwb::UiWorkers
                Pwb::SeismicViewer Pwb::GeoModel Pwb::Interchange Pwb::Project
                Pwb::VisualizationWellTie Pwb::VisualizationCrossWell
                Pwb::SeismicService Pwb::QgisProcessing Qt6::Widgets)
            target_include_directories(viz_c_joint_analysis PRIVATE
                ${CMAKE_CURRENT_SOURCE_DIR}/tests/cpp/viz_c
                ${CMAKE_CURRENT_SOURCE_DIR}/apps/paleo_workbench_platform)
            target_compile_definitions(viz_c_joint_analysis PRIVATE
                PWB_WITH_UI_WELLSEIS=1
                JOINT_ANALYSIS_FIXTURE_VOLUME="${VIZ_C_EXAMPLE_VOLUME}")
            if(MSVC)
                target_compile_options(viz_c_joint_analysis PRIVATE
                    /utf-8 /W3)
            else()
                target_compile_options(viz_c_joint_analysis PRIVATE
                    -Wall -Wextra)
            endif()
            add_test(NAME viz_c.joint_analysis COMMAND viz_c_joint_analysis)
            set_tests_properties(viz_c.joint_analysis PROPERTIES TIMEOUT 300
                ENVIRONMENT "MALLOC_CHECK_=3;QT_QPA_PLATFORM=offscreen")
        endif()
    endif()
endif()
# END VIZ-C-host

# BEGIN VIZ-E — charts drawing kernel + Qt widgets (libs/viz_charts), plan
# V6 of docs/development/cpp-geoviz-completion-plan.md: the geoviz_plots
# drawing half (chart/surface/fence/analytics/factor presentation) with a
# Qt-free core and QPainter widget layer. Joins platform configures (Qt6
# comes from the platform block's find_package); the Qt-free core carries
# its own oracle replay test.
if(PWB_BUILD_PLATFORM)
    add_subdirectory(libs/viz_charts)
endif()

# BEGIN CLOSURE-MAPPING (late) — 08-line closure battery. Registered after
# the VIZ-E charts block so Pwb::VizCharts exists (the contour extraction
# kernel the preparation seam binds). Guarded on the full closure; LayoutExport
# (CONV-29, default OFF) is intentionally not required — the composition
# export engine wiring is a registered follow-up.
# V14-THREE-STAGE-UX: Pwb::Data added to the guard — the install's
# store_getter returns PwbDataStore (a data-integration surface; the
# define lands on Pwb::Application only with the full B/C adapter
# closure, so the mount mirrors that condition).
if(TARGET pwb-platform
   AND TARGET Pwb::UiWorkstationQt AND TARGET Pwb::UiCompositeQt
   AND TARGET Pwb::UiShellQt AND TARGET Pwb::UiPagesDataQt
   AND TARGET Pwb::UiMapQgis AND TARGET Pwb::UiSeqvizQt
   AND TARGET Pwb::UiWellseisQt AND TARGET Pwb::UiPagesMapedit
   AND TARGET Pwb::Application AND TARGET Pwb::Project
   AND TARGET Pwb::UiWorkers AND TARGET Pwb::MappingDocument
   AND TARGET Pwb::VizCharts
   AND TARGET Pwb::Data AND TARGET Pwb::Science
   AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
    # Product wiring: the closure sources join pwb-platform (install call
    # in main_window.cpp compiles under PWB_WITH_CLOSURE_MAPPING).
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/closure_mapping_document.cpp
        apps/paleo_workbench_platform/closure_mapping_install.cpp)
    target_include_directories(pwb-platform PRIVATE
        apps/paleo_workbench_platform)
    target_link_libraries(pwb-platform PRIVATE
        Pwb::UiPagesMapedit Pwb::UiSeqviz Pwb::UiSeqvizQt
        Pwb::UiPagesDataQt Pwb::UiWellseis Pwb::UiWellseisQt
        Pwb::UiWorkers Pwb::MappingDocument Pwb::Project
        Pwb::VizCharts Pwb::Application)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CLOSURE_MAPPING=1)

    # BEGIN V14-FACTOR — the real factor-grid compute kernel (V14 line
    # V14-CONSTRAINT-FACTOR): mapping_kernel interpolation (idw/kriging +
    # CONV-05 constrained engine), CONV-18 envelope codec, factor_host
    # fingerprints and the workflow_runtime catalog seam. Configures without
    # the CONV-05/18 kernel slices keep the honest kernel-unavailable
    # prepare surface (closure_mapping_install falls back to the staged
    # KernelUnavailable result — never a fake grid).
    if(PWB_BUILD_CONV_05 AND PWB_BUILD_CONV_18
       AND TARGET Pwb::FactorHost AND TARGET Pwb::WorkflowRuntime)
        target_sources(pwb-platform PRIVATE
            apps/paleo_workbench_platform/factor_prepare_production.cpp)
        target_link_libraries(pwb-platform PRIVATE
            Pwb::FactorHost Pwb::WorkflowRuntime Pwb::MappingKernel)
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_FACTOR_KERNEL=1)

        add_executable(platform_factor_prepare
            tests/cpp/platform/test_factor_prepare.cpp
            apps/paleo_workbench_platform/factor_prepare_production.cpp)
        target_compile_features(platform_factor_prepare PRIVATE cxx_std_20)
        target_include_directories(platform_factor_prepare PRIVATE
            tests/cpp/platform
            apps/paleo_workbench_platform)
        target_link_libraries(platform_factor_prepare PRIVATE
            Pwb::FactorHost Pwb::WorkflowRuntime Pwb::UiWorkers
            Pwb::MappingKernel Pwb::Domain Pwb::JobContracts)
        add_test(NAME platform.factor_prepare
                 COMMAND platform_factor_prepare)
        set_tests_properties(platform.factor_prepare PROPERTIES
            TIMEOUT 600)
    endif()
    # END V14-FACTOR

    # BEGIN UI-14 WORKFLOW-WIRING — the composition root that instantiates
    # qt::WorkflowController, binds every seam bag to the real services
    # (workflow_runtime + closure_workflow compilers + the SHARED factor
    # grid store/catalog rail the mapping closure owns) and routes the
    # composite stage actions + factor-shelf signals. Compiles only with
    # the full closure above; a reduced configure keeps the pages working
    # through their own install paths (honest seam-absent degrade).
    # cpp-close-01 catalog/project closure — relocated verbatim from
    # apps/paleo_workbench_platform/CMakeLists.txt: the TARGET probe there
    # evaluated before libs/ui_controllers (root line ~1084) existed, so
    # the slice silently never joined the build. Post-hoc target_sources
    # like the CLOSURE-REVIEW block above.
    if(PWB_BUILD_CATALOG_CLOSURE
            AND TARGET Pwb::UiControllers AND TARGET Pwb::UiDataCore
            AND TARGET Pwb::Catalog AND TARGET Pwb::Project)
        target_sources(pwb-platform PRIVATE
            apps/paleo_workbench_platform/closure_catalog_service.cpp
            apps/paleo_workbench_platform/closure_catalog_install.cpp)
        target_link_libraries(pwb-platform PRIVATE
            Pwb::UiControllers Pwb::UiDataCore Pwb::Catalog Pwb::Project)
        # ICatalogApi is a Qt-free header; the seam is consumed via the
        # include path only (no link dep on the Qt-side ui_review library).
        target_include_directories(pwb-platform PRIVATE
            ${CMAKE_SOURCE_DIR}/libs/ui_review/include)
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_CATALOG_CLOSURE=1)
    endif()
    # END cpp-close-01 (relocated)
    if(TARGET Pwb::UiControllersQt AND TARGET Pwb::UiWorkstationQt
       AND TARGET Pwb::UiReviewQt AND TARGET Pwb::WorkflowRuntime)
        target_sources(pwb-platform PRIVATE
            apps/paleo_workbench_platform/workflow_install.cpp
            apps/paleo_workbench_platform/workflow_install.hpp)
        target_link_libraries(pwb-platform PRIVATE
            Pwb::UiControllers Pwb::UiControllersQt
            Pwb::UiWorkstationQt Pwb::QgisPlot Pwb::UiReviewQt Pwb::WorkflowRuntime)
        # workflow_install's constraint capabilities join when the
        # CONV-32 interpretation slice is in this configure.
        if(TARGET Pwb::WorkflowInterpretation)
            target_link_libraries(pwb-platform PRIVATE
                Pwb::WorkflowInterpretation)
        endif()
        if(TARGET Pwb::FactorFusion)
            target_link_libraries(pwb-platform PRIVATE Pwb::FactorFusion)
        endif()
        # The compile/product services join when the closure_workflow
        # slice is in this configure (PWB_BUILD_CPP_CLOSE_02); without it
        # the seams stay unset and the core degrades honestly.
        if(TARGET Pwb::ClosureWorkflow)
            target_link_libraries(pwb-platform PRIVATE Pwb::ClosureWorkflow)
        endif()
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_WORKFLOW_WIRING=1)
    endif()
    # END UI-14 WORKFLOW-WIRING

    # BEGIN V14-COMPILATION-PUBLISH — baseline link fix: main_window.cpp
    # references shell_project_actions (12-line #1421 surface) but this
    # test target's source list never carried the TU, so the target could
    # not link at 412d8baf (reproduced on a clean main worktree; A/B
    # evidence in docs/development/v14-compilation-publish/
    # 09-verification-report.md).
    add_executable(platform_closure_mapping tests/cpp/platform/test_closure_mapping.cpp
        apps/paleo_workbench_platform/app_shell.cpp
        apps/paleo_workbench_platform/main_window.cpp
        apps/paleo_workbench_platform/app_context.cpp
        apps/paleo_workbench_platform/diagnostics.cpp
        apps/paleo_workbench_platform/shell_project_actions.cpp
        apps/paleo_workbench_platform/closure_mapping_document.cpp
        apps/paleo_workbench_platform/closure_mapping_install.cpp
        apps/paleo_workbench_platform/validation_workspace_page.cpp
        apps/paleo_workbench_platform/factor_atlas_panel.cpp
        apps/paleo_workbench_platform/compilation_layer_panel.cpp
        apps/paleo_workbench_platform/profile_settings_panel.cpp
        apps/paleo_workbench_platform/reference_legend_panel.cpp
        apps/paleo_workbench_platform/factor_reference_strip.cpp
        apps/paleo_workbench_platform/workspace_compose.cpp
        apps/paleo_workbench_platform/ribbon_command_install.cpp
        apps/paleo_workbench_platform/comparison_view.cpp
        apps/paleo_workbench_platform/review_disposition_panel.cpp
        apps/paleo_workbench_platform/m5_validation_install.cpp
        apps/paleo_workbench_platform/data_lineage_panel.cpp
        apps/paleo_workbench_platform/m5_data_install.cpp
        apps/paleo_workbench_platform/layout_compose_panel.cpp
        apps/paleo_workbench_platform/layout_compose_panel.hpp
        apps/paleo_workbench_platform/m5_compose_install.cpp
        apps/paleo_workbench_platform/factor_method_config.cpp
        apps/paleo_workbench_platform/factor_method_dialogs.cpp
        apps/paleo_workbench_platform/factor_method_dialogs.hpp)
    # END V14-COMPILATION-PUBLISH
    pwb_link_job_runtime(platform_closure_mapping)
    set_target_properties(platform_closure_mapping PROPERTIES AUTOMOC ON)
    target_compile_features(platform_closure_mapping PRIVATE cxx_std_20)
    target_include_directories(platform_closure_mapping PRIVATE
        tests/cpp/platform
        apps/paleo_workbench_platform
        ${CMAKE_BINARY_DIR}/generated)
    target_link_libraries(platform_closure_mapping PRIVATE
        Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
        Pwb::PlatformServices Pwb::QgisProcessing
        Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
        Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt
        Pwb::UiSeqvizQt Pwb::UiWellseisQt Pwb::UiRibbonQt Pwb::UiWidgets
        Pwb::UiPagesMapedit Pwb::UiSeqviz Pwb::UiWellseis
        Pwb::UiWorkers Pwb::MappingDocument Pwb::Project
        Pwb::Visualization
        Pwb::VizCharts)
        target_compile_definitions(platform_closure_mapping PRIVATE
        PWB_TEST_SRC_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/cpp/platform"
        PWB_WITH_APP_SHELL=1 PWB_WITH_CLOSURE_MAPPING=1)
    # V14-FACTOR: the platform E2E test also binds the real kernel when the
    # CONV-05/18 slices are present (same degradation rule as the app; the
    # production source itself is already in the executable above).
    if(PWB_BUILD_CONV_05 AND PWB_BUILD_CONV_18
       AND TARGET Pwb::FactorHost AND TARGET Pwb::WorkflowRuntime)
        target_sources(platform_closure_mapping PRIVATE
            apps/paleo_workbench_platform/factor_prepare_production.cpp)
        target_link_libraries(platform_closure_mapping PRIVATE
            Pwb::FactorHost Pwb::WorkflowRuntime Pwb::MappingKernel)
        target_compile_definitions(platform_closure_mapping PRIVATE
            PWB_WITH_FACTOR_KERNEL=1)
    endif()
    add_test(NAME platform.closure_mapping
             COMMAND platform_closure_mapping)
    set_tests_properties(platform.closure_mapping PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)

    # M6 — ribbon visual/QA harness (plan 00-plan.md §4-M6): offscreen
    # captures the acceptance matrix into the build-tree evidence dir and
    # hard-gates the §5 structural contract. Same closure as this block;
    # runs twice (100% / QT_SCALE_FACTOR=1.5 DPI sweep).
    add_executable(platform_ribbon_visual
        tests/cpp/platform/test_ribbon_visual.cpp
        apps/paleo_workbench_platform/app_shell.cpp
        apps/paleo_workbench_platform/main_window.cpp
        apps/paleo_workbench_platform/app_context.cpp
        apps/paleo_workbench_platform/diagnostics.cpp
        apps/paleo_workbench_platform/shell_project_actions.cpp
        apps/paleo_workbench_platform/closure_mapping_document.cpp
        apps/paleo_workbench_platform/closure_mapping_install.cpp
        apps/paleo_workbench_platform/validation_workspace_page.cpp
        apps/paleo_workbench_platform/factor_atlas_panel.cpp
        apps/paleo_workbench_platform/compilation_layer_panel.cpp
        apps/paleo_workbench_platform/profile_settings_panel.cpp
        apps/paleo_workbench_platform/reference_legend_panel.cpp
        apps/paleo_workbench_platform/factor_reference_strip.cpp
        apps/paleo_workbench_platform/workspace_compose.cpp
        apps/paleo_workbench_platform/ribbon_command_install.cpp
        apps/paleo_workbench_platform/comparison_view.cpp
        apps/paleo_workbench_platform/review_disposition_panel.cpp
        apps/paleo_workbench_platform/m5_validation_install.cpp
        apps/paleo_workbench_platform/data_lineage_panel.cpp
        apps/paleo_workbench_platform/m5_data_install.cpp
        apps/paleo_workbench_platform/layout_compose_panel.cpp
        apps/paleo_workbench_platform/layout_compose_panel.hpp
        apps/paleo_workbench_platform/m5_compose_install.cpp
        apps/paleo_workbench_platform/factor_method_config.cpp
        apps/paleo_workbench_platform/factor_method_dialogs.cpp
        apps/paleo_workbench_platform/factor_method_dialogs.hpp)
    pwb_link_job_runtime(platform_ribbon_visual)
    set_target_properties(platform_ribbon_visual PROPERTIES AUTOMOC ON)
    target_compile_features(platform_ribbon_visual PRIVATE cxx_std_20)
    target_include_directories(platform_ribbon_visual PRIVATE
        tests/cpp/platform
        apps/paleo_workbench_platform
        ${CMAKE_BINARY_DIR}/generated)
    target_link_libraries(platform_ribbon_visual PRIVATE
        Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
        Pwb::PlatformServices Pwb::QgisProcessing
        Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
        Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt
        Pwb::UiSeqvizQt Pwb::UiWellseisQt Pwb::UiRibbonQt Pwb::UiWidgets
        Pwb::UiPagesMapedit Pwb::UiSeqviz Pwb::UiWellseis
        Pwb::UiWorkers Pwb::MappingDocument Pwb::Project
        Pwb::Visualization
        Pwb::VizCharts)
        target_compile_definitions(platform_ribbon_visual PRIVATE
        PWB_TEST_SRC_DIR="${CMAKE_SOURCE_DIR}/tests/cpp/platform"
        PWB_WITH_APP_SHELL=1 PWB_WITH_CLOSURE_MAPPING=1)
    # Mirror the product capability grant (qgis_editing → CONV_27): the
    # layer-tree dock adoption + ws2「约束」panel adoption compile only
    # under this define — without it the captures silently lack the
    # 图层/约束/编图图层 tabs that the shipped binary shows.
    if(PWB_BUILD_CONV_27 AND TARGET Pwb::UiWorkbench)
        target_compile_definitions(platform_ribbon_visual PRIVATE
            PWB_WITH_CONV_27=1)
        target_link_libraries(platform_ribbon_visual PRIVATE
            Pwb::UiWorkbench)
    endif()
    # 同样镜像 ws0 数据管理页的工具行接线：install_data_workspace
    # （稿式搜索/类型/状态过滤行 + 计数）只在 PWB_WITH_V14_DATA_LINEAGE
    # 下编译 —— 缺它时截图里 ws0 缺整行。
    if(TARGET Pwb::Data AND TARGET Pwb::UiPagesDataQt
       AND TARGET Pwb::UiWellseisQt)
        target_sources(platform_ribbon_visual PRIVATE
            apps/paleo_workbench_platform/closure_data_workspace.cpp
            apps/paleo_workbench_platform/closure_data_workspace.hpp)
        target_link_libraries(platform_ribbon_visual PRIVATE
            Pwb::Data Pwb::UiPagesDataQt Pwb::UiWellseis
            pwb_ui_wellseis_qt)
        target_compile_definitions(platform_ribbon_visual PRIVATE
            PWB_WITH_V14_DATA_LINEAGE=1)
    endif()
    if(PWB_BUILD_CONV_05 AND PWB_BUILD_CONV_18
       AND TARGET Pwb::FactorHost AND TARGET Pwb::WorkflowRuntime)
        target_sources(platform_ribbon_visual PRIVATE
            apps/paleo_workbench_platform/factor_prepare_production.cpp)
        target_link_libraries(platform_ribbon_visual PRIVATE
            Pwb::FactorHost Pwb::WorkflowRuntime Pwb::MappingKernel)
        target_compile_definitions(platform_ribbon_visual PRIVATE
            PWB_WITH_FACTOR_KERNEL=1)
    endif()
    set(PWB_RIBBON_VISUAL_EVIDENCE
        "${CMAKE_BINARY_DIR}/visual-evidence/ribbon")
    add_test(NAME platform.ribbon_visual
             COMMAND platform_ribbon_visual ${PWB_RIBBON_VISUAL_EVIDENCE})
    set_tests_properties(platform.ribbon_visual PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
    add_test(NAME platform.ribbon_visual_dpi15
             COMMAND platform_ribbon_visual ${PWB_RIBBON_VISUAL_EVIDENCE}-dpi15)
    set_tests_properties(platform.ribbon_visual_dpi15 PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;QT_SCALE_FACTOR=1.5;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
endif()
# END CLOSURE-MAPPING (late)

# VIZ-E app wiring (plan P-A): the data/preview page assembly mounts into
# the platform app when the full closure is present — viz_charts Qt layer,
# UI-06 data pages, and the CONV-30 job runtime (surface previews compute
# through the product JobCenter). Configures without one of those keep the
# Python pages as the production path (guard stays off, main_window hook
# compiles out).
if(PWB_BUILD_PLATFORM AND TARGET Pwb::VizChartsQt
   AND TARGET Pwb::UiPagesDataQt AND TARGET Pwb::UiWorkers
   AND TARGET Pwb::MappingKernel AND TARGET Pwb::QgisProcessing
   AND PWB_BUILD_CONV_30)
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/viz_e_dat_preview.cpp
        apps/paleo_workbench_platform/viz_e_factor_preview.cpp
        apps/paleo_workbench_platform/viz_e_hosts.cpp
        apps/paleo_workbench_platform/viz_e_install.cpp
        apps/paleo_workbench_platform/viz_e_dat_preview.hpp
        apps/paleo_workbench_platform/viz_e_factor_preview.hpp
        apps/paleo_workbench_platform/viz_e_hosts.hpp
        apps/paleo_workbench_platform/viz_e_install.hpp)
    target_link_libraries(pwb-platform PRIVATE
        Pwb::QgisPlot Pwb::VizChartsQt Pwb::UiPagesDataQt Pwb::MappingKernel)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_VIZ_E=1)
    if(BUILD_TESTING)
        add_subdirectory(tests/cpp/viz_e)
    endif()
    # BEGIN CLOSURE-PREVIEW (task 04) — unified data page, parse-registry
    # base seam and preview dispatch. Superset of the VIZ-E closure: adds
    # the AppShell-side adopt mount, the ingest registry adapter, the
    # ui_pages_preview format targets and the D→E seismic presenter
    # registration. Missing optional targets keep the plain VIZ-E mount.
    if(TARGET Pwb::UiCanvas AND TARGET Pwb::UiDataCore
       AND TARGET Pwb::Ingest AND TARGET Pwb::SeismicIo
       AND TARGET Pwb::Visualization AND TARGET Pwb::SeismicViewer
       AND TARGET Pwb::Data)
        target_sources(pwb-platform PRIVATE
            apps/paleo_workbench_platform/closure_preview_adapters.cpp
            apps/paleo_workbench_platform/closure_preview_install.cpp
            apps/paleo_workbench_platform/closure_preview_adapters.hpp
            apps/paleo_workbench_platform/closure_preview_install.hpp)
        target_link_libraries(pwb-platform PRIVATE
            Pwb::UiCanvas Pwb::UiDataCore Pwb::Ingest Pwb::SeismicIo
            Pwb::Visualization Pwb::SeismicViewer)
        target_compile_definitions(pwb-platform PRIVATE
            PWB_WITH_CLOSURE_PREVIEW=1)
        if(BUILD_TESTING AND TARGET platform_app_shell)
            # Task 04 wiring battery: the real MainWindow+AppShell with the
            # closure defines — one data page, adopted workspace, presenter
            # registry, project-refresh notification.
            add_executable(platform_closure_preview
                tests/cpp/platform/test_closure_preview.cpp
                apps/paleo_workbench_platform/main_window.cpp
                apps/paleo_workbench_platform/app_context.cpp
                apps/paleo_workbench_platform/diagnostics.cpp
                apps/paleo_workbench_platform/app_shell.cpp
                apps/paleo_workbench_platform/job_center.cpp
                apps/paleo_workbench_platform/viz_e_dat_preview.cpp
                apps/paleo_workbench_platform/viz_e_factor_preview.cpp
                apps/paleo_workbench_platform/viz_e_hosts.cpp
                apps/paleo_workbench_platform/viz_e_install.cpp
                apps/paleo_workbench_platform/closure_preview_adapters.cpp
                apps/paleo_workbench_platform/closure_preview_install.cpp
                apps/paleo_workbench_platform/validation_workspace_page.cpp
                apps/paleo_workbench_platform/factor_atlas_panel.cpp
                apps/paleo_workbench_platform/compilation_layer_panel.cpp
                apps/paleo_workbench_platform/profile_settings_panel.cpp
                apps/paleo_workbench_platform/reference_legend_panel.cpp
                apps/paleo_workbench_platform/factor_reference_strip.cpp
                apps/paleo_workbench_platform/workspace_compose.cpp
                apps/paleo_workbench_platform/ribbon_command_install.cpp
                apps/paleo_workbench_platform/comparison_view.cpp
                apps/paleo_workbench_platform/review_disposition_panel.cpp
                apps/paleo_workbench_platform/m5_validation_install.cpp
                apps/paleo_workbench_platform/data_lineage_panel.cpp
                apps/paleo_workbench_platform/m5_data_install.cpp)
            if(COMMAND pwb_link_job_runtime)
                pwb_link_job_runtime(platform_closure_preview)
            endif()
            set_target_properties(platform_closure_preview PROPERTIES
                AUTOMOC ON)
            target_compile_features(platform_closure_preview PRIVATE
                cxx_std_20)
            target_include_directories(platform_closure_preview PRIVATE
                tests/cpp/platform
                apps/paleo_workbench_platform
                ${CMAKE_BINARY_DIR}/generated)
            target_link_libraries(platform_closure_preview PRIVATE
                Pwb::QgisProcessing
                Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy
                Pwb::PlatformServices
                Pwb::UiWorkstationQt Pwb::UiCompositeQt Pwb::UiShellQt
                Pwb::UiPagesDataQt Pwb::UiMapQgis Pwb::QgisPlot Pwb::UiReviewQt
                Pwb::UiSeqvizQt Pwb::UiWellseisQt Pwb::UiRibbonQt
                Pwb::UiWidgets
                Pwb::UiCanvas Pwb::UiDataCore Pwb::Ingest Pwb::SeismicIo
                Pwb::Visualization Pwb::SeismicViewer
                Pwb::UiPagesPreview Pwb::UiPagesPreviewQt
                Pwb::VizChartsQt Pwb::MappingKernel Pwb::UiWorkers
                Pwb::QgisProcessing Pwb::Domain)
            target_compile_definitions(platform_closure_preview PRIVATE
                PWB_WITH_APP_SHELL=1 PWB_WITH_VIZ_E=1 PWB_WITH_CONV_30=1
                PWB_WITH_CLOSURE_PREVIEW=1
                PWB_TEST_SRC_DIR="${CMAKE_SOURCE_DIR}/tests/cpp/platform")
            # main_window.cpp references shell_project_actions symbols once
            # PWB_WITH_DATA_INTEGRATION propagates from Pwb::Application
            # (same gate as platform_three_stage_flow above).
            if(TARGET Pwb::Data AND TARGET Pwb::Science
               AND TARGET Pwb::Visualization AND TARGET Pwb::Workflow)
                target_sources(platform_closure_preview PRIVATE
                    apps/paleo_workbench_platform/shell_project_actions.cpp)
            endif()
            add_test(NAME platform.closure_preview
                     COMMAND platform_closure_preview)
            set_tests_properties(platform.closure_preview PROPERTIES
                ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
                ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
                TIMEOUT 300)
        endif()
    endif()
    # END CLOSURE-PREVIEW
endif()
# END VIZ-E

# BEGIN 05 — well/time-depth external presenters (05→04 contract): the
# data page previews .las/.xml well assets and time-depth CSVs through the
# 05 pages + the production well-log load seam. Requires the viz-e
# registry closure; the WLE half degrades honestly when the VIZ-A bridge
# is absent, the time-depth half needs the viz-B cross-well core.
if(TARGET pwb-platform AND TARGET Pwb::VizChartsQt
   AND TARGET Pwb::UiPagesDataQt AND TARGET Pwb::UiPagesPreviewQt
   AND TARGET Pwb::UiWorkers AND TARGET Pwb::MappingKernel
   AND TARGET Pwb::JobQt)
    target_sources(pwb-platform PRIVATE
        apps/paleo_workbench_platform/well_presenter_install.cpp
        apps/paleo_workbench_platform/well_presenter_install.hpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::UiPagesPreviewQt)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_WELL_PRESENTERS=1)
    if(TARGET Pwb::UiWorkersWleLoad)
        target_link_libraries(pwb-platform PRIVATE Pwb::UiWorkersWleLoad)
        target_compile_definitions(pwb-platform
            PRIVATE PWB_WELL_PRESENTERS_HAVE_WLE=1)
    endif()
    if(TARGET Pwb::VisualizationCrossWell)
        target_link_libraries(pwb-platform PRIVATE Pwb::VisualizationCrossWell)
        target_compile_definitions(pwb-platform
            PRIVATE PWB_WELL_PRESENTERS_HAVE_TIE=1)
    endif()
    # BEGIN V14-COMPILATION-PUBLISH — baseline configure fix: the mount
    # condition must match tests/cpp/well_crosswell's own guard, which also
    # requires Pwb::UiWorkersWleLoad. Without it every configuration with
    # the default PWB_BUILD_VIZ_B=ON and BUILD_TESTING=ON (WLE absent)
    # failed at configure time (reproduced on a clean main@412d8baf
    # worktree with the documented linux-ninja option set — A/B evidence in
    # docs/development/v14-compilation-publish/09-verification-report.md).
    if(BUILD_TESTING AND TARGET Pwb::VisualizationCrossWell
       AND TARGET Pwb::UiPagesDataQt
       AND TARGET Pwb::UiWorkersWleLoad)
        # V14-THREE-STAGE-UX: UiWorkersWleLoad only exists when the WLE
        # viewer closure joined the build (science_suite viewer track);
        # without it the tests' own first fail-closed check would abort
        # every fresh PLATFORM+DATA+VIZ-B testing configure.
        add_subdirectory(tests/cpp/well_crosswell)
    endif()
    # END V14-COMPILATION-PUBLISH
endif()
# END 05

# BEGIN CONV-04
# Task 04 (feat/cpp-conv-04-ring-clip-repair): bounded ring clip and
# closure/orientation repair kernel slice without shapely. Option declared
# here for discoverability; -DPWB_BUILD_CONV_04=ON gates the additions in
# libs/mapping_kernel. Existing CONV blocks and targets are untouched.
option(PWB_BUILD_CONV_04 "Build CONV-04 ring_ops kernel slice" OFF)
# END CONV-04
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

# BEGIN CONV-27
# Task UI closure (feat/cpp-qgis-ui-workbench-closure): three-stage
# workflow dock, domain layer tree, edit tool lifecycle, native layer
# properties, constraint panel, layout persistence. The slice lives in
# libs/ui (+ a small EditController addition in libs/qgis); the app wires
# it under PWB_WITH_CONV_27.
option(PWB_BUILD_CONV_27 "Build conv-27 QGIS workbench UI closure" OFF)
if(PWB_BUILD_CONV_27)
    if(NOT PWB_BUILD_PLATFORM)
        message(FATAL_ERROR "PWB_BUILD_CONV_27=ON requires PWB_BUILD_PLATFORM=ON")
    endif()
endif()
# END CONV-27

# ----------------------------------------------------------------- summary ---
# Print what is actually ON, and why (declared vs implied-by:<feature>).
pwb_feature_summary()

# ---------------------------------------------------------------- packaging --
# Opt-in native packaging skeleton (branch cpp-build-packaging-hardening).
# Included LAST so it never alters a configure where PWB_ENABLE_PACKAGING=OFF
# (it registers zero install rules in that case; the other worktrees are
# unaffected). When ON, the module self-activates (pwb_install_all).
include(cmake/PwbInstall.cmake)

# BEGIN native-product closure (epilogue)
# Runs after every add_subdirectory block: validates the hard closure
# fail-closed, generates pwb/app/product_capabilities.hpp and prints the
# capability/link-closure summary. Defined in cmake/PwbNativeProduct.cmake.
if(PWB_BUILD_NATIVE_PRODUCT)
    pwb_native_product_summary()
endif()
# END native-product closure (epilogue)
