# closure_review tests — headless Qt-free core battery over real
# .paleo.json section shapes (broken project explains its issues; clean
# project passes; export failures leave no success receipt; finalize
# guards/supersede/fingerprint; the IReviewActions backend closes the
# loop through injected delegates).

add_executable(closure_review.core_test closure_review_core_test.cpp)
target_compile_features(closure_review.core_test PRIVATE cxx_std_20)
target_link_libraries(closure_review.core_test PRIVATE
    Pwb::ClosureReview Pwb::UiReview Pwb::Project Pwb::Domain
    Pwb::UiDataCore Pwb::MappingKernel)
target_include_directories(closure_review.core_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME closure_review.core_test COMMAND closure_review.core_test)
set_tests_properties(closure_review.core_test PROPERTIES TIMEOUT 120)

# V14-COMPILATION-PUBLISH — the QC provenance registrar seam (the
# provenance_registered flag flips only on a real registration).
add_executable(closure_review.provenance_sink provenance_sink_test.cpp)
target_compile_features(closure_review.provenance_sink PRIVATE cxx_std_20)
target_link_libraries(closure_review.provenance_sink PRIVATE
    Pwb::ClosureReview Pwb::Domain Pwb::Project Pwb::UiReview)
target_include_directories(closure_review.provenance_sink PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME closure_review.provenance_sink COMMAND closure_review.provenance_sink)
set_tests_properties(closure_review.provenance_sink PROPERTIES TIMEOUT 60)
