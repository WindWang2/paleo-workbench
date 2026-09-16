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
target_include_directories(pwb_catalog PRIVATE ${PWB_VENDOR_DIR}/sqlite)
if(MSVC)
    set_source_files_properties(${PWB_VENDOR_DIR}/sqlite/sqlite3.c
        PROPERTIES COMPILE_OPTIONS "/W0;/utf-8")
endif()

install(TARGETS pwb_catalog EXPORT PwbDataTargets ARCHIVE DESTINATION lib)
install(DIRECTORY include/pwb DESTINATION include)
