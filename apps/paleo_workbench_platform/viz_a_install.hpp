// VIZ-A — line-A production wiring for the platform app. Installs:
//   1. the WLE LAS preview provider into the ingest preview registry
//      (the .las preview branch goes live process-wide; without this call
//      it reports an honest capability-unavailable message);
//   2. a well-log menu whose "打开 LAS…" action parses through the
//      JobCenter (parse off the GUI thread, cooperative token cancellation,
//      queued delivery to the well-log dock host via load_document —
//      atomic document+presentation transaction; stale deliveries from a
//      superseded open are dropped by a generation guard).
// Late outcomes after window close are dropped by the JobOwner lifecycle.
// The function is a no-op returning false when the well-log dock is absent.

#pragma once

class QMainWindow;

namespace pwb::app {
class JobCenter;
}

namespace pwb::app::viz_a {

bool install(QMainWindow* window, JobCenter* jobs);

}  // namespace pwb::app::viz_a
