# pwb_project — .paleo.json compatibility (schema parity, atomic IO, paths).
if(NOT DEFINED PWB_VENDOR_DIR_DEFAULT)
    set(PWB_VENDOR_DIR_DEFAULT "${CMAKE_CURRENT_SOURCE_DIR}/../data_suite/third_party")
endif()
set(PWB_VENDOR_DIR "${PWB_VENDOR_DIR_DEFAULT}" CACHE PATH "Vendored deps root")

add_library(pwb_project STATIC
    src/document.cpp
    src/manager.cpp
    src/paths.cpp
    src/schema.cpp
)
add_library(Pwb::Project ALIAS pwb_project)
target_compile_features(pwb_project PUBLIC cxx_std_20)
target_link_libraries(pwb_project PUBLIC Pwb::Domain)
target_include_directories(pwb_project
    PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
           $<BUILD_INTERFACE:${PWB_VENDOR_DIR}>
           $<INSTALL_INTERFACE:include>)
target_compile_definitions(pwb_project PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
if(MSVC)
    target_compile_options(pwb_project PRIVATE /utf-8 /W4 /permissive-)
endif()

install(TARGETS pwb_project EXPORT PwbDataTargets ARCHIVE DESTINATION lib)
install(DIRECTORY include/pwb DESTINATION include)

# BEGIN CONV-26
# Save-As artifact relocation (staged copy/move + owned-path rebase).
target_sources(pwb_project PRIVATE src/relocation.cpp)
# END CONV-26

# BEGIN CONV-33
# Version lifecycle models (implemented, not stubs): VersionSet /
# VersionSnapshot / ContourDraft / CompilationRun / WorkflowStep /
# QualityReport DTOs + Json codecs, field-for-field against
# project/models.py. Prerequisite for workflow/versioning.py (CONV-33).
target_sources(pwb_project PRIVATE src/version_models.cpp)
# END CONV-33
