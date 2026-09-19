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
