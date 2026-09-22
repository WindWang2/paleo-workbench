# Line-03 closure_science tests.
#
# closure_science.core — the acceptance loop: real model package + real ONNX
#   Runtime end-to-end over the catalog (version rows -> inference run ->
#   DERIVED result version + run linkage + provenance), the science-service
#   catalog loop (payload source + envelope publisher), and the negative
#   set: unknown model / unknown provider / no native executor / missing
#   grid descriptor / wrong shape / missing CRS, cancellation (terminal
#   cancelled, resumable), journal restore + project-identity late-arrival
#   guard, output identity reconciliation. The ONNX Runtime library rides in
#   on the ctest environment like prediction.runtime.

add_executable(closure_science_core_test core_test.cpp)
target_link_libraries(closure_science_core_test
    PRIVATE Pwb::ClosureScience Pwb::Workflow Pwb::Domain)
target_compile_features(closure_science_core_test PRIVATE cxx_std_20)
target_compile_definitions(closure_science_core_test PRIVATE
    PWB_FIXTURE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
add_executable(closure_science_inference_hash_test inference_hash_test.cpp)
target_link_libraries(closure_science_inference_hash_test
    PRIVATE Pwb::ClosureScience)
target_compile_features(closure_science_inference_hash_test PRIVATE cxx_std_20)
target_include_directories(closure_science_inference_hash_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../src)
add_test(NAME closure_science.inference_hash
    COMMAND closure_science_inference_hash_test)
set_tests_properties(closure_science.inference_hash PROPERTIES TIMEOUT 60)

add_executable(closure_science_mock_facies_test mock_facies_test.cpp)
target_link_libraries(closure_science_mock_facies_test
    PRIVATE Pwb::ClosureScience Pwb::Workflow Pwb::Project Pwb::Domain)
target_compile_features(closure_science_mock_facies_test PRIVATE cxx_std_20)
add_test(NAME closure_science.mock_facies COMMAND closure_science_mock_facies_test)
set_tests_properties(closure_science.mock_facies PROPERTIES TIMEOUT 120)

add_test(NAME closure_science.core COMMAND closure_science_core_test)
set_tests_properties(closure_science.core PROPERTIES TIMEOUT 600)
if(PWB_ONNXRUNTIME_LIBRARY AND EXISTS "${PWB_ONNXRUNTIME_LIBRARY}")
    file(TO_CMAKE_PATH "${PWB_ONNXRUNTIME_LIBRARY}" _pwb_ort_closure_library)
    set_tests_properties(closure_science.core PROPERTIES
        ENVIRONMENT "PALEO_ONNXRUNTIME_LIBRARY=${_pwb_ort_closure_library}")
endif()

if(TARGET pwb_closure_science_qt)
    # QSignalSpy lives in Qt6::Test — not part of the platform component
    # list (same pattern as libs/ui_wellseis/ui_wellseis_tests).
    find_package(Qt6 QUIET COMPONENTS Test)
    add_executable(closure_science_qt_hooks_test qt_hooks_test.cpp)
    target_link_libraries(closure_science_qt_hooks_test
        PRIVATE Pwb::ClosureScienceQt Pwb::Domain
            Qt6::Widgets Qt6::Test)
    target_compile_features(closure_science_qt_hooks_test PRIVATE cxx_std_20)
    target_compile_definitions(closure_science_qt_hooks_test PRIVATE
        PWB_FIXTURE_DIR="${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
    set_target_properties(closure_science_qt_hooks_test PROPERTIES AUTOMOC ON)
    add_test(NAME closure_science.qt_hooks COMMAND closure_science_qt_hooks_test)
    set_tests_properties(closure_science.qt_hooks PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        TIMEOUT 300)
    if(PWB_ONNXRUNTIME_LIBRARY AND EXISTS "${PWB_ONNXRUNTIME_LIBRARY}")
        set_tests_properties(closure_science.qt_hooks PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PALEO_ONNXRUNTIME_LIBRARY=${_pwb_ort_closure_library}")
    endif()
endif()
