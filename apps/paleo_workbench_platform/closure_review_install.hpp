// CLOSURE-REVIEW (line 09) — the 审核治理/可验证发布 closure install for
// the platform shell: binds the real project-backed IReviewActions
// (libs/closure_review) onto the shell's review page, replacing the
// nullptr provider with an honest binding that follows the AppContext
// store lifecycle (unbound → "未绑定工程" guard; project open → live
// QC/finalize/export over the real document, persisted through the
// store's save seam).
//
// Assembly contract: install_review_actions once after the shell exists;
// notify_project_store_changed after every project open/close. Both are
// idempotent and safe on partial binding (the page may be absent in
// trimmed hosts). No app_shell restructuring — the shell's existing
// review_page() accessor carries the wiring.

#pragma once

class QString;

namespace pwb::app {

class AppShell;
class AppContext;

namespace closure_review {

// Idempotent. Creates the shell-parented binding (QObject lifetime — the
// host never owns anything) and reflects the current store state.
void install_review_actions(AppShell* shell, AppContext* context);

// Re-evaluate the binding after the context's project store changed
// (open success / close): flips the page's project-bound state and
// refreshes its reports/documents/artifacts from the live document.
// Idempotent.
void notify_project_store_changed(AppShell* shell, AppContext* context);

}  // namespace closure_review

}  // namespace pwb::app
