# pwb_domain — strong ids, stage vocabulary, errors, JSON conventions.
# Vendor dir (nlohmann single header) defaults next to data_suite so every
# module builds standalone with the same vendored dependency.
if(NOT DEFINED PWB_VENDOR_DIR_DEFAULT)
    set(PWB_VENDOR_DIR_DEFAULT "${CMAKE_CURRENT_SOURCE_DIR}/../data_suite/third_party")
endif()
set(PWB_VENDOR_DIR
    "${PWB_VENDOR_DIR_DEFAULT}"
    CACHE PATH "Directory holding nlohmann/json.hpp (vendored)")

add_library(pwb_domain STATIC
    src/ids.cpp
    src/sha256.cpp
    src/support.cpp
    src/text.cpp
)
add_library(Pwb::Domain ALIAS pwb_domain)
target_compile_features(pwb_domain PUBLIC cxx_std_20)
target_include_directories(pwb_domain
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<BUILD_INTERFACE:${PWB_VENDOR_DIR}>
        $<INSTALL_INTERFACE:include>)
target_compile_definitions(pwb_domain PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
if(MSVC)
    target_compile_options(pwb_domain PRIVATE /utf-8 /W4 /permissive-)
endif()

install(TARGETS pwb_domain EXPORT PwbDataTargets
        ARCHIVE DESTINATION lib
        LIBRARY DESTINATION lib
        RUNTIME DESTINATION bin)
install(DIRECTORY include/pwb DESTINATION include)
