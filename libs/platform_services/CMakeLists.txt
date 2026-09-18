# Platform services — settings / theme tokens / diagnostics / resources /
# Qt session policy for the CPP-A shell (CONV-PS Python retirement).
# Depends on Pwb::Qgis only for the diagnostics probe; everything else is
# Qt-only so the services stay usable in non-QGIS tooling.
add_library(pwb_platform_services STATIC
    include/pwb/platform_services/theme_service.hpp  # Q_OBJECT: feeds AUTOMOC
    src/theme_tokens.cpp
    src/theme_service.cpp
    src/settings_service.cpp
    src/qt_session_policy.cpp
    src/diagnostics_report.cpp
    src/resource_locator.cpp
)
add_library(Pwb::PlatformServices ALIAS pwb_platform_services)
target_include_directories(pwb_platform_services PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_platform_services PUBLIC cxx_std_20)
set_target_properties(pwb_platform_services PROPERTIES AUTOMOC ON)
# Platform-only builds (PWB_BUILD_DATA=OFF) do not register Pwb::Domain;
# the only thing we need from it is the header-only vendored nlohmann, so
# fall back to the same vendor dir the domain lib uses.
if(NOT DEFINED PWB_VENDOR_DIR_DEFAULT)
    set(PWB_VENDOR_DIR_DEFAULT
        "${CMAKE_CURRENT_SOURCE_DIR}/../data_suite/third_party")
endif()
target_include_directories(pwb_platform_services SYSTEM PUBLIC
    $<BUILD_INTERFACE:${PWB_VENDOR_DIR_DEFAULT}>)
if(TARGET Pwb::Domain)
    target_link_libraries(pwb_platform_services PUBLIC Pwb::Domain)
endif()
target_link_libraries(pwb_platform_services PUBLIC Qt6::Widgets Pwb::Qgis)
# Dev-tree resource resolution (resource_locator.cpp) — compile-time source
# root, overridable at runtime via PALEO_RESOURCES_DIR.
target_compile_definitions(pwb_platform_services PRIVATE
    PWB_SOURCE_DIR="${CMAKE_SOURCE_DIR}")
if(MSVC)
    target_compile_options(pwb_platform_services PRIVATE /utf-8 /W4 /permissive-)
endif()
