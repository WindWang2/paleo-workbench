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
    add_subdirectory(libs/workflow_graph)
endif()
# END CONV-25
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
    if(NOT TARGET pwb_science)
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
# BEGIN CONV-27C (subdirectory) — added after the data and CONV-02 blocks so
# Pwb::Domain and Pwb::MappingDocument exist when the library configures.
if(PWB_BUILD_CONV_27C)
    add_subdirectory(libs/cartography)
endif()
# END CONV-27C (subdirectory)
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
    add_subdirectory(libs/workflow_engine)
endif()
# END CONV-07
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
# BEGIN CONV-09
# M8 first slice: DTW well-log matcher kernel (viz/dtw_log_matcher.py port),
# Qt-free, frozen against the Python oracle. Tests need Pwb::Domain
# (configure with -DPWB_BUILD_DATA=ON).
option(PWB_BUILD_CONV_09
    "Build the CONV-09 well_science DTW kernel (M8 first slice)" OFF)
if(PWB_BUILD_CONV_09)
    pwb_add_subdirectory_once(libs/well_science)
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
# BEGIN CONV-14
option(PWB_BUILD_CONV_14
    "Build the interchange path-safety/manifest/preflight kernel (conv-14)" OFF)
if(PWB_BUILD_CONV_14)
    add_subdirectory(libs/interchange)
endif()
# END CONV-14
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
    add_subdirectory(libs/application)
    add_subdirectory(libs/ui)
    add_subdirectory(libs/platform_services)
    add_subdirectory(libs/ui_widgets)
    add_subdirectory(libs/ui_shell)
    add_subdirectory(libs/ui_data_core)
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
