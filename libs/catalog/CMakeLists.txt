# pwb_catalog — canonical catalog.sqlite repository.
if(NOT DEFINED PWB_VENDOR_DIR_DEFAULT)
    set(PWB_VENDOR_DIR_DEFAULT "${CMAKE_CURRENT_SOURCE_DIR}/../data_suite/third_party")
endif()
set(PWB_VENDOR_DIR "${PWB_VENDOR_DIR_DEFAULT}" CACHE PATH "Vendored deps root")

add_library(pwb_catalog STATIC
    src/models.cpp
    src/repository.cpp
    src/sqlite.cpp
)
add_library(Pwb::Catalog ALIAS pwb_catalog)
target_compile_features(pwb_catalog PUBLIC cxx_std_20)
target_link_libraries(pwb_catalog PUBLIC Pwb::Domain Pwb::Project)
target_include_directories(pwb_catalog
    PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
           $<BUILD_INTERFACE:${PWB_VENDOR_DIR}>
           $<INSTALL_INTERFACE:include>)
target_compile_definitions(pwb_catalog PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
if(MSVC)
    target_compile_options(pwb_catalog PRIVATE /utf-8 /W4 /permissive-)
endif()

# The vendored SQLite amalgamation lives under data_suite/third_party so it
# is shared by every consumer of this library.
target_sources(pwb_catalog PRIVATE ${PWB_VENDOR_DIR}/sqlite/sqlite3.c)
target_include_directories(pwb_catalog PUBLIC ${PWB_VENDOR_DIR}/sqlite)
if(MSVC)
    set_source_files_properties(${PWB_VENDOR_DIR}/sqlite/sqlite3.c
        PROPERTIES COMPILE_OPTIONS "/W0;/utf-8")
else()
    # A-line integration fix (handed back to B): the statically vendored
    # sqlite3 must not preempt the system libsqlite3 loaded by QGIS/GDAL in
    # the integrated application — hidden visibility keeps both copies
    # isolated (each binary binds its own).
    set_source_files_properties(${PWB_VENDOR_DIR}/sqlite/sqlite3.c
        PROPERTIES COMPILE_OPTIONS "-fvisibility=hidden")
endif()

install(TARGETS pwb_catalog EXPORT PwbDataTargets ARCHIVE DESTINATION lib)
install(DIRECTORY include/pwb DESTINATION include)

# BEGIN CONV-15
# Catalog GC / payload dedup / entity pagination (conv-15): new TUs only —
# the existing add_library list above is untouched.
target_sources(pwb_catalog PRIVATE
    src/gc.cpp
    src/dedup.cpp
    src/entity_view.cpp
)
# END CONV-15

# BEGIN CONV-26
# SQL-level paged asset reads (conv-26): serves deterministic pages straight
# from catalog.sqlite without materializing the document (db.py
# _search_assets_page / _count_assets parity). New TU only.
target_sources(pwb_catalog PRIVATE
    src/paged_sql.cpp
)
# END CONV-26

# BEGIN CONV-31
# Catalog domain core (conv-31): document indexes, seam value types,
# checksum, policy layers (governance / artifact policy / port roles /
# model gates), telemetry, lineage walks, impact/staleness, explain,
# missing-source scan + relink, queries, tags collaborator, legacy
# migration/projection, structural audit, V11 policy core and the trash /
# working-copy storage surface. New TUs only — the existing lists above
# are untouched.
target_sources(pwb_catalog PRIVATE
    src/document_index.cpp
    src/refs.cpp
    src/checksum.cpp
    src/policies.cpp
    src/telemetry.cpp
    src/lineage_graph.cpp
    src/impact.cpp
    src/explain.cpp
    src/sources.cpp
    src/queries.cpp
    src/tags.cpp
    src/legacy_migration.cpp
    src/audit.cpp
    src/v11_policy.cpp
    src/trash.cpp
)
# END CONV-31

# BEGIN CONV-31B
# Catalog service/db deep core (conv-31b): the DirtySet write channel
# (apply_changes/reconcile/rebuild/sync/is_fresh), the SQL read side
# (14 lazy reads + the query surface), the service orchestration core
# (open health matrix / _save / _BatchSave / _CatalogMaps), the
# working-copy state machine, the resolve_path ladder, the service-level
# trash/restore/purge orchestration, the model registry, the governance
# metadata pipeline, the #849-1 promote shapes and the V11 bundle
# orchestration. New TUs only — dedup.cpp/gc.cpp/repository.cpp/models.cpp
# were EXTENDED in place and stay in their existing lists above
# (row_mapping.hpp is a private header, not a TU).
target_sources(pwb_catalog PRIVATE
    src/apply_changes.cpp
    src/queries_sql.cpp
    src/service_core.cpp
    src/working_copy.cpp
    src/resolve.cpp
    src/trash_service.cpp
    src/model_registry.cpp
    src/asset_metadata.cpp
    src/version_promote.cpp
    src/v11_bundle.cpp
)
# END CONV-31B

# BEGIN PWB-V14-DATA-LINEAGE
# Manual-edit provenance assembly (catalog/lifecycle.py register/complete
# parity). The entity-workspace batched reads (run_ids_touching_assets /
# asset_version_rollups_sql) extend src/queries_sql.cpp in place above.
target_sources(pwb_catalog PRIVATE
    src/manual_edit.cpp
)
# END PWB-V14-DATA-LINEAGE
