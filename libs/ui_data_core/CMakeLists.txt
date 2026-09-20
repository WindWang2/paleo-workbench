# UI-03 — core-data-preview: Qt-free core of the data page / preview /
# map-edit UI behavior (libs/ui_data_core) + Qt shells (pwb_ui_data_qt).
#
# Same split as libs/job_runtime: the static core never links Qt (tests
# run headless); the Qt target exists only when Qt6::Core/Widgets are
# really there (the platform block performs the find_package).
#
# The core needs the data closure (Pwb::Catalog model types ride inside
# AssetHandle/AssetView and the paged query seam). Platform-only builds
# (PWB_BUILD_DATA=OFF, e.g. linux-gcc-release) do not register it — the
# whole library+tests then skip with a loud STATUS instead of failing the
# configure (platform_services conditional-link precedent).

if(NOT TARGET Pwb::Catalog OR NOT TARGET Pwb::Ingest)
    message(STATUS
        "ui_data_core skipped: requires Pwb::Catalog + Pwb::Ingest "
        "(set PWB_BUILD_DATA=ON; platform-only builds have no catalog)")
    return()
endif()

add_library(pwb_ui_data_core STATIC
    src/asset_table_core.cpp
    src/asset_view.cpp
    src/data_asset_registry.cpp
    src/export_service.cpp
    src/facies_groups.cpp
    src/filter_index.cpp
    src/import_service.cpp
    src/interchange_models.cpp
    src/map_edit_commands.cpp
    src/map_edit_draft.cpp
    src/map_edit_factory.cpp
    src/map_edit_geometry.cpp
    src/map_edit_items.cpp
    src/map_edit_snap.cpp
    src/map_edit_topology.cpp
    src/paged_asset_core.cpp
    src/preview_cache.cpp
    src/preview_disk_cache.cpp
    src/preview_provider.cpp
    src/preview_strategy.cpp
    src/preview_types.cpp
    src/preview_worker.cpp
    src/scanner.cpp
)
add_library(Pwb::UiDataCore ALIAS pwb_ui_data_core)
target_include_directories(pwb_ui_data_core PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_data_core PUBLIC cxx_std_20)
target_link_libraries(pwb_ui_data_core PUBLIC
    Pwb::Domain Pwb::Catalog Pwb::Ingest Pwb::Project Pwb::Interchange)

# QGraphicsItem shells need Qt6::Widgets; the platform block's QGIS SDK
# find_package already locates Core/Gui/Widgets.
if(TARGET Qt6::Widgets)
    # NOTE: asset_table_model / paged_asset_model / preview_settings_store /
    # preview_worker_qt shells are deferred (see ui-03-findings.md) — the
    # Qt-free cores they wrap are already in pwb_ui_data_core.
    add_library(pwb_ui_data_qt STATIC
        qt/src/map_edit_items.cpp
        qt/src/map_edit_draft_item.cpp
        qt/include/pwb/ui_data_qt/map_edit_items.hpp
        qt/include/pwb/ui_data_qt/map_edit_draft_item.hpp
    )
    add_library(Pwb::UiDataQt ALIAS pwb_ui_data_qt)
    target_include_directories(pwb_ui_data_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/qt/include>)
    target_compile_features(pwb_ui_data_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_data_qt PUBLIC
        Pwb::UiDataCore Qt6::Core Qt6::Widgets)
    set_target_properties(pwb_ui_data_qt PROPERTIES AUTOMOC ON)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_data_core_tests)
endif()
