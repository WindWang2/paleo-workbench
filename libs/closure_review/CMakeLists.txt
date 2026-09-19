# closure_review (line 09) — the review/publish governance closure:
# Qt-free QC/versioning/export cores over the portable project JSON tree,
# the ProjectReviewActions IReviewActions backend, and headless tests over
# real .paleo.json fixtures. The Qt page (libs/ui_review) and the platform
# installer (apps/paleo_workbench_platform) stay untouched structurally —
# this library only supplies the backend they bind.
#
# Requires (fail-closed like libs/ui_review): Pwb::Project (document tree +
# manager), Pwb::UiReview (the IReviewActions contract), Pwb::UiDataCore
# (validate_ring + new_feature_id) and Pwb::MappingKernel (ring_centroid /
# signed_area) — all resolved by the platform configure before this block.

foreach(_required Pwb::Project Pwb::UiReview Pwb::UiDataCore
                  Pwb::MappingKernel Pwb::Domain)
    if(NOT TARGET ${_required})
        message(FATAL_ERROR
            "libs/closure_review requires ${_required} — enable the "
            "platform configure (PWB_BUILD_PLATFORM) first")
    endif()
endforeach()

add_library(pwb_closure_review STATIC
    src/project_review_actions.cpp
    src/report_export.cpp
    src/review_qc_core.cpp
    src/review_versioning.cpp
)
add_library(Pwb::ClosureReview ALIAS pwb_closure_review)
target_include_directories(pwb_closure_review PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_closure_review PUBLIC cxx_std_20)
# PUBLIC: headers expose domain Json/Result/DataError + ui_review
# IReviewActions and the QcInputs/CartographicQaDelegate surfaces the
# installer and tests need.
target_link_libraries(pwb_closure_review
    PUBLIC Pwb::Domain Pwb::UiReview Pwb::Project
    PRIVATE Pwb::UiDataCore Pwb::MappingKernel)

if(BUILD_TESTING)
    add_subdirectory(closure_review_tests)
endif()
