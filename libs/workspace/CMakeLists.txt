# pwb_workspace — stage/membership/binding state codec.
if(NOT DEFINED PWB_VENDOR_DIR_DEFAULT)
    set(PWB_VENDOR_DIR_DEFAULT "${CMAKE_CURRENT_SOURCE_DIR}/../data_suite/third_party")
endif()
set(PWB_VENDOR_DIR "${PWB_VENDOR_DIR_DEFAULT}" CACHE PATH "Vendored deps root")

add_library(pwb_workspace STATIC
    src/state.cpp
)
add_library(Pwb::Workspace ALIAS pwb_workspace)
target_compile_features(pwb_workspace PUBLIC cxx_std_20)
target_link_libraries(pwb_workspace PUBLIC Pwb::Domain)
target_include_directories(pwb_workspace
    PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
           $<BUILD_INTERFACE:${PWB_VENDOR_DIR}>
           $<INSTALL_INTERFACE:include>)
target_compile_definitions(pwb_workspace PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
if(MSVC)
    target_compile_options(pwb_workspace PRIVATE /utf-8 /W4 /permissive-)
endif()

install(TARGETS pwb_workspace EXPORT PwbDataTargets ARCHIVE DESTINATION lib)
install(DIRECTORY include/pwb DESTINATION include)

# BEGIN CONV-26
# Membership mutation surface (set/remove/rebind + stale-reference repair).
target_sources(pwb_workspace PRIVATE src/mutations.cpp)
# END CONV-26

# BEGIN V14-QGIS-CONTROL
# Layer control plane core (Qt-free), post QGIS-native convergence: the
# state behavior surface and the version->usage reverse query (ports of
# mapping_workspace/{stage_state behavior,source_usage}.py). The
# ordering engine, domain tree model and keyed-LCS diff retired with the
# second layer tree (QgsLayerTree is the runtime authority).
target_sources(pwb_workspace PRIVATE
    src/state_ops.cpp
    src/source_usage.cpp)
if(BUILD_TESTING)
    add_subdirectory(workspace_tests)
endif()
# END V14-QGIS-CONTROL
