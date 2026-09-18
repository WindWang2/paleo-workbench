add_executable(pwb-platform
    main.cpp
    main_window.cpp
)
set_target_properties(pwb-platform PROPERTIES AUTOMOC ON)
target_include_directories(pwb-platform PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(pwb-platform PRIVATE cxx_std_20)
target_link_libraries(pwb-platform PRIVATE Pwb::Application Pwb::Ui)

# Runtime closure: QGIS vendor bin + Qt bin (single ABI, no PATH guessing at
# dev time; the deployed package carries its own layout instead).
set_target_properties(pwb-platform PROPERTIES
    BUILD_RPATH "${PALEO_QGIS_RUNTIME}"
    VS_DEBUGGER_ENVIRONMENT "PATH=${PWB_QT_RUNTIME};${PALEO_QGIS_RUNTIME};$ENV{PATH}")

# Dev-time self-check fixture root (deployed packages carry their own).
target_compile_definitions(pwb-platform PRIVATE
    PWB_SOURCE_DIR="${CMAKE_SOURCE_DIR}")

# WLE dock: consume C's viewer adapter (the only WLE build) when present.
if(TARGET Pwb::VisualizationWellLog)
    target_link_libraries(pwb-platform PRIVATE Pwb::VisualizationWellLog)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_WELL_LOG=1)
endif()

# D seismic viewer dock + E attribute kernels: the app is the composition
# root (E's contract: the host registers; no static auto-registration).
if(TARGET Pwb::SeismicViewer)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicViewer)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_SEISMIC_VIEWER=1)
endif()
if(TARGET Pwb::SeismicAttributes AND TARGET Pwb::Data
        AND TARGET Pwb::Science AND TARGET Pwb::Workflow)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicAttributes)
    target_compile_definitions(pwb-platform PRIVATE
        PWB_WITH_SEISMIC_ATTRIBUTES=1)
endif()
# Real SEG-Y import (M3): reader + B publication path.
if(TARGET Pwb::SeismicIo AND TARGET Pwb::Data)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicIo)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_SEISMIC_IO=1)
endif()

# BEGIN CONV-01
# Swarm task 01: the 地质因子图 action compiles into the app when the slice
# is built (libs/application carries the runner + kernel link).
if(PWB_BUILD_CONV_01)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_01=1)
endif()
# END CONV-01
# BEGIN CONV-16
# conv-16 factor statistics HUD: the dock reads pwb::mapping::GridStatistics
# (FactorGrid.statistics), so the mapping kernel joins the link closure only
# when this cluster is enabled. The interpolation flow calls
# MainWindow::showFactorStatistics once factor results land in the app.
if(PWB_BUILD_CONV_16)
    if(NOT TARGET Pwb::MappingKernel)
        message(FATAL_ERROR "PWB_BUILD_CONV_16=ON requires PWB_BUILD_MAPPING_KERNEL=ON")
    endif()
    target_sources(pwb-platform PRIVATE factor_stats_dock.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::MappingKernel)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_16=1)
endif()
# END CONV-16

# BEGIN PWB-PACKAGING
# Opt-in diagnostic helper (separate executable, NOT linked into pwb-platform).
# Built only when the app's UI/Application Qt-linked libs exist, mirroring the
# platform target's own guard. It reports the install tree it expects and is
# used by the native packaging skeleton (cmake/PwbInstall.cmake).
if(TARGET Pwb::Ui OR TARGET Pwb::Application)
    include(GNUInstallDirs)
    add_executable(pwb-diagnose diag_main.cpp)
    set_target_properties(pwb-diagnose PROPERTIES AUTOMOC ON)
    target_compile_features(pwb-diagnose PRIVATE cxx_std_20)
    target_include_directories(pwb-diagnose PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    if(TARGET Pwb::Ui)
        target_link_libraries(pwb-diagnose PRIVATE Pwb::Ui)
    else()
        target_link_libraries(pwb-diagnose PRIVATE Pwb::Application)
    endif()
    target_compile_definitions(pwb-diagnose PRIVATE
        PWB_HAS_QT
        PWB_VERSION="${PROJECT_VERSION}"
        PWB_INSTALL_PREFIX="${CMAKE_INSTALL_PREFIX}"
        PWB_RESOURCE_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/resources"
        PWB_TEMPLATE_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/templates"
        PWB_ICON_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/icons"
        PWB_SCHEMA_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/schema"
        PWB_BIN_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}")
    if(DEFINED PALEO_QGIS_RUNTIME)
        target_compile_definitions(pwb-diagnose PRIVATE
            PWB_QGIS_RUNTIME_DIR="${PALEO_QGIS_RUNTIME}")
    endif()
    if(DEFINED PWB_QT_RUNTIME)
        target_compile_definitions(pwb-diagnose PRIVATE
            PWB_QT_RUNTIME_DIR="${PWB_QT_RUNTIME}")
    endif()
endif()
# END PWB-PACKAGING
