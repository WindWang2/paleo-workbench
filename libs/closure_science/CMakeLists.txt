# Line-03 closure_science — the science/prediction product loop adapter:
# catalog payload source + envelope publisher for the CONV-28 science
# services, the native inference job service (run lifecycle, provider
# dispatch, cancellation), the built-in providers (frozen demo + real tiled
# ONNX) and the prediction task journal. The Qt target binds the production
# hooks into the ui_wellseis prediction pages.
#
# Composition only — no numeric algorithm and no inference kernel lives
# here (pwb::prediction runs ONNX; pwb::science_service composes kernels).

add_library(pwb_closure_science STATIC
    src/model_seed.cpp
    src/catalog_payload_source.cpp
    src/catalog_envelope_publisher.cpp
    src/inference_service.cpp
    src/mock_facies.cpp
    src/providers.cpp
    src/task_journal.cpp)
add_library(Pwb::ClosureScience ALIAS pwb_closure_science)
target_include_directories(pwb_closure_science PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_closure_science PUBLIC cxx_std_20)
target_link_libraries(pwb_closure_science
    PUBLIC
        Pwb::Catalog
        Pwb::Domain
        Pwb::Prediction
        Pwb::ScienceService
    PRIVATE
        Pwb::Project)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(pwb_closure_science PRIVATE -Wall -Wextra)
elseif(MSVC)
    target_compile_options(pwb_closure_science PRIVATE /utf-8 /W4 /permissive-)
endif()

if(TARGET Pwb::UiWellseisQt AND TARGET Qt6::Widgets)
    add_library(pwb_closure_science_qt STATIC
        include/pwb/closure_science/qt/page_binding.hpp
        src/qt/page_binding.cpp)
    add_library(Pwb::ClosureScienceQt ALIAS pwb_closure_science_qt)
    target_include_directories(pwb_closure_science_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_closure_science_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_closure_science_qt
        PUBLIC
            Pwb::ClosureScience
            Pwb::UiWellseisQt
        PRIVATE
            Qt6::Core
            Pwb::Catalog
            Pwb::Project)
    set_target_properties(pwb_closure_science_qt PROPERTIES AUTOMOC ON)
    if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(pwb_closure_science_qt PRIVATE -Wall -Wextra)
    elseif(MSVC)
        target_compile_options(pwb_closure_science_qt PRIVATE /utf-8 /W4
            /permissive-)
    endif()
endif()

if(BUILD_TESTING)
    add_subdirectory(closure_science_tests)
endif()
