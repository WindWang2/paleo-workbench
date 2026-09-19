# CONV-02 — Qt-free MapDocument / MapCompositionDocument JSON kernel ported
# from paleo_workbench/mapping/layers.py + mapping/composer/models.py
# (full-conversion plan M6: pipeline MapDocument leaf). Frozen against the
# Python oracle via tools/oracle/generate_map_document_fixtures.py.
#
# CONV-27 — the behavior layer on top of that kernel: CompositionEditSession,
# MapDocumentEditSession (undo/redo), revisions/dirty state, immutable
# snapshots, document_io feature normalization and atomic file IO with
# recovery. Frozen via tools/oracle/generate_map_document_edit_fixtures.py.
#
# CONV-27d — the bridge edit domain (still Qt-free): native edit session
# controller + session set + gesture manager (topology-edit migration M0/M1
# host logic) and the renderer-neutral legacy-document render snapshot
# adapter. Frozen via tools/oracle/generate_map_document_bridge_fixtures.py.
add_library(pwb_mapping_document STATIC
    src/map_document.cpp
    src/composition.cpp
    src/edit_command.cpp
    src/composition_session.cpp
    src/map_document_session.cpp
    src/map_document_snapshot.cpp
    src/document_io.cpp
    src/document_service.cpp
    src/edit_session_set.cpp
    src/edit_gesture_manager.cpp
    src/native_edit_session.cpp
    src/render_snapshot.cpp)
add_library(Pwb::MappingDocument ALIAS pwb_mapping_document)
target_include_directories(pwb_mapping_document PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_mapping_document PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_mapping_document requires Pwb::Domain "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()
target_link_libraries(pwb_mapping_document PUBLIC Pwb::Domain)

if(BUILD_TESTING)
    add_subdirectory(mapping_document_tests)
endif()
